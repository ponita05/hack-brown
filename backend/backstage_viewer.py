"""
backstage_viewer.py
A local-only "backstage" dashboard that explains how data flows through your system.

- Runs on 127.0.0.1 only (not accessible from other machines)
- Minimal UI, meant for judges
- Polls your existing backend endpoints:
    /debug/redis
    /latest/{session_id}
    /history/{session_id}?limit=...
    /guide/state/{session_id}        (optional; if exists)
    /solution/latest/{session_id}    (optional; if you add it)
    /debug/events/{session_id}       (optional; if you add event logging)

USAGE:
  pip install fastapi uvicorn
  python backstage_viewer.py --backend http://127.0.0.1:8000 --port 8081 --session demo-session-1

IMPORTANT (CORS):
- Your backend currently allows origins like http://localhost:8081 and http://127.0.0.1:8081
- So default port=8081 is recommended (already allowed by your backend CORS list).
- If you choose a different port, add it to backend CORS allow_origins.
"""

from __future__ import annotations

import argparse
import json
import time
from typing import Any, Dict, Optional

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI()

CONFIG: Dict[str, Any] = {
    "backend_url": "http://127.0.0.1:8000",
    "session_id": "demo-session-1",
    "viewer_started_at": time.time(),
}

# -----------------------
# Minimal HTML (no build)
# -----------------------
HTML = r"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Backstage Viewer (Local Only)</title>
  <style>
    :root {
      --bg: #0b1020;
      --panel: #121a33;
      --muted: rgba(255,255,255,0.72);
      --soft: rgba(255,255,255,0.10);
      --soft2: rgba(255,255,255,0.06);
      --good: #35d07f;
      --warn: #ffcc66;
      --bad: #ff5c7a;
      --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
      --sans: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, "Apple Color Emoji","Segoe UI Emoji";
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: radial-gradient(1200px 600px at 30% 10%, rgba(120,140,255,0.15), transparent),
                  radial-gradient(1000px 500px at 80% 20%, rgba(0,255,170,0.10), transparent),
                  var(--bg);
      color: white;
      font-family: var(--sans);
    }
    header {
      position: sticky;
      top: 0;
      z-index: 10;
      background: rgba(11,16,32,0.75);
      backdrop-filter: blur(10px);
      border-bottom: 1px solid var(--soft2);
    }
    .wrap {
      max-width: 1400px;
      margin: 0 auto;
      padding: 14px 16px;
    }
    .titlebar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }
    h1 {
      margin: 0;
      font-size: 16px;
      font-weight: 700;
      letter-spacing: 0.2px;
    }
    .pill {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 6px 10px;
      border: 1px solid var(--soft);
      border-radius: 999px;
      background: rgba(255,255,255,0.04);
      font-size: 12px;
      color: var(--muted);
      font-family: var(--mono);
      white-space: nowrap;
    }
    .grid {
      max-width: 1400px;
      margin: 0 auto;
      padding: 14px 16px 24px;
      display: grid;
      grid-template-columns: 1fr 1.25fr 1fr;
      gap: 12px;
    }
    .card {
      border: 1px solid var(--soft2);
      background: rgba(18,26,51,0.65);
      backdrop-filter: blur(10px);
      border-radius: 14px;
      overflow: hidden;
      min-height: 140px;
    }
    .card .hd {
      padding: 10px 12px;
      border-bottom: 1px solid var(--soft2);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      background: rgba(255,255,255,0.02);
    }
    .card .hd .h {
      font-size: 12px;
      font-weight: 700;
      color: rgba(255,255,255,0.88);
      letter-spacing: 0.3px;
      text-transform: uppercase;
    }
    .card .bd {
      padding: 12px;
    }
    .row { display: flex; gap: 8px; flex-wrap: wrap; }
    .k {
      font-size: 11px;
      color: rgba(255,255,255,0.65);
      font-family: var(--mono);
    }
    .v {
      font-size: 12px;
      color: rgba(255,255,255,0.92);
      font-family: var(--mono);
    }
    .ok { color: var(--good); }
    .warn { color: var(--warn); }
    .bad { color: var(--bad); }
    pre {
      margin: 0;
      font-family: var(--mono);
      font-size: 11px;
      line-height: 1.35;
      color: rgba(255,255,255,0.85);
      white-space: pre-wrap;
      word-break: break-word;
    }
    .list {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .item {
      border: 1px solid var(--soft2);
      background: rgba(255,255,255,0.03);
      border-radius: 12px;
      padding: 10px;
    }
    .item .top {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: baseline;
      margin-bottom: 6px;
    }
    .item .top .t {
      font-family: var(--mono);
      font-size: 11px;
      color: rgba(255,255,255,0.75);
    }
    .item .top .tag {
      font-family: var(--mono);
      font-size: 11px;
      padding: 2px 8px;
      border-radius: 999px;
      border: 1px solid var(--soft);
      background: rgba(0,0,0,0.15);
      color: rgba(255,255,255,0.85);
      white-space: nowrap;
    }
    .hint {
      font-size: 12px;
      color: rgba(255,255,255,0.78);
      line-height: 1.4;
    }
    .small {
      font-size: 11px;
      color: rgba(255,255,255,0.62);
      font-family: var(--mono);
    }
    .foot {
      padding: 0 16px 16px;
      max-width: 1400px;
      margin: 0 auto;
      color: rgba(255,255,255,0.55);
      font-size: 11px;
      font-family: var(--mono);
    }
    @media (max-width: 1100px) {
      .grid { grid-template-columns: 1fr; }
    }
    button {
      font-family: var(--mono);
      font-size: 11px;
      padding: 6px 10px;
      border-radius: 10px;
      border: 1px solid var(--soft);
      background: rgba(255,255,255,0.05);
      color: rgba(255,255,255,0.85);
      cursor: pointer;
    }
    button:hover { background: rgba(255,255,255,0.08); }
  </style>
</head>

<body>
  <header>
    <div class="wrap">
      <div class="titlebar">
        <h1>Backstage Viewer (Local Only)</h1>
        <div class="row">
          <span class="pill">backend: <span id="backendUrl"></span></span>
          <span class="pill">session: <span id="sessionId"></span></span>
          <span class="pill">poll: <span id="pollMs"></span>ms</span>
          <button id="forceRefresh">refresh now</button>
        </div>
      </div>
    </div>
  </header>

  <div class="grid">
    <!-- LEFT: Tips + Redis -->
    <section class="card">
      <div class="hd">
        <div class="h">Tips (Explain the pipeline)</div>
        <div class="small" id="nowTs"></div>
      </div>
      <div class="bd">
        <div class="list">
          <div class="item">
            <div class="top">
              <div class="t">What judges should look at</div>
              <div class="tag">Narrative</div>
            </div>
            <div class="hint">
              This page is a separate local-only server. It polls the backend to show how state changes over time:
              <br/>• Vision result → stored as <span class="v">latest</span> and appended to <span class="v">history</span>
              <br/>• Guided Fix state (toilet demo) → stored as <span class="v">guide:state</span>
              <br/>• Solution pipeline → stored as <span class="v">solution:latest</span> (if enabled)
            </div>
          </div>

          <div class="item">
            <div class="top">
              <div class="t">When to use RAG</div>
              <div class="tag">Demo script</div>
            </div>
            <div class="hint">
              • When you understand the analysis but need exact step-by-step instructions<br/>
              • When symptoms remain even after Guided Fix<br/>
              • When you need a parts/tools/safety checklist
            </div>
          </div>

          <div class="item" id="redisCard">
            <div class="top">
              <div class="t">Redis / Storage</div>
              <div class="tag" id="storageTag">loading...</div>
            </div>
            <pre id="redisText">Loading...</pre>
          </div>

        </div>
      </div>
    </section>

    <!-- MIDDLE: Latest Analysis + History -->
    <section class="card">
      <div class="hd">
        <div class="h">Vision Output → State Store</div>
        <div class="small" id="latestAge"></div>
      </div>
      <div class="bd">
        <div class="item">
          <div class="top">
            <div class="t">Latest snapshot (/latest)</div>
            <div class="tag" id="dangerTag">-</div>
          </div>
          <pre id="latestText">Loading...</pre>
        </div>

        <div style="height:10px"></div>

        <div class="item">
          <div class="top">
            <div class="t">Recent history (/history)</div>
            <div class="tag" id="historyTag">-</div>
          </div>
          <pre id="historyText">Loading...</pre>
        </div>
      </div>
    </section>

    <!-- RIGHT: Solution / Guide / Events -->
    <section class="card">
      <div class="hd">
        <div class="h">RAG + Groq Output</div>
        <div class="small" id="rightStatus"></div>
      </div>
      <div class="bd">
        <div class="item">
          <div class="top">
            <div class="t">Solution snapshot</div>
            <div class="tag" id="solutionTag">optional</div>
          </div>
          <pre id="solutionText">If your backend has /solution/latest/{session_id}, it will appear here.</pre>
        </div>

        <div style="height:10px"></div>

        <div class="item">
          <div class="top">
            <div class="t">Guide state (optional)</div>
            <div class="tag" id="guideTag">optional</div>
          </div>
          <pre id="guideText">If your backend has /guide/state/{session_id}, it will appear here.</pre>
        </div>

        <div style="height:10px"></div>

        <div class="item">
          <div class="top">
            <div class="t">Event trace (optional)</div>
            <div class="tag" id="eventsTag">optional</div>
          </div>
          <pre id="eventsText">If your backend has /debug/events/{session_id}, it will appear here.</pre>
        </div>
      </div>
    </section>
  </div>

  <div class="foot">
    Local only: this viewer binds to <span class="v">127.0.0.1</span> so it is not accessible externally.
  </div>

<script>
  const cfg = window.__BACKSTAGE_CONFIG__;
  const backend = cfg.backend_url;
  const sessionId = cfg.session_id;

  const POLL_MS = 600;
  const pretty = (obj) => JSON.stringify(obj, null, 2);

  const el = (id) => document.getElementById(id);

  el("backendUrl").textContent = backend;
  el("sessionId").textContent = sessionId;
  el("pollMs").textContent = POLL_MS;

  function fmtAgeSeconds(tsSec) {
    if (!tsSec) return "";
    const age = Math.max(0, (Date.now()/1000) - tsSec);
    if (age < 60) return `${age.toFixed(1)}s ago`;
    const m = Math.floor(age/60);
    return `${m}m ${Math.round(age - m*60)}s ago`;
  }

  async function safeFetchJson(url) {
    try {
      const r = await fetch(url, { cache: "no-store" });
      if (!r.ok) return { __error: `HTTP ${r.status}` };
      return await r.json();
    } catch (e) {
      return { __error: String(e) };
    }
  }

  function setTagDanger(level) {
    const tag = el("dangerTag");
    if (!level) { tag.textContent = "-"; return; }
    tag.textContent = String(level).toUpperCase();
    tag.className = "tag";
    if (level === "high") tag.classList.add("bad");
    else if (level === "medium") tag.classList.add("warn");
    else tag.classList.add("ok");
  }

  async function pollOnce() {
    el("nowTs").textContent = new Date().toLocaleTimeString();

    // Redis
    const redis = await safeFetchJson(`${backend}/debug/redis`);
    const storageTag = el("storageTag");
    if (redis.__error) {
      storageTag.textContent = "unreachable";
      storageTag.className = "tag bad";
      el("redisText").textContent = pretty(redis);
    } else {
      const useRedis = !!redis.use_redis;
      storageTag.textContent = useRedis ? "redis" : "in-memory";
      storageTag.className = "tag " + (useRedis ? "ok" : "warn");
      el("redisText").textContent = pretty(redis);
    }

    // Latest
    const latest = await safeFetchJson(`${backend}/latest/${sessionId}`);
    if (latest.__error || latest.success === false) {
      el("latestText").textContent = pretty(latest);
      setTagDanger(null);
      el("latestAge").textContent = "";
    } else {
      const entry = latest.latest || {};
      const ts = entry.timestamp;
      const data = entry.data || {};
      setTagDanger(data.overall_danger_level);
      el("latestAge").textContent = `updated: ${fmtAgeSeconds(ts)}`;
      el("latestText").textContent = pretty({
        timestamp: ts,
        fixture: data.fixture,
        location: data.location,
        no_issue_detected: data.no_issue_detected,
        overall_danger_level: data.overall_danger_level,
        requires_shutoff: data.requires_shutoff,
        immediate_action: data.immediate_action,
        top_issue: (data.prospected_issues && data.prospected_issues[0]) ? data.prospected_issues[0] : null
      });
    }

    // History
    const hist = await safeFetchJson(`${backend}/history/${sessionId}?limit=8`);
    const historyTag = el("historyTag");
    if (hist.__error || hist.success === false) {
      historyTag.textContent = "error";
      historyTag.className = "tag bad";
      el("historyText").textContent = pretty(hist);
    } else {
      historyTag.textContent = `${hist.count} entries`;
      historyTag.className = "tag ok";
      const simplified = (hist.history || []).map(h => ({
        ts: h.timestamp,
        top_issue: h.data?.prospected_issues?.[0]?.issue_name,
        danger: h.data?.overall_danger_level,
        no_issue_detected: h.data?.no_issue_detected
      }));
      el("historyText").textContent = pretty(simplified);
    }

    // Optional: solution/latest
    const sol = await safeFetchJson(`${backend}/solution/latest/${sessionId}`);
    const solTag = el("solutionTag");
    if (!sol.__error && sol.success !== false) {
      solTag.textContent = "present";
      solTag.className = "tag ok";
      el("solutionText").textContent = pretty(sol);
    } else {
      solTag.textContent = "optional";
      solTag.className = "tag";
      // keep text if endpoint missing
      if (sol.__error && String(sol.__error).includes("HTTP 404")) {
        el("solutionText").textContent =
          "Endpoint not found. Add /solution/latest/{session_id} if you want this snapshot.";
      } else if (sol.__error && String(sol.__error).includes("HTTP")) {
        el("solutionText").textContent = pretty(sol);
      }
    }

    // Optional: guide/state
    const guide = await safeFetchJson(`${backend}/guide/state/${sessionId}`);
    const guideTag = el("guideTag");
    if (!guide.__error && guide.success !== false) {
      guideTag.textContent = "present";
      guideTag.className = "tag ok";
      el("guideText").textContent = pretty({
        plan_id: guide.plan_id,
        state: guide.state,
        current_step_obj: guide.current_step_obj,
        overlay: guide.guide_overlay
      });
    } else {
      guideTag.textContent = "optional";
      guideTag.className = "tag";
      if (guide.__error && String(guide.__error).includes("HTTP 404")) {
        el("guideText").textContent =
          "Endpoint not found. If you use Guided Fix, /guide/state/{session_id} will show here.";
      }
    }

    // Optional: debug/events
    const events = await safeFetchJson(`${backend}/debug/events/${sessionId}?limit=50`);
    const eventsTag = el("eventsTag");
    if (!events.__error && events.success !== false) {
      eventsTag.textContent = "present";
      eventsTag.className = "tag ok";
      el("eventsText").textContent = pretty(events);
    } else {
      eventsTag.textContent = "optional";
      eventsTag.className = "tag";
      if (events.__error && String(events.__error).includes("HTTP 404")) {
        el("eventsText").textContent =
          "Endpoint not found. If you add an event log, you can show a live transaction trace here.";
      }
    }

    el("rightStatus").textContent = "ok";
  }

  let timer = null;
  function startPolling() {
    if (timer) clearInterval(timer);
    pollOnce();
    timer = setInterval(pollOnce, POLL_MS);
  }

  el("forceRefresh").addEventListener("click", pollOnce);
  startPolling();
</script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def index():
    # Embed config safely into the page
    cfg = {
        "backend_url": CONFIG["backend_url"].rstrip("/"),
        "session_id": CONFIG["session_id"],
        "viewer_started_at": CONFIG["viewer_started_at"],
    }
    injected = (
        "<script>window.__BACKSTAGE_CONFIG__ = "
        + json.dumps(cfg)
        + ";</script>"
    )
    html = HTML.replace("</head>", injected + "\n</head>")
    return HTMLResponse(content=html)

@app.get("/config")
async def config():
    return JSONResponse(CONFIG)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", default="http://127.0.0.1:8000", help="Your main backend URL")
    parser.add_argument("--port", type=int, default=8081, help="Viewer port (use 8081 to match your backend CORS)")
    parser.add_argument("--session", default="demo-session-1", help="Session id to view")
    args = parser.parse_args()

    CONFIG["backend_url"] = args.backend.rstrip("/")
    CONFIG["session_id"] = args.session

    import uvicorn

    # Local only: bind to 127.0.0.1 so it cannot be accessed from other machines
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")

if __name__ == "__main__":
    main()
