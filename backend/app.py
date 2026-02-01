import os
import io
import json
import time
import asyncio
import hashlib
from typing import Optional, Any, Dict, List, Literal, Tuple

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import redis
import PIL.Image

import google.generativeai as genai

# 너가 만든 모듈들
try:
    from rag_index import rag_retrieve
    from query_builder import analysis_to_query
    RAG_ENABLED = True
except Exception as e:
    print("⚠️ RAG import failed:", e)
    RAG_ENABLED = False

    def rag_retrieve(query: str, top_k: int = 6):
        return []

    def analysis_to_query(analysis: dict):
        return "home repair issue"

# Llama reasoning pipeline (new)
try:
    from reasoner import refine_observation_and_build_query
    from planner import generate_fix_plan
    from schemas import VectorRetrievalMetrics, SolutionResponseV2
    LLAMA_ENABLED = True
    print("✅ Llama reasoning pipeline loaded")
except Exception as e:
    print(f"⚠️ Llama pipeline import failed: {e}")
    print("   Make sure to install: pip install groq")
    print("   And set GROQ_API_KEY in .env")
    LLAMA_ENABLED = False


load_dotenv()

app = FastAPI()

# ----------------------------
# Config
# ----------------------------
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_DB = int(os.environ.get("REDIS_DB", "0"))
REDIS_TTL_SECONDS = int(os.environ.get("REDIS_TTL_SECONDS", "86400"))

MIN_SECONDS_PER_SESSION = float(os.environ.get("MIN_SECONDS_PER_SESSION", "4"))
REQUEST_TIMEOUT_SECONDS = float(os.environ.get("REQUEST_TIMEOUT_SECONDS", "20"))

LOCK_TTL_SECONDS = int(os.environ.get("LOCK_TTL_SECONDS", "30"))

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise RuntimeError("Missing GEMINI_API_KEY. Put it in backend/.env or export it.")

# ----------------------------
# Redis connection (fallback to in-memory)
# ----------------------------
analysis_history: Dict[str, List[dict]] = {}
latest_by_session: Dict[str, dict] = {}
status_by_session: Dict[str, str] = {}
last_call_by_session: Dict[str, float] = {}
last_hash_by_session: Dict[str, str] = {}

# Guide fallback memory
guide_state_by_session: Dict[str, dict] = {}

try:
    redis_client = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        decode_responses=True,
        socket_connect_timeout=2,
    )
    redis_client.ping()
    USE_REDIS = True
    print(f"✅ Connected to Redis at {REDIS_HOST}:{REDIS_PORT} db={REDIS_DB}")
except (redis.ConnectionError, redis.TimeoutError) as e:
    USE_REDIS = False
    print(f"⚠️ Redis not available ({e}), using in-memory storage")

# ----------------------------
# CORS
# ----------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:8081",
        "http://127.0.0.1:8081",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------
# Gemini
# ----------------------------
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.0-flash")

# ----------------------------
# Redis key helpers
# ----------------------------
def k_latest(session_id: str) -> str:
    return f"session:{session_id}:latest"

def k_history(session_id: str) -> str:
    return f"session:{session_id}:history"

def k_status(session_id: str) -> str:
    return f"session:{session_id}:status"

def k_last_call(session_id: str) -> str:
    return f"session:{session_id}:last_call"

def k_last_hash(session_id: str) -> str:
    return f"session:{session_id}:last_hash"

def k_solution_latest(session_id: str) -> str:
    return f"session:{session_id}:solution:latest"

def k_lock(session_id: str) -> str:
    return f"session:{session_id}:lock"

def k_guide_state(session_id: str) -> str:
    return f"session:{session_id}:guide:state"

def k_guide_plan(session_id: str) -> str:
    return f"session:{session_id}:guide:plan"

# ----------------------------
# State store helpers
# ----------------------------
def set_status(session_id: str, status: str):
    if USE_REDIS:
        redis_client.set(k_status(session_id), status, ex=REDIS_TTL_SECONDS)
    else:
        status_by_session[session_id] = status

def get_status(session_id: str) -> str:
    if USE_REDIS:
        s = redis_client.get(k_status(session_id))
        return s or "idle"
    return status_by_session.get(session_id, "idle")

def should_throttle(session_id: str) -> bool:
    now = time.time()
    if USE_REDIS:
        last = redis_client.get(k_last_call(session_id))
        last = float(last) if last else 0.0
        return (now - last) < MIN_SECONDS_PER_SESSION
    last = last_call_by_session.get(session_id, 0.0)
    return (now - last) < MIN_SECONDS_PER_SESSION

def set_last_call(session_id: str):
    now = time.time()
    if USE_REDIS:
        redis_client.set(k_last_call(session_id), str(now), ex=REDIS_TTL_SECONDS)
    else:
        last_call_by_session[session_id] = now

def is_duplicate_frame(session_id: str, raw_image: bytes) -> bool:
    h = hashlib.sha256(raw_image).hexdigest()
    if USE_REDIS:
        prev = redis_client.get(k_last_hash(session_id))
        if prev == h:
            return True
        redis_client.set(k_last_hash(session_id), h, ex=REDIS_TTL_SECONDS)
        return False
    prev = last_hash_by_session.get(session_id)
    if prev == h:
        return True
    last_hash_by_session[session_id] = h
    return False

def store_analysis(session_id: str, data: dict, raw_response: Optional[str] = None):
    entry = {"timestamp": time.time(), "data": data, "raw_response": raw_response}
    if USE_REDIS:
        redis_client.set(k_latest(session_id), json.dumps(entry), ex=REDIS_TTL_SECONDS)
        redis_client.lpush(k_history(session_id), json.dumps(entry))
        redis_client.ltrim(k_history(session_id), 0, 49)
        redis_client.expire(k_history(session_id), REDIS_TTL_SECONDS)
    else:
        latest_by_session[session_id] = entry
        analysis_history.setdefault(session_id, []).append(entry)
        analysis_history[session_id] = analysis_history[session_id][-50:]

