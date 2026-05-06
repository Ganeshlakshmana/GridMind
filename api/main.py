"""
api/main.py

FastAPI backend for the GridMind dashboard.

POST /chat   — intent-routed chat endpoint (use this from the UI)
POST /run    — direct full agent run (bypass routing)
GET  /fleet, /fleet/summary, /fleet/{id}, /anomalies, /trends, /report, /escalations, /traces
"""

import asyncio
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from anthropic import Anthropic
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

app = FastAPI(title="GridMind API", version="1.0.0",
              description="VPP operations agent — fleet monitoring, diagnostics, and autonomous remediation.")

app.add_middleware(CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"], allow_headers=["*"])

_executor = ThreadPoolExecutor(max_workers=4)
_anthropic = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


# ── Models ────────────────────────────────────────────────────────────────────

class RunRequest(BaseModel):
    prompt: str
    session_id: Optional[str] = None

class ChatRequest(BaseModel):
    prompt: str

class ResolveRequest(BaseModel):
    action: str
    notes: Optional[str] = ""

class EscalateRequest(BaseModel):
    reason: str
    severity: str


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _run_sync(fn, *args, **kwargs):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, lambda: fn(*args, **kwargs))


# ── Intent classifier ─────────────────────────────────────────────────────────

_CLASSIFIER_PROMPT = """You are an intent classifier for GridMind, a VPP (Virtual Power Plant) operations dashboard managing 50 solar energy systems in Berlin.

Classify the user message into exactly one intent:

1. "agent_run"        - Requests needing autonomous decision-making, triage, fixing, or full diagnostics
                        Examples: "run a diagnostic", "fix all issues", "resolve the inverter fault", "what needs attention"

2. "show_status"      - Requests for fleet-wide status or health overview
                        Examples: "show fleet summary", "how is the fleet doing", "give me an overview"

3. "show_anomalies"   - Requests to see broken, offline, degraded, or problematic systems
                        Examples: "show offline systems", "which systems are degraded", "show warnings", "what is broken"
                        Extract: anomaly_type if mentioned (offline/low_output/battery_drain/inverter_fault)
                        Extract: status_filter if mentioned (offline/degraded/warning/healthy)

4. "show_system"      - Requests about one specific system
                        Examples: "tell me about SYS_042", "what is SYS_001 status", "show SYS_019"
                        Extract: system_id

5. "show_trends"      - Requests about trends, history, or metrics over time
                        Examples: "show output trends", "battery SOC over time", "last 12 hours"
                        Extract: metric if mentioned

6. "show_escalations" - Requests about escalation tickets or open issues needing human intervention
                        Examples: "show escalations", "open tickets", "what has been escalated"

7. "out_of_scope"     - Anything NOT related to VPP operations, solar systems, fleet, or energy management
                        Examples: weather forecasts, coding help, general knowledge, personal questions, jokes

Respond ONLY with valid JSON, no markdown fences, no extra text:
{"intent": "...", "system_id": null, "anomaly_type": null, "status_filter": null, "metric": null, "refusal_reason": null}"""


def classify_intent(prompt: str) -> dict:
    try:
        response = _anthropic.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": f"{_CLASSIFIER_PROMPT}\n\nUser message: {prompt}"}]
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except Exception as e:
        logger.error("Intent classification failed: %s", e)
        return {"intent": "agent_run", "system_id": None, "anomaly_type": None,
                "status_filter": None, "metric": None, "refusal_reason": None}


# ── /chat endpoint ────────────────────────────────────────────────────────────

