"""
agent/nodes.py

Seven node functions for the GridMind LangGraph agent.
Each function takes VPPState, does exactly one job, and returns
a partial state dict with only the fields it owns.

Node ownership:
    monitor_node  → fleet_summary
    detect_node   → anomalies
    triage_node   → triage_plan, messages
    action_node   → actions_taken
    verify_node   → verification
    report_node   → report
    router        → returns next node name (str), never mutates state

LLM calls only happen in triage_node — all other nodes are deterministic.
This keeps costs low and makes the graph easy to test without API keys.
"""

import json
import logging
import os
from typing import Literal

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent.state import VPPState
from tools.registry import TOOL_MAP

logger = logging.getLogger(__name__)

# ── Model ─────────────────────────────────────────────────────────────────────

def _get_triage_model() -> ChatAnthropic:
    """
    Plain model for triage_node — NO tools bound.
    Triage only needs to reason and return JSON; binding tools causes
    the model to emit tool_use blocks instead of a text response.
    """
    return ChatAnthropic(
        model="claude-opus-4-5",
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
        max_tokens=4096,
    )


_TRIAGE_SYSTEM_PROMPT = """\
You are GridMind, an autonomous VPP (Virtual Power Plant) operations agent.
You have already scanned the fleet and detected anomalies.
Your job now is to produce a triage plan: decide for each anomalous system
whether to resolve it automatically, escalate it for human intervention,
or monitor it without immediate action.

You must respond ONLY with a valid JSON object — no prose, no markdown fences.

Schema:
{
  "to_resolve": [
    {"system_id": "SYS_XXX", "action": "<valid_action>", "notes": "<brief reason>"}
  ],
  "to_escalate": [
    {"system_id": "SYS_XXX", "reason": "<why human needed>", "severity": "low|medium|high|critical"}
  ],
  "to_monitor": ["SYS_XXX"],
  "rationale": "<1–2 sentence summary of your overall triage logic>"
}

Valid actions:
  restart_inverter          — for inverter_fault systems
  reset_battery_management  — for battery_drain systems
  clear_low_output_flag     — for low_output systems
  force_reconnect           — for offline systems (escalate if it fails)

Severity guide:
  critical — system poses grid stability risk or SOC < 10%
  high     — offline > 30 min or zero output during peak hours
  medium   — degraded output, non-critical
  low      — informational, no immediate risk

Be decisive. Do not put a system in both to_resolve and to_escalate.
Prefer automated resolution unless the anomaly suggests physical damage
or the system has been offline long enough that reconnect is unlikely to succeed.
"""


# ── 1. monitor_node ───────────────────────────────────────────────────────────

def monitor_node(state: VPPState) -> dict:
    """
    Call get_fleet_summary and write the result to state.
    Entry point for every agent session.
    """
    logger.info("[monitor] Fetching fleet summary")
    try:
        summary = TOOL_MAP["get_fleet_summary"].invoke({})
        logger.info(
            "[monitor] Fleet: %d systems, %d needing attention",
            summary["total"],
            len(summary["systems_needing_attention"]),
        )
        return {"fleet_summary": summary}
    except Exception as exc:
        logger.error("[monitor] Failed: %s", exc)
        return {"error": f"monitor_node failed: {exc}"}


# ── 2. detect_node ────────────────────────────────────────────────────────────

def detect_node(state: VPPState) -> dict:
    """
    Call detect_anomalies and write the result to state.
    Runs after monitor_node regardless of fleet health.
    """
    logger.info("[detect] Running anomaly detection")
    try:
        anomalies = TOOL_MAP["detect_anomalies"].invoke({})
        logger.info("[detect] Found %d anomalous systems", anomalies["total_anomalies"])
        return {"anomalies": anomalies}
    except Exception as exc:
        logger.error("[detect] Failed: %s", exc)
        return {"error": f"detect_node failed: {exc}"}


# ── 3. triage_node ────────────────────────────────────────────────────────────