def get_latest(session_id: str) -> Optional[dict]:
    if USE_REDIS:
        raw = redis_client.get(k_latest(session_id))
        return json.loads(raw) if raw else None
    return latest_by_session.get(session_id)

def get_history(session_id: str, limit: int = 50):
    if USE_REDIS:
        items = redis_client.lrange(k_history(session_id), 0, limit - 1)
        return [json.loads(x) for x in items]
    hist = analysis_history.get(session_id, [])
    return list(reversed(hist[-limit:]))

# ----------------------------
# 🔒 Redis distributed lock helpers
# ----------------------------
def acquire_lock(session_id: str) -> bool:
    if not USE_REDIS:
        return True
    token = str(time.time())
    return bool(redis_client.set(k_lock(session_id), token, nx=True, ex=LOCK_TTL_SECONDS))

def release_lock(session_id: str):
    if USE_REDIS:
        redis_client.delete(k_lock(session_id))

# ----------------------------
# Robust JSON extraction helpers
# ----------------------------
def strip_code_fences(s: str) -> str:
    s = (s or "").strip()
    if s.startswith("```json"):
        s = s[7:]
    elif s.startswith("```"):
        s = s[3:]
    if s.endswith("```"):
        s = s[:-3]
    return s.strip()

def extract_json_object(s: str) -> str:
    s = strip_code_fences(s)
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return s.strip()
    return s[start : end + 1].strip()