@app.post("/chat", summary="Intent-routed chat endpoint")
async def chat(body: ChatRequest):
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt cannot be empty.")

    logger.info("POST /chat — classifying: %r", prompt[:80])
    intent_data = await _run_sync(classify_intent, prompt)
    intent      = intent_data.get("intent", "agent_run")
    logger.info("Intent: %s | %s", intent, intent_data)

    from tools.registry import TOOL_MAP

    # ── Guardrail ─────────────────────────────────────────────────────────────
    if intent == "out_of_scope":
        reason = intent_data.get("refusal_reason") or (
            "I'm GridMind, a VPP operations assistant. I can only help with "
            "fleet monitoring, diagnostics, and solar energy system management."
        )
        return {"type": "refusal", "message": reason}

    # ── Show anomalies ────────────────────────────────────────────────────────
    if intent == "show_anomalies":
        anomaly_type  = intent_data.get("anomaly_type")
        status_filter = intent_data.get("status_filter")
        STATUS_TO_ANOMALY = {"offline": "offline", "warning": "battery_drain", "degraded": None}
        if not anomaly_type and status_filter:
            anomaly_type = STATUS_TO_ANOMALY.get(status_filter)
        result = await _run_sync(TOOL_MAP["detect_anomalies"].invoke,
            {"anomaly_type": anomaly_type, "threshold_pct": None})
        total = result["total_anomalies"]
        if total == 0:
            label = anomaly_type.replace("_", " ") if anomaly_type else "anomalous"
            msg = f"No {label} systems found. Fleet is looking clean."
        else:
            label   = anomaly_type.replace("_", " ").title() if anomaly_type else "anomalous"
            systems = ", ".join(a["system_id"] for a in result["anomalies"][:5])
            extra   = f" +{total-5} more" if total > 5 else ""
            msg = f"Found {total} {label} system{'s' if total != 1 else ''}: {systems}{extra}"
        return {"type": "anomalies", "anomaly_type": anomaly_type, "data": result, "message": msg}

    # ── Show fleet status ─────────────────────────────────────────────────────
    if intent == "show_status":
        result = await _run_sync(TOOL_MAP["get_fleet_summary"].invoke, {})
        by_status = result.get("by_status", {})
        healthy   = by_status.get("healthy", 0)
        total     = result.get("total", 50)
        output    = result.get("total_output_kw", 0)
        attention = len(result.get("systems_needing_attention", []))
        msg = (f"Fleet is {round(healthy/total*100)}% healthy — {healthy}/{total} systems online, "
               f"{output} kW total output. {attention} system{'s' if attention != 1 else ''} need attention.")
        return {"type": "fleet_summary", "data": result, "message": msg}

    # ── Show specific system ──────────────────────────────────────────────────
    if intent == "show_system":
        import re
        system_id = intent_data.get("system_id")
        if not system_id:
            match = re.search(r"SYS_\d+", prompt.upper())
            system_id = match.group(0) if match else None
        if not system_id:
            return {"type": "error", "message": "Which system? Please include a system ID like SYS_042."}
        try:
            result  = await _run_sync(TOOL_MAP["get_system_status"].invoke, {"system_id": system_id})
            history = await _run_sync(TOOL_MAP["get_system_history"].invoke, {"system_id": system_id, "hours_back": 12})
            status  = result["status"].title()
            anomaly = f" · {result['anomaly_type'].replace('_',' ').title()}" if result.get("anomaly_type") else ""
            msg = f"{result['system_id']} in {result['location']} is **{status}**{anomaly}. Output: {result['solar_output_kw']} kW."
            return {"type": "system", "data": {**result, "history": history["readings"]}, "message": msg}
        except KeyError as e:
            return {"type": "error", "message": str(e)}

    # ── Show trends ───────────────────────────────────────────────────────────
    if intent == "show_trends":
        metric = intent_data.get("metric") or "solar_output_kw"
        result = await _run_sync(TOOL_MAP["get_fleet_trends"].invoke, {"hours_back": 24, "metric": metric})
        summary = result.get("summary", {})
        trend   = summary.get("overall_trend", "stable")
        peak    = summary.get("peak_value")
        label   = metric.replace("_", " ")
        msg = f"Fleet {label} trend over 24h is **{trend}**. Peak average was {peak}."
        return {"type": "trends", "metric": metric, "data": result, "message": msg}

    # ── Show escalations ──────────────────────────────────────────────────────
    if intent == "show_escalations":
        from data.fleet_store import load_escalations
        escalations  = await _run_sync(load_escalations)
        open_tickets = [e for e in escalations if e.get("status") == "open"]
        n = len(open_tickets)
        msg = f"{n} open escalation ticket{'s' if n != 1 else ''} require field inspection."
        return {"type": "escalations", "data": open_tickets, "message": msg}

    # ── Full agent run ────────────────────────────────────────────────────────
    from agent.runner import run_session as _run
    report = await _run_sync(_run, prompt)
    if "error" in report and not report.get("executive_summary"):
        return {"type": "error", "message": report["error"]}
    return {"type": "agent_report", "data": report}


