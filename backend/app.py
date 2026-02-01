import os
import io
import json
import time
import asyncio
import hashlib
from typing import Optional, Any, Dict, List

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


load_dotenv()

app = FastAPI()

# ----------------------------
# Config
# ----------------------------
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_DB = int(os.environ.get("REDIS_DB", "0"))
REDIS_TTL_SECONDS = int(os.environ.get("REDIS_TTL_SECONDS", "86400"))

# auto-capture가 4초면 throttle은 4~5초가 맞음 (너는 6초라 충돌이 잦음)
MIN_SECONDS_PER_SESSION = float(os.environ.get("MIN_SECONDS_PER_SESSION", "4"))
REQUEST_TIMEOUT_SECONDS = float(os.environ.get("REQUEST_TIMEOUT_SECONDS", "20"))

# 🔒 Busy 락 TTL (Gemini timeout보다 조금 크게)
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
model = genai.GenerativeModel("gemini-2.5-pro")

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
# 🔒 Redis distributed lock helpers (핵심 수정)
# ----------------------------
def acquire_lock(session_id: str) -> bool:
    """
    락을 잡으면 True, 이미 잡혀있으면 False.
    Redis 없으면 항상 True (단일 프로세스 가정).
    """
    if not USE_REDIS:
        return True
    token = str(time.time())
    # SET key value NX EX ttl  => 분산락 기본 패턴
    return bool(redis_client.set(k_lock(session_id), token, nx=True, ex=LOCK_TTL_SECONDS))

def release_lock(session_id: str):
    if USE_REDIS:
        redis_client.delete(k_lock(session_id))


# ----------------------------
# JSON schema models
# ----------------------------
class ProspectedIssue(BaseModel):
    rank: int = Field(ge=1, le=3)
    issue_name: str
    suspected_cause: str
    confidence: float = Field(ge=0.0, le=1.0)
    symptoms_match: list[str]
    category: str

class HomeIssueExtraction(BaseModel):
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
    return """You are a home repair expert analyzing images of household issues (plumbing, electrical, HVAC, structural, etc.).

Your job is to identify the TOP 3 MOST LIKELY ISSUES and rank them by likelihood. This JSON will be fed to a second LLM that will use RAG to find repair manuals and provide solutions.

Return ONLY valid JSON matching this exact schema:
{
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
""".strip()


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


# ----------------------------
# Debug endpoints
# ----------------------------
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


# ----------------------------
# Main endpoints
# ----------------------------
@app.post("/frame")
async def analyze_frame(
    image: UploadFile = File(...),
    session_id: str = Form("demo-session-1"),
):
    # ✅ 1) 분산락 먼저 (여기서 busy 판정)
    if not acquire_lock(session_id):
        return {
            "success": False,
            "skipped": True,
            "reason": "busy",
            "session_id": session_id,
            "status": get_status(session_id),
        }

    # ✅ 2) 어떤 에러가 나도 finally에서 락/상태 해제
    try:
        # throttle은 락 잡고 나서 체크해야 “동시 요청” 경쟁이 줄어듦
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

        # Gemini 호출
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

        store_analysis(session_id, parsed.model_dump(), raw_response=raw_text[:4000])
        return {"success": True, "session_id": session_id, "data": parsed.model_dump()}

    finally:
        # ✅ 어떤 경우든 상태/락 해제
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


# ----------------------------
# RAG Solution endpoint
# ----------------------------
class SolutionRequest(BaseModel):
    session_id: str = "demo-session-1"

@app.post("/solution")
async def generate_solution(req: SolutionRequest):
    session_id = req.session_id

    latest_item = get_latest(session_id)
    if not latest_item:
        return {"success": False, "error": "No analysis found for session", "session_id": session_id}

    analysis = latest_item.get("data") if isinstance(latest_item, dict) else None
    if not analysis or not isinstance(analysis, dict) or "prospected_issues" not in analysis:
        return {"success": False, "error": "Latest analysis missing data", "session_id": session_id}

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
    # ✅ 파일명이 main.py면 이게 맞음
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
