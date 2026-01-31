# Home Issue Analyzer Backend

FastAPI backend that receives screenshot frames, analyzes them with Claude Vision, and returns structured JSON.

## Setup

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Set up your API key**:
   ```bash
   cp .env.example .env
   # Edit .env and add your ANTHROPIC_API_KEY
   ```

3. **Run the server**:
   ```bash
   python app.py
   ```

   Or with uvicorn directly:
   ```bash
   uvicorn app:app --reload --port 8000
   ```

## API Endpoints

### POST /frame
Analyzes a screenshot frame and returns structured JSON.

**Request**:
- `Content-Type: multipart/form-data`
- `image`: JPEG image file
- `session_id`: (optional) session identifier

**Response** (with top 3 prospected issues for LLM #2):
```json
{
  "success": true,
  "session_id": "demo-session-1",
  "data": {
    "prospected_issues": [
      {
        "rank": 1,
        "issue_name": "Toilet drain clog from excess toilet paper",
        "suspected_cause": "Excessive toilet paper buildup in drain pipe",
        "confidence": 0.85,
        "symptoms_match": ["Water level rising", "Slow drainage"],
        "category": "plumbing"
      },
      {
        "rank": 2,
        "issue_name": "Main drain line partial blockage",
        "suspected_cause": "Buildup in main sewer line causing backup",
        "confidence": 0.60,
        "symptoms_match": ["Water level rising", "Multiple fixtures affected"],
        "category": "plumbing"
      },
      {
        "rank": 3,
        "issue_name": "Flapper valve malfunction",
        "suspected_cause": "Faulty flapper preventing proper flush cycle",
        "confidence": 0.35,
        "symptoms_match": ["Water running continuously"],
        "category": "plumbing"
      }
    ],
    "overall_danger_level": "low",
    "location": "Bathroom toilet",
    "fixture": "Toilet bowl and drain",
    "observed_symptoms": ["Water level higher than normal", "Visible toilet paper"],
    "requires_shutoff": false,
    "water_present": true,
    "immediate_action": "Stop flushing, wait for water level to drop",
    "professional_needed": false
  },
  "raw_tokens": 1234
}
```

### GET /health
Health check endpoint.

## Architecture Flow

This is **LLM #1** (Structured Extractor) in your full pipeline:

1. ✅ **Frontend** captures frame every 4 seconds
2. ✅ **POST** to `/frame` with JPEG blob
3. ✅ **Backend** encodes to base64
4. ✅ **Claude Vision** (LLM #1) analyzes image → returns **TOP 3 PROSPECTED ISSUES**
5. ✅ **Pydantic** validates JSON schema (strict 3 issues)
6. ✅ **Return** structured data to frontend

**Why Top 3 Issues?**
The JSON with 3 ranked hypotheses will be fed to **LLM #2** (Planner) which will:
- Query RAG (FAISS + LlamaIndex) for each prospected issue
- Find relevant repair manuals/knowledge
- Generate step-by-step solutions
- Provide overlay instructions to user

## Next Steps (Full Pipeline)

- [ ] **State Store (Redis)**: Store session JSON for each user
- [ ] **RAG Query Builder**: Convert JSON issues → vector queries
- [ ] **FAISS Retriever (LlamaIndex)**: Load plumbing/repair manuals
- [ ] **LLM #2 (Planner)**: Use JSON + RAG context → generate repair steps
- [ ] **Overlay Push (WebSocket)**: Real-time step overlays on video
- [ ] **Verification Loop**: Detect when issue is fixed → show "FIXED" image