def triage_node(state: VPPState) -> dict:
    """
    Use the LLM to produce a triage plan from the detected anomalies.
    The only node that makes an LLM call.

    If there are no anomalies, skips the LLM and returns an empty plan
    so the router can fast-path to report_node.
    """
    anomalies = state.get("anomalies", {})
    anomaly_list = anomalies.get("anomalies", [])

    # Fast path — nothing to triage
    if not anomaly_list:
        logger.info("[triage] No anomalies — skipping LLM call")
        return {
            "triage_plan": {
                "to_resolve":  [],
                "to_escalate": [],
                "to_monitor":  [],
                "rationale":   "Fleet is healthy. No triage required.",
            }
        }

    logger.info("[triage] Triaging %d anomalies via LLM", len(anomaly_list))

    # Build a compact anomaly summary for the prompt — avoids sending full history
    # and queries the vector store for similar past incidents
    from db.vector_store import get_vector_store
    store = get_vector_store()

    compact = []
    for a in anomaly_list:
        query = f"anomaly_type={a['anomaly_type']} status={a['status']} alerts={', '.join(a['alerts'])}"
        similar = store.search(query, k=1)
        past_case = "No matching past case found."
        if similar:
            past_case = f"Action: {similar[0]['action']} (Result: {similar[0]['result']}). Case study: {similar[0]['text']}"

        compact.append({
            "system_id":             a["system_id"],
            "location":              a["location"],
            "anomaly_type":          a["anomaly_type"],
            "status":                a["status"],
            "solar_output_kw":       a["solar_output_kw"],
            "expected_output_kw":    a["expected_output_kw"],
            "battery_soc_pct":       a["battery_soc_pct"],
            "last_updated":          a["last_updated"],
            "alerts":                a["alerts"],
            "similar_past_incident": past_case,
        })

    user_content = (
        f"Operator request: {state.get('prompt', 'Run full diagnostic.')}\n\n"
        f"Fleet summary:\n{json.dumps(state.get('fleet_summary', {}), indent=2)}\n\n"
        f"Anomalous systems ({len(compact)}):\n{json.dumps(compact, indent=2)}\n\n"
        "Produce a triage plan."
    )

    messages = state.get("messages", [])
    new_messages = messages + [
        SystemMessage(content=_TRIAGE_SYSTEM_PROMPT),
        HumanMessage(content=user_content),
    ]

    try:
        model    = _get_triage_model()
        response = model.invoke(new_messages)
        raw = response.content

        # Claude returns a list of content blocks when tools are bound.
        # Extract text from the first text block.
        if isinstance(raw, list):
            text_blocks = [b.text for b in raw if hasattr(b, "text")]
            if not text_blocks:
                raise ValueError("LLM returned no text content in response blocks.")
            raw = text_blocks[0]

        if not isinstance(raw, str):
            raise ValueError(f"Unexpected response type: {type(raw)}")

        # Strip markdown fences if the model wraps JSON despite instructions
        clean = raw.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        triage_plan = json.loads(clean.strip())

        logger.info(
            "[triage] Plan: resolve=%d, escalate=%d, monitor=%d",
            len(triage_plan.get("to_resolve", [])),
            len(triage_plan.get("to_escalate", [])),
            len(triage_plan.get("to_monitor", [])),
        )

        return {
            "triage_plan": triage_plan,
            "messages":    new_messages + [AIMessage(content=raw)],
        }

    except Exception as exc:
        logger.error("[triage] LLM call failed: %s", exc)
        # Fallback: escalate everything rather than doing nothing
        fallback_plan = {
            "to_resolve":  [],
            "to_escalate": [
                {
                    "system_id": a["system_id"],
                    "reason":    f"Triage LLM failed ({exc}). Manual review required.",
                    "severity":  "medium",
                }
                for a in anomaly_list
            ],
            "to_monitor":  [],
            "rationale":   f"LLM triage failed: {exc}. All anomalies escalated for safety.",
        }
        return {"triage_plan": fallback_plan}


# ── 4. action_node ────────────────────────────────────────────────────────────

def action_node(state: VPPState) -> dict:
    """
    Execute the triage plan — call resolve_issue and escalate_issue
    for every system in to_resolve and to_escalate respectively.

    Continues through all actions even if one fails — partial progress
    is better than all-or-nothing when managing a real fleet.
    """
    plan    = state.get("triage_plan", {})
    results = []

    for item in plan.get("to_resolve", []):
        sid    = item["system_id"]
        action = item["action"]
        notes  = item.get("notes", "")
        logger.info("[action] resolve_issue: %s via %s", sid, action)
        try:
            result = TOOL_MAP["resolve_issue"].invoke({
                "system_id": sid,
                "action":    action,
                "notes":     notes,
            })
            results.append({"type": "resolve", **result})
        except Exception as exc:
            logger.error("[action] resolve_issue failed for %s: %s", sid, exc)
            results.append({
                "type":      "resolve",
                "system_id": sid,
                "action":    action,
                "success":   False,
                "error":     str(exc),
            })

    for item in plan.get("to_escalate", []):
        sid      = item["system_id"]
        reason   = item["reason"]
        severity = item.get("severity", "medium")
        logger.info("[action] escalate_issue: %s (%s)", sid, severity)
        try:
            ticket = TOOL_MAP["escalate_issue"].invoke({
                "system_id": sid,
                "reason":    reason,
                "severity":  severity,
            })
            results.append({"type": "escalate", **ticket})
        except Exception as exc:
            logger.error("[action] escalate_issue failed for %s: %s", sid, exc)
            results.append({
                "type":      "escalate",
                "system_id": sid,
                "success":   False,
                "error":     str(exc),
            })

    logger.info("[action] Completed %d actions", len(results))
    return {"actions_taken": results}