# ----------------------------
# RAG citation normalize
# ----------------------------
def normalize_passages(passages: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if passages is None:
        return out
    if isinstance(passages, list) and (len(passages) == 0 or isinstance(passages[0], str)):
        for i, t in enumerate(passages[:6], start=1):
            out.append({"rank": i, "score": None, "text": t, "source": "docs"})
        return out
    if isinstance(passages, list) and (len(passages) == 0 or isinstance(passages[0], dict)):
        for i, p in enumerate(passages[:6], start=1):
            text = p.get("text") or p.get("chunk") or p.get("content") or ""
            source = p.get("source") or p.get("doc_id") or p.get("file") or "docs"
            score = p.get("score")
            out.append({"rank": i, "score": score, "text": text, "source": source})
        return out
    return [{"rank": 1, "score": None, "text": str(passages), "source": "docs"}]

# ============================================================
# ✅ 1) Extraction schema: fixture_type + visual_flags 포함
# ============================================================

FixtureType = Literal[
    "toilet",
    "sink",
    "shower",
    "bathtub",
    "floor_drain",
    "pipe",
    "water_heater",
    "hvac",
    "breaker_panel",
    "appliance",
    "unknown",
]

class VisualFlags(BaseModel):
    # ✅ “갈색 휴지 => clog” 같은 데모용 시그널을 여기에 담음
    tissue_visible: bool = False
    brown_tissue_visible: bool = False
    standing_water_visible: bool = False
    water_near_rim: bool = False
    leak_visible: bool = False
    corrosion_rust_visible: bool = False
    smoke_fire_visible: bool = False

class ProspectedIssue(BaseModel):
    rank: int = Field(ge=1, le=3)
    issue_name: str
    suspected_cause: str
    confidence: float = Field(ge=0.0, le=1.0)
    symptoms_match: list[str]
    category: str

class HomeIssueExtraction(BaseModel):
    # ✅ 라우팅 핵심
    fixture_type: FixtureType
    fixture_type_confidence: float = Field(ge=0.0, le=1.0)
    visual_flags: VisualFlags

    # 기존 필드
    no_issue_detected: bool = False
    prospected_issues: list[ProspectedIssue] = Field(min_length=3, max_length=3)
    overall_danger_level: str = Field(pattern="^(low|medium|high)$")
    location: str
    fixture: str
    observed_symptoms: list[str]
    requires_shutoff: bool
    water_present: bool
    immediate_action: str
    professional_needed: bool

def build_extraction_prompt() -> str:
    return """
You are a home repair expert analyzing ONE image of a household situation.

Your job:
(1) Identify fixture_type (closed set)
(2) Extract visual_flags (especially tissue + brown tissue)
(3) Provide a conservative issue JSON

IMPORTANT RULES:
- "Dirty bowl / stains" alone is NOT a clog. Clog requires evidence like standing water, water near rim, overflow risk, or clear blockage.
- However, for TOILET DEMO PURPOSES ONLY:
  If you see BROWN TISSUE / BROWN PAPER clumps inside toilet bowl, set visual_flags.brown_tissue_visible=true.
  If fixture_type == "toilet" AND brown_tissue_visible == true, your #1 issue SHOULD be "Toilet clogged (paper blockage)" with high confidence (>=0.85).

Return ONLY valid JSON matching this exact schema:
{
  "fixture_type": "toilet|sink|shower|bathtub|floor_drain|pipe|water_heater|hvac|breaker_panel|appliance|unknown",
  "fixture_type_confidence": 0.0,
  "visual_flags": {
    "tissue_visible": true|false,
    "brown_tissue_visible": true|false,
    "standing_water_visible": true|false,
    "water_near_rim": true|false,
    "leak_visible": true|false,
    "corrosion_rust_visible": true|false,
    "smoke_fire_visible": true|false
  },

  "no_issue_detected": true|false,
  "prospected_issues": [
    {"rank": 1, "issue_name": "...", "suspected_cause": "...", "confidence": 0.0, "symptoms_match": ["..."], "category": "plumbing"},
    {"rank": 2, "issue_name": "...", "suspected_cause": "...", "confidence": 0.0, "symptoms_match": ["..."], "category": "plumbing"},
    {"rank": 3, "issue_name": "...", "suspected_cause": "...", "confidence": 0.0, "symptoms_match": ["..."], "category": "plumbing"}
  ],
  "overall_danger_level": "low|medium|high",
  "location": "...",
  "fixture": "...",
  "observed_symptoms": ["..."],
  "requires_shutoff": true|false,
  "water_present": true|false,
  "immediate_action": "...",
  "professional_needed": true|false
}

STRICT RULES:
- Output ONLY the JSON object (no markdown, no commentary).
- Exactly 3 prospected issues.
- Confidence 0.0 to 1.0
- overall_danger_level must be low/medium/high

SPECIAL RULE:
- If no_issue_detected=true:
  - prospected_issues[0].issue_name must be exactly "No visible issue"
  - overall_danger_level must be "low"
  - requires_shutoff=false, professional_needed=false
  - immediate_action should say "Looks normal. No action needed."
""".strip()

# ============================================================
# ✅ 2) Toilet demo: Guide skeleton (고정)
# ============================================================

GuideOutcome = Literal["done", "still", "flushed_again", "reset", "danger", "skip"]

class GuideStep(BaseModel):
    step_id: int
    title: str
    instruction: str
    safety_note: Optional[str] = None
    check_hint: Optional[str] = None
    is_danger_step: bool = False

class GuideFocus(BaseModel):
    fixture: str = ""
    location: str = ""
    issue_name: str = ""
    category: str = ""

class GuideInterrupt(BaseModel):
    active: bool = False
    level: Literal["medium", "high"] = "high"
    message: str = ""
    requires_shutoff: bool = False
    created_at: float = Field(default_factory=lambda: time.time())

class GuideState(BaseModel):
    plan_id: str
    current_step: int = 1
    completed_steps: list[int] = Field(default_factory=list)
    failed_attempts: dict[str, int] = Field(default_factory=dict)
    last_updated: float = Field(default_factory=lambda: time.time())
    status: str = "active"  # active|done|paused

    active: bool = True
    focus: GuideFocus = Field(default_factory=GuideFocus)
    interrupt: GuideInterrupt = Field(default_factory=GuideInterrupt)

TOILET_CLOG_PLAN_ID = "toilet_clog_v1"

TOILET_CLOG_STEPS: list[GuideStep] = [
    GuideStep(
        step_id=1,
        title="Stop making it worse",
        instruction="Stop flushing immediately. If the water is near the rim, do NOT flush again. Watch the water level for 30 seconds.",
        safety_note="If the water is rising fast, shut off the toilet supply valve (behind the toilet, turn clockwise).",
        check_hint="Water level is stable (not rising).",
        is_danger_step=True,
    ),
    GuideStep(
        step_id=2,
        title="Plunge correctly",
        instruction="Use a flange plunger. Make a tight seal, then plunge firmly for 20–30 seconds. Wait 10 seconds to see if it drains.",
        safety_note="Avoid chemical drain cleaners (splash risk).",
        check_hint="Water drains down or at least drops.",
        is_danger_step=False,
    ),
    GuideStep(
        step_id=3,
        title="Second attempt + stop rule",
        instruction="Try plunging one more round (15–20 seconds). If still clogged, stop using the toilet and escalate.",
        safety_note="Repeated flushing increases overflow risk.",
        check_hint="Still blocked after 2 rounds.",
        is_danger_step=True,
    ),
    GuideStep(
        step_id=4,
        title="Escalate safely",
        instruction="Use a toilet auger (snake) if available. Otherwise stop and call maintenance/plumber. Keep the area dry and don’t flush.",
        safety_note="If sewage backup/overflow occurs, treat as high-risk and escalate immediately.",
        check_hint="Auger clears the clog OR you decide to call a pro.",
        is_danger_step=True,
    ),
]

GUIDE_PLANS: dict[str, list[GuideStep]] = {TOILET_CLOG_PLAN_ID: TOILET_CLOG_STEPS}

def extract_focus_from_analysis(analysis: dict) -> GuideFocus:
    issues = analysis.get("prospected_issues", []) or []
    top = issues[0] if isinstance(issues, list) and len(issues) > 0 and isinstance(issues[0], dict) else {}
    return GuideFocus(
        fixture=str(analysis.get("fixture", "") or ""),
        location=str(analysis.get("location", "") or ""),
        issue_name=str(top.get("issue_name", "") or ""),
        category=str(top.get("category", "") or ""),
    )

def is_danger_escalation(analysis: dict) -> bool:
    lvl = str(analysis.get("overall_danger_level", "low")).lower()
    requires = bool(analysis.get("requires_shutoff", False))
    return lvl == "high" or requires

def load_guide_state(session_id: str) -> Optional[GuideState]:
    if USE_REDIS:
        raw = redis_client.get(k_guide_state(session_id))
        if not raw:
            return None
        return GuideState.model_validate_json(raw)
    raw = guide_state_by_session.get(session_id)
    return GuideState.model_validate(raw) if raw else None

def save_guide_state(session_id: str, st: GuideState):
    if USE_REDIS:
        redis_client.set(k_guide_state(session_id), st.model_dump_json(), ex=REDIS_TTL_SECONDS)
    else:
        guide_state_by_session[session_id] = st.model_dump()

def get_plan_steps(plan_id: str) -> list[GuideStep]:
    return GUIDE_PLANS.get(plan_id, TOILET_CLOG_STEPS)

def clamp_step(step: int, max_step: int) -> int:
    if step < 1:
        return 1
    if step > max_step:
        return max_step
    return step

def current_step_obj(plan_id: str, state: GuideState) -> Optional[GuideStep]:
    steps = get_plan_steps(plan_id)
    idx = clamp_step(state.current_step, len(steps)) - 1
    if 0 <= idx < len(steps):
        return steps[idx]
    return None

def make_guide_overlay_payload(st: Optional[GuideState]) -> Optional[dict]:
    if not st or not st.active:
        return None

    steps = get_plan_steps(st.plan_id)
    cur = current_step_obj(st.plan_id, st)

    if st.interrupt and st.interrupt.active:
        return {
            "active": True,
            "type": "interrupt",
            "level": st.interrupt.level,
            "message": st.interrupt.message,
            "requires_shutoff": st.interrupt.requires_shutoff,
            "plan_id": st.plan_id,
            "focus": st.focus.model_dump(),
            "status": st.status,
            "current_step": st.current_step,
            "total_steps": len(steps),
        }

    if st.status == "done":
        return {
            "active": True,
            "type": "done",
            "level": "medium",
            "message": "✅ Guided Fix completed. If it still doesn’t work, escalate to maintenance/plumber.",
            "plan_id": st.plan_id,
            "focus": st.focus.model_dump(),
            "status": st.status,
            "current_step": st.current_step,
            "total_steps": len(steps),
        }

    return {
        "active": True,
        "type": "step",
        "level": "high" if (cur and cur.is_danger_step) else "medium",
        "message": (cur.instruction if cur else ""),
        "title": (cur.title if cur else ""),
        "safety_note": (cur.safety_note if cur else None),
        "check_hint": (cur.check_hint if cur else None),
        "plan_id": st.plan_id,
        "focus": st.focus.model_dump(),
        "status": st.status,
        "current_step": st.current_step,
        "total_steps": len(steps),
    }

# ============================================================
# ✅ 3) Non-toilet: 바로 LLM로 quick steps 생성
# ============================================================

class QuickStepsResponse(BaseModel):
    fixture_type: FixtureType
    steps: list[str] = Field(default_factory=list)
    safety_notes: list[str] = Field(default_factory=list)
    when_to_call_pro: list[str] = Field(default_factory=list)

def build_quick_steps_prompt(analysis: dict) -> str:
    return f"""
You are FixDad, a careful home repair assistant.
Given this analysis JSON, produce a safe step-by-step plan.

Constraints:
- Keep it short and actionable.
- No dangerous instructions (no opening gas lines, no electrical panel work beyond flipping a breaker, no chemical drain cleaners).
- If uncertain, ask for one specific next check (e.g., "take a wide shot", "show the valve", "show the label plate").
- Do NOT invent brand/model part numbers.

Return ONLY valid JSON:
{{
  "steps": ["...", "...", "..."],
  "safety_notes": ["...", "..."],
  "when_to_call_pro": ["...", "..."]
}}

ANALYSIS_JSON:
{json.dumps(analysis, ensure_ascii=False, indent=2)}
""".strip()

async def generate_quick_steps(analysis: dict) -> QuickStepsResponse:
    prompt = build_quick_steps_prompt(analysis)
    resp = await asyncio.wait_for(
        asyncio.to_thread(model.generate_content, [prompt]),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    raw_text = extract_json_object((resp.text or "").strip())
    obj = json.loads(raw_text)

    steps = obj.get("steps") or []
    safety = obj.get("safety_notes") or []
    callpro = obj.get("when_to_call_pro") or []

    if not isinstance(steps, list):
        steps = [str(steps)]
    if not isinstance(safety, list):
        safety = [str(safety)]
    if not isinstance(callpro, list):
        callpro = [str(callpro)]

    return QuickStepsResponse(
        fixture_type=str(analysis.get("fixture_type", "unknown")),
        steps=[str(x) for x in steps][:10],
        safety_notes=[str(x) for x in safety][:10],
        when_to_call_pro=[str(x) for x in callpro][:10],
    )

# ============================================================
# ✅ 4) Toilet “brown tissue => clogged” 서버 강제 override
# ============================================================

def apply_toilet_demo_overrides(parsed_dict: dict) -> dict:
    """
    fixture_type==toilet & brown_tissue_visible==true -> 무조건 clog로 확정
    """
    try:
        ft = str(parsed_dict.get("fixture_type", "unknown"))
        flags = parsed_dict.get("visual_flags") or {}
        brown = bool(flags.get("brown_tissue_visible", False))
        if ft == "toilet" and brown:
            # no_issue_detected는 false로
            parsed_dict["no_issue_detected"] = False

            # water_present는 "대개 있을 가능성"이 높지만, 여기서는 데모 안정성 위해 true로
            # (원하면 flags.standing_water_visible 기반으로 바꿔도 됨)
            parsed_dict["water_present"] = True

            # danger는 보통 low~medium. overflow risk이면 medium
            if bool(flags.get("water_near_rim", False)):
                parsed_dict["overall_danger_level"] = "medium"
                parsed_dict["requires_shutoff"] = True
                parsed_dict["professional_needed"] = False
                parsed_dict["immediate_action"] = "Stop flushing. Watch water level. Be ready to shut off the toilet supply valve if it rises."
            else:
                parsed_dict["overall_danger_level"] = "low"
                parsed_dict["requires_shutoff"] = False
                parsed_dict["professional_needed"] = False
                parsed_dict["immediate_action"] = "Stop flushing. Prepare a flange plunger and try plunging."

            # prospected_issues[0] 강제
            issues = parsed_dict.get("prospected_issues") or []
            if len(issues) != 3:
                # 혹시 LLM이 망치면 안전하게 3개 재구성
                issues = [
                    {
                        "rank": 1,
                        "issue_name": "Toilet clogged (paper blockage)",
                        "suspected_cause": "Paper/tissue buildup blocking the trap",
                        "confidence": 0.9,
                        "symptoms_match": ["brown tissue visible", "likely paper blockage"],
                        "category": "plumbing",
                    },
                    {
                        "rank": 2,
                        "issue_name": "Partial toilet clog",
                        "suspected_cause": "Partial blockage in the trapway",
                        "confidence": 0.6,
                        "symptoms_match": ["tissue visible"],
                        "category": "plumbing",
                    },
                    {
                        "rank": 3,
                        "issue_name": "Low flush / weak siphon",
                        "suspected_cause": "Weak flush may fail to clear solids",
                        "confidence": 0.35,
                        "symptoms_match": ["toilet bowl contents not clearing"],
                        "category": "plumbing",
                    },
                ]
            else:
                issues[0]["issue_name"] = "Toilet clogged (paper blockage)"
                issues[0]["suspected_cause"] = "Paper/tissue buildup blocking the trap"
                issues[0]["confidence"] = max(float(issues[0].get("confidence", 0.0)), 0.9)
                sm = issues[0].get("symptoms_match") or []
                if "brown tissue visible" not in sm:
                    sm.append("brown tissue visible")
                issues[0]["symptoms_match"] = sm
                issues[0]["category"] = issues[0].get("category") or "plumbing"
            parsed_dict["prospected_issues"] = issues

    except Exception:
        # override 실패해도 원본 유지
        pass

    return parsed_dict

# ============================================================
# Debug endpoints
# ============================================================

@app.get("/debug/redis")
async def debug_redis():
    if not USE_REDIS:
        return {"use_backend": True, "use_redis": False, "error": "Redis fallback mode"}
    return {
        "use_backend": True,
        "use_redis": True,
        "redis_host": f"{REDIS_HOST}:{REDIS_PORT}",
        "redis_db": REDIS_DB,
        "dbsize": redis_client.dbsize(),
        "sample_keys": redis_client.keys("session:*")[:50],
    }

@app.get("/status/{session_id}")
async def status(session_id: str):
    return {"success": True, "session_id": session_id, "status": get_status(session_id)}

@app.get("/debug/latest_raw/{session_id}")
async def debug_latest_raw(session_id: str):
    item = get_latest(session_id)
    if not item:
        return {"success": False, "error": "No latest", "session_id": session_id}
    return {"success": True, "session_id": session_id, "latest": item}

@app.post("/debug/write")
async def debug_write(session_id: str = Form("demo-session-1")):
    test_payload = {"hello": "world", "session_id": session_id}
    store_analysis(session_id, test_payload, raw_response="debug_write")
    return {"success": True, "wrote": True, "session_id": session_id}

# ============================================================
# Main endpoints
# ============================================================

@app.post("/frame")
async def analyze_frame(
    image: UploadFile = File(...),
    session_id: str = Form("demo-session-1"),
):
    if not acquire_lock(session_id):
        return {
            "success": False,
            "skipped": True,
            "reason": "busy",
            "session_id": session_id,
            "status": get_status(session_id),
        }

    try:
        if should_throttle(session_id):
            return {"success": False, "skipped": True, "reason": "throttled", "session_id": session_id}

        set_status(session_id, "analyzing")
        set_last_call(session_id)

        raw_image = await image.read()

        if is_duplicate_frame(session_id, raw_image):
            return {"success": False, "skipped": True, "reason": "duplicate", "session_id": session_id}

        try:
            pil_image = PIL.Image.open(io.BytesIO(raw_image))
        except Exception as e:
            return {"success": False, "error": f"Bad image: {str(e)}", "session_id": session_id}

        # ✅ (A) First LLM call: image -> JSON (fixture_type 포함)
        try:
            resp = await asyncio.wait_for(
                asyncio.to_thread(
                    model.generate_content,
                    [build_extraction_prompt(), pil_image, "Extract the JSON now. Return only JSON."],
                ),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            return {"success": False, "error": "Gemini timeout", "session_id": session_id}
        except Exception as e:
            return {"success": False, "error": f"Gemini API error: {str(e)}", "session_id": session_id}

        raw_text = (resp.text or "").strip()
        json_text = extract_json_object(raw_text)

        try:
            parsed = HomeIssueExtraction.model_validate_json(json_text)
        except Exception as e:
            store_analysis(session_id, {"error": "validation_failed"}, raw_response=raw_text[:4000])
            return {
                "success": False,
                "error": f"JSON validation failed: {str(e)}",
                "raw_response": raw_text[:1200],
                "session_id": session_id,
            }

        parsed_dict = parsed.model_dump()

        # ✅ (B) Toilet demo hard rule override
        parsed_dict = apply_toilet_demo_overrides(parsed_dict)

        # 저장
        store_analysis(session_id, parsed_dict, raw_response=raw_text[:4000])

        fixture_type = str(parsed_dict.get("fixture_type", "unknown"))
        guide_overlay = None
        quick_steps = None

        # ✅ (C) Routing
        # - toilet -> guide overlay 제공(데모 안정)
        # - non-toilet -> quick steps 바로 생성해서 리턴
        if fixture_type == "toilet":
            # guide state 있으면 overlay 반영
            st = load_guide_state(session_id)
            if st and st.active and st.status in ("active", "paused"):
                if is_danger_escalation(parsed_dict):
                    lvl = str(parsed_dict.get("overall_danger_level", "high")).lower()
                    requires = bool(parsed_dict.get("requires_shutoff", False))
                    st.interrupt = GuideInterrupt(
                        active=True,
                        level="high" if (lvl == "high" or requires) else "medium",
                        requires_shutoff=requires,
                        message=(
                            "⚠️ High-risk detected. Stop and do immediate safety steps. "
                            + (f"Immediate action: {parsed_dict.get('immediate_action','')}" if parsed_dict.get("immediate_action") else "")
                        ).strip(),
                    )
                    st.status = "paused"
                else:
                    if st.interrupt and st.interrupt.active:
                        st.interrupt.active = False
                        st.interrupt.message = ""
                        if st.status == "paused":
                            st.status = "active"

                st.last_updated = time.time()
                save_guide_state(session_id, st)
                guide_overlay = make_guide_overlay_payload(st)

        else:
            # non-toilet -> 즉시 step-by-step 생성
            try:
                qs = await generate_quick_steps(parsed_dict)
                quick_steps = qs.model_dump()
            except Exception as e:
                quick_steps = {
                    "fixture_type": fixture_type,
                    "steps": [],
                    "safety_notes": [],
                    "when_to_call_pro": [],
                    "error": f"quick_steps_failed: {str(e)[:120]}",
                }

        return {
            "success": True,
            "session_id": session_id,
            "data": parsed_dict,
            "guide_overlay": guide_overlay,
            "quick_steps": quick_steps,
        }

    finally:
        set_status(session_id, "idle")
        release_lock(session_id)

@app.get("/latest/{session_id}")
async def latest(session_id: str):
    item = get_latest(session_id)
    if not item:
        return {"success": False, "error": "No latest analysis yet", "session_id": session_id}
    return {"success": True, "session_id": session_id, "latest": item}

@app.get("/history/{session_id}")
async def history(session_id: str, limit: int = 50):
    hist = get_history(session_id, limit)
    return {
        "success": True,
        "session_id": session_id,
        "count": len(hist),
        "history": hist,
        "storage": "redis" if USE_REDIS else "in-memory",
    }

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "storage": "redis" if USE_REDIS else "in-memory",
        "redis_host": f"{REDIS_HOST}:{REDIS_PORT}",
        "redis_db": REDIS_DB,
    }

# ============================================================
# Guided Fix endpoints (toilet only)
# ============================================================

class GuideInitRequest(BaseModel):
    session_id: str = "demo-session-1"

@app.post("/guide/init")
async def guide_init(req: GuideInitRequest):
    session_id = req.session_id

    latest_item = get_latest(session_id)
    if not latest_item:
        return {"success": False, "error": "No analysis found. Capture a frame first.", "session_id": session_id}

    analysis = latest_item.get("data") if isinstance(latest_item, dict) else None
    if not analysis or not isinstance(analysis, dict):
        return {"success": False, "error": "Latest analysis missing data", "session_id": session_id}

    # ✅ toilet일 때만 guide 사용
    if str(analysis.get("fixture_type", "unknown")) != "toilet":
        return {"success": False, "error": "Guide is enabled only for toilet demo. Use quick_steps for other fixtures.", "session_id": session_id}

    plan_id = TOILET_CLOG_PLAN_ID
    steps = get_plan_steps(plan_id)

    st = load_guide_state(session_id)
    if st and st.plan_id == plan_id and st.status in ("active", "paused"):
        st.active = True
        st.last_updated = time.time()
        save_guide_state(session_id, st)
        return {
            "success": True,
            "session_id": session_id,
            "plan_id": plan_id,
            "steps": [s.model_dump() for s in steps],
            "state": st.model_dump(),
            "selected_reason": "existing state reused",
        }

    focus = extract_focus_from_analysis(analysis)
    st = GuideState(
        plan_id=plan_id,
        current_step=1,
        completed_steps=[],
        failed_attempts={},
        status="active",
        active=True,
        focus=focus,
        interrupt=GuideInterrupt(active=False),
    )
    if USE_REDIS:
        redis_client.set(k_guide_plan(session_id), plan_id, ex=REDIS_TTL_SECONDS)
    save_guide_state(session_id, st)

    return {
        "success": True,
        "session_id": session_id,
        "plan_id": plan_id,
        "steps": [s.model_dump() for s in steps],
        "state": st.model_dump(),
        "selected_reason": "toilet demo plan",
    }

@app.get("/guide/state/{session_id}")
async def guide_state(session_id: str):
    st = load_guide_state(session_id)
    if not st:
        return {"success": False, "error": "No guide state. Call /guide/init first.", "session_id": session_id}

    steps = get_plan_steps(st.plan_id)
    cur = current_step_obj(st.plan_id, st)
    overlay = make_guide_overlay_payload(st)
    return {
        "success": True,
        "session_id": session_id,
        "plan_id": st.plan_id,
        "steps": [s.model_dump() for s in steps],
        "state": st.model_dump(),
        "current_step_obj": cur.model_dump() if cur else None,
        "guide_overlay": overlay,
    }

@app.post("/guide/reset")
async def guide_reset(req: GuideInitRequest):
    session_id = req.session_id
    if USE_REDIS:
        redis_client.delete(k_guide_state(session_id))
        redis_client.delete(k_guide_plan(session_id))
    else:
        guide_state_by_session.pop(session_id, None)
    return {"success": True, "session_id": session_id, "message": "Guide reset."}

class GuideNextRequest(BaseModel):
    session_id: str = "demo-session-1"
    outcome: GuideOutcome = "skip"
    note: Optional[str] = None

@app.post("/guide/next")
async def guide_next(req: GuideNextRequest):
    session_id = req.session_id
    st = load_guide_state(session_id)
    if not st:
        return {"success": False, "error": "No guide state. Call /guide/init first.", "session_id": session_id}

    steps = get_plan_steps(st.plan_id)
    max_step = len(steps)

    if req.outcome == "reset":
        st.current_step = 1
        st.completed_steps = []
        st.failed_attempts = {}
        st.status = "active"
        st.active = True
        st.interrupt = GuideInterrupt(active=False)
        st.last_updated = time.time()
        save_guide_state(session_id, st)
        cur = current_step_obj(st.plan_id, st)
        return {
            "success": True,
            "session_id": session_id,
            "plan_id": st.plan_id,
            "steps": [s.model_dump() for s in steps],
            "state": st.model_dump(),
            "current_step_obj": cur.model_dump() if cur else None,
            "message": "Reset to step 1.",
        }

    if req.outcome == "danger":
        st.status = "paused"
        st.last_updated = time.time()
        save_guide_state(session_id, st)
        cur = current_step_obj(st.plan_id, st)
        return {
            "success": True,
            "session_id": session_id,
            "plan_id": st.plan_id,
            "steps": [s.model_dump() for s in steps],
            "state": st.model_dump(),
            "current_step_obj": cur.model_dump() if cur else None,
            "message": "Pausing: treat as high risk. Stop and escalate.",
        }

    if st.interrupt and st.interrupt.active and req.outcome in ("done", "still", "skip", "flushed_again"):
        st.interrupt.active = False
        st.interrupt.message = ""
        if st.status == "paused":
            st.status = "active"

    if req.outcome == "done":
        if st.current_step not in st.completed_steps:
            st.completed_steps.append(st.current_step)

        if st.current_step < max_step:
            st.current_step += 1
            msg = "Nice. Moving to next step."
        else:
            st.status = "done"
            msg = "All steps completed. If issue persists, escalate / call a pro."

        st.last_updated = time.time()
        save_guide_state(session_id, st)

        cur = current_step_obj(st.plan_id, st) if st.status != "done" else None
        return {
            "success": True,
            "session_id": session_id,
            "plan_id": st.plan_id,
            "steps": [s.model_dump() for s in steps],
            "state": st.model_dump(),
            "current_step_obj": cur.model_dump() if cur else None,
            "message": msg,
        }

    if req.outcome == "still":
        k = str(st.current_step)
        st.failed_attempts[k] = int(st.failed_attempts.get(k, 0)) + 1

        if st.failed_attempts[k] >= 2 and st.current_step < max_step:
            st.current_step = min(st.current_step + 1, max_step)
            msg = "Tried enough. Let’s escalate to the next step."
        else:
            msg = "Got it. Try the same step once more carefully."

        st.last_updated = time.time()
        save_guide_state(session_id, st)

        cur = current_step_obj(st.plan_id, st)
        return {
            "success": True,
            "session_id": session_id,
            "plan_id": st.plan_id,
            "steps": [s.model_dump() for s in steps],
            "state": st.model_dump(),
            "current_step_obj": cur.model_dump() if cur else None,
            "message": msg,
        }

    if req.outcome == "flushed_again":
        st.current_step = 1
        st.status = "active"
        st.last_updated = time.time()
        save_guide_state(session_id, st)

        cur = current_step_obj(st.plan_id, st)
        return {
            "success": True,
            "session_id": session_id,
            "plan_id": st.plan_id,
            "steps": [s.model_dump() for s in steps],
            "state": st.model_dump(),
            "current_step_obj": cur.model_dump() if cur else None,
            "message": "You flushed again. Overflow risk is higher now. Back to Step 1: stop flushing and stabilize the water level.",
        }

    st.last_updated = time.time()
    save_guide_state(session_id, st)
    cur = current_step_obj(st.plan_id, st)
    return {
        "success": True,
        "session_id": session_id,
        "plan_id": st.plan_id,
        "steps": [s.model_dump() for s in steps],
        "state": st.model_dump(),
        "current_step_obj": cur.model_dump() if cur else None,
        "message": "Current step returned.",
    }

# ============================================================
# RAG Solution endpoint (optional, 그대로 유지)
# ============================================================

class SolutionRequest(BaseModel):
    session_id: str = "demo-session-1"

@app.post("/solution")
async def generate_solution(req: SolutionRequest):
    """
    Generate structured fix plan using Llama reasoning pipeline.

    New flow (with Llama):
    [1] Vision LLM → Observation JSON (already done in /frame)
    [2] Llama Reasoner ① → Refine JSON, assess risk, generate query
    [3] RAG (FAISS) → Retrieve repair manuals (if needed)
    [4] Llama Reasoner ② → Structured fix plan with citation tracking
    [5] Return to frontend

    This ensures validity, reproducibility, and leverages deterministic behavior.
    """
    session_id = req.session_id
    t0_total = time.time()
    stage_latencies = {}

    # ============================================================
    # [1] Get latest analysis (Vision model output from /frame)
    # ============================================================
    latest_item = get_latest(session_id)
    if not latest_item:
        return {"success": False, "error": "No analysis found for session", "session_id": session_id}

    analysis = latest_item.get("data") if isinstance(latest_item, dict) else None
    if not analysis or not isinstance(analysis, dict):
        return {"success": False, "error": "Latest analysis missing data", "session_id": session_id}

    print(f"\n{'='*60}")
    print(f"[Solution Pipeline] Starting for session {session_id}")
    print(f"{'='*60}")

    # ============================================================
    # [2] Llama Reasoner ① - Refine JSON and generate query
    # ============================================================
    if not LLAMA_ENABLED:
        # Fallback to old Gemini-only pipeline
        return await _legacy_gemini_solution(req, analysis, session_id)

    t0 = time.time()
    print(f"[Stage 1/3] Calling Llama Reasoner ① for JSON refinement...")
    success, reasoner_output, error = refine_observation_and_build_query(analysis, session_id)
    stage_latencies["reasoner1_ms"] = (time.time() - t0) * 1000

    if not success or not reasoner_output:
        print(f"❌ [Stage 1/3] Reasoner ① failed: {error}")
        return {
            "success": False,
            "session_id": session_id,
            "error": error or "Reasoner ① failed",
            "error_stage": "reasoner1",
            "stage_latencies": stage_latencies,
        }

    print(f"✅ [Stage 1/3] Reasoner ① completed in {stage_latencies['reasoner1_ms']:.0f}ms")
    print(f"   Refined issue: {reasoner_output.refined_issue}")
    print(f"   Risk: {reasoner_output.risk_assessment.level}")
    print(f"   RAG needed: {reasoner_output.requires_rag}")

    # ============================================================
    # [3] RAG Retrieval (if needed)
    # ============================================================
    retrieved_docs = []
    retrieval_metrics = None

    if reasoner_output.requires_rag:
        t0 = time.time()
        print(f"[Stage 2/3] RAG retrieval with query: '{reasoner_output.rag_query}'")

        try:
            # Use reasoner's optimized semantic query
            passages_raw = rag_retrieve(reasoner_output.rag_query, top_k=6)
            retrieved_docs = normalize_passages(passages_raw)

            # Calculate vector retrieval metrics for statistical analysis
            if retrieved_docs:
                scores = [d.get("score") for d in retrieved_docs if d.get("score") is not None]
                retrieval_metrics = VectorRetrievalMetrics(
                    avg_similarity_score=sum(scores) / len(scores) if scores else None,
                    min_similarity_score=min(scores) if scores else None,
                    max_similarity_score=max(scores) if scores else None,
                    num_docs_retrieved=len(retrieved_docs),
                    retrieval_latency_ms=(time.time() - t0) * 1000,
                )

                print(f"✅ [Stage 2/3] Retrieved {len(retrieved_docs)} docs in {retrieval_metrics.retrieval_latency_ms:.0f}ms")
                if retrieval_metrics.avg_similarity_score:
                    print(f"   Avg similarity: {retrieval_metrics.avg_similarity_score:.3f}")
            else:
                print(f"⚠️ [Stage 2/3] No documents retrieved (query may be too specific)")

        except Exception as e:
            print(f"⚠️ [Stage 2/3] RAG retrieval failed: {str(e)}")
            # Continue without docs (planner will use fallback mode)

        stage_latencies["rag_ms"] = (time.time() - t0) * 1000
    else:
        print(f"[Stage 2/3] Skipping RAG (not required for this issue)")
        stage_latencies["rag_ms"] = 0.0

    # ============================================================
    # [4] Llama Reasoner ② - Generate structured fix plan
    # ============================================================
    t0 = time.time()
    print(f"[Stage 3/3] Calling Llama Planner (Reasoner ②) for fix plan generation...")
    success, fix_plan, error = generate_fix_plan(
        reasoner_output=reasoner_output,
        retrieved_docs=retrieved_docs,
        retrieval_metrics=retrieval_metrics,
        session_id=session_id,
    )
    stage_latencies["planner_ms"] = (time.time() - t0) * 1000

    if not success or not fix_plan:
        print(f"❌ [Stage 3/3] Planner failed: {error}")
        return {
            "success": False,
            "session_id": session_id,
            "error": error or "Planner (Reasoner ②) failed",
            "error_stage": "reasoner2",
            "reasoner_output": reasoner_output.model_dump() if reasoner_output else None,
            "stage_latencies": stage_latencies,
        }

    print(f"✅ [Stage 3/3] Planner completed in {stage_latencies['planner_ms']:.0f}ms")
    print(f"   Steps generated: {len(fix_plan.steps)}")
    print(f"   Confidence: {fix_plan.statistical_metrics.confidence:.2f}")
    print(f"   Citation coverage: {fix_plan.citation_tracker.citation_coverage:.2f}")
    print(f"   Hallucination risk: {fix_plan.citation_tracker.hallucination_risk_score:.2f}")

    # ============================================================
    # [5] Save to Redis and return
    # ============================================================
    total_latency_ms = (time.time() - t0_total) * 1000
    stage_latencies["total_ms"] = total_latency_ms

    print(f"\n{'='*60}")
    print(f"[Solution Pipeline] Completed in {total_latency_ms:.0f}ms")
    print(f"  Reasoner ①: {stage_latencies['reasoner1_ms']:.0f}ms")
    print(f"  RAG:        {stage_latencies.get('rag_ms', 0):.0f}ms")
    print(f"  Planner:    {stage_latencies['planner_ms']:.0f}ms")
    print(f"{'='*60}\n")

    if USE_REDIS:
        solution_data = {
            "reasoner_output": reasoner_output.model_dump(),
            "fix_plan": fix_plan.model_dump(),
            "timestamp": time.time(),
        }
        redis_client.set(
            k_solution_latest(session_id),
            json.dumps(solution_data),
            ex=REDIS_TTL_SECONDS,
        )

    # Return structured response (with legacy fields for backward compatibility)
    return {
        "success": True,
        "session_id": session_id,

        # New structured fields (Llama pipeline)
        "reasoner_output": reasoner_output.model_dump(),
        "fix_plan": fix_plan.model_dump(),

        # Legacy fields (for backward compatibility with frontend)
        "query": reasoner_output.rag_query,
        "citations": retrieved_docs,
        "solution": fix_plan.summary,  # Simple text summary

        # Performance metrics
        "stage_latencies": stage_latencies,
        "total_latency_ms": total_latency_ms,
    }


# ============================================================
# Legacy Gemini-only solution (fallback if Llama not available)
# ============================================================

async def _legacy_gemini_solution(req: SolutionRequest, analysis: dict, session_id: str):
    """
    Legacy solution generation using only Gemini (no Llama reasoning).
    Used as fallback when Llama pipeline is not available.
    """
    print("⚠️ Using legacy Gemini-only solution (Llama not available)")

    try:
        query = analysis_to_query(analysis)
    except Exception as e:
        return {"success": False, "error": f"analysis_to_query error: {str(e)}", "session_id": session_id}

    try:
        passages_raw = rag_retrieve(query, top_k=6)
    except Exception as e:
        return {"success": False, "error": f"rag_retrieve error: {str(e)}", "session_id": session_id}

    citations = normalize_passages(passages_raw)

    prompt = f"""
You are FixDad, a careful home repair assistant.
Use the analysis JSON and the retrieved manual excerpts to produce a safe, step-by-step plan.
If there is danger, prioritize shutoff and calling a professional.

ANALYSIS_JSON:
{json.dumps(analysis, ensure_ascii=False, indent=2)}

RETRIEVED_EXCERPTS:
{json.dumps(citations, ensure_ascii=False, indent=2)}

Output format:
1) What I think is happening (1-2 sentences)
2) Danger check (bullets)
3) Step-by-step DIY plan (numbered)
4) If it fails (next escalation)
5) Call a pro if (bullets)
6) Tools/parts checklist

Rules:
- Be specific and grounded in the excerpts.
- If you are unsure, say what to inspect next.
- Do not invent brand/model part names.
""".strip()

    try:
        resp = await asyncio.wait_for(
            asyncio.to_thread(model.generate_content, [prompt]),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        return {"success": False, "error": "Gemini timeout (solution)", "session_id": session_id}
    except Exception as e:
        return {"success": False, "error": f"Gemini API error (solution): {str(e)}", "session_id": session_id}

    solution_text = (resp.text or "").strip()

    if USE_REDIS:
        redis_client.set(k_solution_latest(session_id), solution_text, ex=REDIS_TTL_SECONDS)

    return {
        "success": True,
        "session_id": session_id,
        "query": query,
        "citations": citations,
        "solution": solution_text,
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
