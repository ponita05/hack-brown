import os
import io
import json
import time
import asyncio
import hashlib
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import redis
import PIL.Image

import google.generativeai as genai

# ----------------------------
# Load environment variables
# ----------------------------
load_dotenv()

# ----------------------------
# App
# ----------------------------
app = FastAPI()

# ----------------------------
# Config
# ----------------------------
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_DB = int(os.environ.get("REDIS_DB", "0"))
REDIS_TTL_SECONDS = int(os.environ.get("REDIS_TTL_SECONDS", "86400"))

MIN_SECONDS_PER_SESSION = float(os.environ.get("MIN_SECONDS_PER_SESSION", "6"))
REQUEST_TIMEOUT_SECONDS = float(os.environ.get("REQUEST_TIMEOUT_SECONDS", "20"))

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise RuntimeError("Missing GEMINI_API_KEY. Put it in backend/.env or export it.")

# ----------------------------
# Redis connection (fallback to in-memory)
# ----------------------------
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
    analysis_history = {}
    latest_by_session = {}
    status_by_session = {}
    last_call_by_session = {}
    last_hash_by_session = {}

# ----------------------------
# CORS
# ----------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://localhost:8081"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------
# Gemini
# ----------------------------
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

# ----------------------------
# Session locks (avoid overlap)
# ----------------------------
session_locks: dict[str, asyncio.Lock] = {}

def get_lock(session_id: str) -> asyncio.Lock:
    if session_id not in session_locks:
        session_locks[session_id] = asyncio.Lock()
    return session_locks[session_id]

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

def store_analysis(session_id: str, data: dict):
    entry = {"timestamp": time.time(), "data": data}

    if USE_REDIS:
        # 1) latest snapshot
        redis_client.set(k_latest(session_id), json.dumps(entry), ex=REDIS_TTL_SECONDS)

        # 2) history list
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
# Your JSON schema models
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
- Output ONLY the JSON object.
- Exactly 3 prospected issues.
- Confidence 0.0 to 1.0
- overall_danger_level must be low/medium/high
"""

# ----------------------------
# Debug endpoints (so you can PROVE Redis writes)
# ----------------------------
@app.get("/debug/redis")
async def debug_redis():
    if not USE_REDIS:
        return {"use_redis": False, "error": "Redis fallback mode"}
    return {
        "use_redis": True,
        "redis_host": f"{REDIS_HOST}:{REDIS_PORT}",
        "redis_db": REDIS_DB,
        "dbsize": redis_client.dbsize(),
        "sample_keys": redis_client.keys("session:*")[:20],
    }

@app.post("/debug/write")
async def debug_write(session_id: str = Form("demo-session-1")):
    """Writes a test record into Redis so you can verify keys instantly."""
    test_payload = {"hello": "world", "session_id": session_id}
    store_analysis(session_id, test_payload)
    return {"success": True, "wrote": True, "session_id": session_id}

# ----------------------------
# Main endpoints
# ----------------------------
@app.post("/frame")
async def analyze_frame(
    image: UploadFile = File(...),
    session_id: str = Form("demo-session-1")
):
    lock = get_lock(session_id)

    # If already processing, don't overlap
    if lock.locked():
        return {"success": False, "skipped": True, "reason": "busy", "session_id": session_id}

    async with lock:
        if should_throttle(session_id):
            return {"success": False, "skipped": True, "reason": "throttled", "session_id": session_id}

        set_status(session_id, "analyzing")
        set_last_call(session_id)

        raw_image = await image.read()

        if is_duplicate_frame(session_id, raw_image):
            set_status(session_id, "idle")
            return {"success": False, "skipped": True, "reason": "duplicate", "session_id": session_id}

        try:
            pil_image = PIL.Image.open(io.BytesIO(raw_image))
        except Exception as e:
            set_status(session_id, "idle")
            return {"success": False, "error": f"Bad image: {str(e)}", "session_id": session_id}

        try:
            # run Gemini in a thread + timeout
            resp = await asyncio.wait_for(
                asyncio.to_thread(
                    model.generate_content,
                    [build_extraction_prompt(), pil_image, "Analyze this image and extract the JSON now."]
                ),
                timeout=REQUEST_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            set_status(session_id, "idle")
            return {"success": False, "error": "Gemini timeout", "session_id": session_id}
        except Exception as e:
            set_status(session_id, "idle")
            return {"success": False, "error": f"Gemini API error: {str(e)}", "session_id": session_id}

        text = (resp.text or "").strip()

        # strip code fences
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        try:
            parsed = HomeIssueExtraction.model_validate_json(text)
        except Exception as e:
            set_status(session_id, "idle")
            return {
                "success": False,
                "error": f"JSON validation failed: {str(e)}",
                "raw_response": text[:1000],
                "session_id": session_id
            }

        store_analysis(session_id, parsed.model_dump())
        set_status(session_id, "idle")

        return {"success": True, "session_id": session_id, "data": parsed.model_dump()}

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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