# ── 5. verify_node ────────────────────────────────────────────────────────────

def verify_node(state: VPPState) -> dict:
    """
    For every system that was resolved (not escalated), call get_system_status
    to confirm the fix landed correctly in fleet_store.

    Records whether the post-fix status matches the expected outcome.
    """
    actions   = state.get("actions_taken", [])
    plan      = state.get("triage_plan", {})
    resolved  = {
        item["system_id"]: item["action"]
        for item in plan.get("to_resolve", [])
    }

    verification = []
    for action_result in actions:
        sid = action_result.get("system_id")
        if sid not in resolved:
            continue   # skip escalations — nothing to verify

        logger.info("[verify] Checking %s post-fix", sid)
        try:
            current = TOOL_MAP["get_system_status"].invoke({"system_id": sid})
            fix_succeeded = current["status"] == "healthy"
            verification.append({
                "system_id":      sid,
                "action":         resolved[sid],
                "fix_succeeded":  fix_succeeded,
                "current_status": current["status"],
                "current_anomaly": current["anomaly_type"],
            })
            logger.info(
                "[verify] %s → status=%s fix_succeeded=%s",
                sid, current["status"], fix_succeeded,
            )
        except Exception as exc:
            logger.error("[verify] get_system_status failed for %s: %s", sid, exc)
            verification.append({
                "system_id":     sid,
                "action":        resolved[sid],
                "fix_succeeded": False,
                "error":         str(exc),
            })

    return {"verification": verification}


# ── 6. report_node ────────────────────────────────────────────────────────────

def report_node(state: VPPState) -> dict:
    """
    Generate the final structured ops report and attach session metadata.
    Always runs — even when an error occurred in an earlier node.
    """
    logger.info("[report] Generating final ops report")
    try:
        report = TOOL_MAP["generate_ops_report"].invoke({})
    except Exception as exc:
        logger.error("[report] generate_ops_report failed: %s", exc)
        report = {"error": str(exc)}

    # Attach session context so the API and dashboard can render it fully
    report["session"] = {
        "session_id":    state.get("session_id"),
        "prompt":        state.get("prompt"),
        "triage_plan":   state.get("triage_plan"),
        "actions_taken": state.get("actions_taken", []),
        "verification":  state.get("verification", []),
        "error":         state.get("error"),
    }

    return {"report": report}


# ── 7. router ─────────────────────────────────────────────────────────────────

def router(state: VPPState) -> Literal[
    "detect_node",
    "triage_node",
    "action_node",
    "verify_node",
    "report_node",
]:
    """
    Pure routing function — reads state, returns the next node name.
    Never mutates state. Called by LangGraph as a conditional edge.

    Routing logic:
        error at any point           → report_node  (fail-safe)
        after monitor                → detect_node
        after detect, no anomalies   → report_node  (fast path)
        after detect, has anomalies  → triage_node
        after triage, has actions    → action_node
        after triage, no actions     → report_node
        after action                 → verify_node
        after verify                 → report_node
    """
    if state.get("error"):
        return "report_node"

    if state.get("verification") is not None:
        return "report_node"

    if state.get("actions_taken") is not None:
        return "verify_node"

    if state.get("triage_plan") is not None:
        plan = state["triage_plan"]
        has_actions = (
            len(plan.get("to_resolve",  [])) > 0 or
            len(plan.get("to_escalate", [])) > 0
        )
        return "action_node" if has_actions else "report_node"

    if state.get("anomalies") is not None:
        total = state["anomalies"].get("total_anomalies", 0)
        return "triage_node" if total > 0 else "report_node"

    if state.get("fleet_summary") is not None:
        return "detect_node"

    return "report_node"