# ── /run (direct, no routing) ─────────────────────────────────────────────────

@app.post("/run")
async def run_session(body: RunRequest):
    from agent.runner import run_session as _run
    report = await _run_sync(_run, body.prompt, body.session_id)
    if "error" in report and not report.get("executive_summary"):
        raise HTTPException(status_code=500, detail=report["error"])
    return report


# ── Fleet ─────────────────────────────────────────────────────────────────────

@app.get("/fleet")
async def get_fleet():
    from data.fleet_store import load_fleet
    return load_fleet(force=True)

@app.get("/fleet/summary")
async def get_fleet_summary(status_filter: Optional[str] = Query(default=None)):
    from tools.registry import TOOL_MAP
    try:
        return TOOL_MAP["get_fleet_summary"].invoke({"status_filter": status_filter})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/fleet/{system_id}")
async def get_system(system_id: str):
    from data.fleet_store import get_system as _get
    try:
        return _get(system_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.post("/fleet/{system_id}/resolve")
async def resolve_issue(system_id: str, body: ResolveRequest):
    from tools.registry import TOOL_MAP
    try:
        return await _run_sync(TOOL_MAP["resolve_issue"].invoke,
            {"system_id": system_id, "action": body.action, "notes": body.notes})
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/fleet/{system_id}/escalate")
async def escalate_issue(system_id: str, body: EscalateRequest):
    from tools.registry import TOOL_MAP
    try:
        return await _run_sync(TOOL_MAP["escalate_issue"].invoke,
            {"system_id": system_id, "reason": body.reason, "severity": body.severity})
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/anomalies")
async def detect_anomalies(anomaly_type: Optional[str] = Query(default=None),
                            threshold_pct: Optional[float] = Query(default=None)):
    from tools.registry import TOOL_MAP
    try:
        return TOOL_MAP["detect_anomalies"].invoke({"anomaly_type": anomaly_type, "threshold_pct": threshold_pct})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/trends")
async def get_fleet_trends(hours_back: int = Query(default=24, ge=1, le=24),
                            metric: str = Query(default="solar_output_kw")):
    from tools.registry import TOOL_MAP
    try:
        return TOOL_MAP["get_fleet_trends"].invoke({"hours_back": hours_back, "metric": metric})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/report")
async def generate_ops_report(sections: Optional[str] = Query(default=None)):
    from tools.registry import TOOL_MAP
    include = [s.strip() for s in sections.split(",")] if sections else None
    try:
        return await _run_sync(TOOL_MAP["generate_ops_report"].invoke, {"include_sections": include})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/escalations")
async def get_escalations():
    from data.fleet_store import load_escalations
    return load_escalations()

@app.get("/traces")
async def list_traces():
    import json as _json
    traces_dir = Path(__file__).parent.parent / "traces"
    if not traces_dir.exists():
        return []
    results = []
    for path in sorted(traces_dir.glob("session_*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            with open(path, encoding="utf-8") as f:
                t = _json.load(f)
            results.append({"session_id": t.get("session_id"), "started_at": t.get("started_at"),
                             "elapsed_seconds": t.get("elapsed_seconds"), "prompt": t.get("prompt"),
                             "outcome": t.get("outcome"), "health_after": t.get("fleet_after", {}).get("health_score_pct"),
                             "error": t.get("error")})
        except Exception as exc:
            logger.warning("Could not parse trace %s: %s", path.name, exc)
    return results

@app.get("/traces/{session_id}")
async def get_trace(session_id: str):
    from observability.tracer import load_trace
    try:
        return load_trace(session_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok", "service": "GridMind API"}