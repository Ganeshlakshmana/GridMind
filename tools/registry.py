"""
registry.py

Single source of truth for all GridMind tools.

Import ALL_TOOLS from here — never import tools directly from their modules
in agent, mcp_server, or evals. This ensures a single registration point:
adding a new tool means updating one list in one file.

Usage:
    from tools.registry import ALL_TOOLS

    # LangGraph agent
    model = ChatAnthropic(...).bind_tools(ALL_TOOLS)

    # MCP server
    for tool in ALL_TOOLS:
        mcp.add_tool(tool)

    # Eval harness
    available = {t.name: t for t in ALL_TOOLS}
"""

from tools.action_tools import escalate_issue, resolve_issue, update_system_config
from tools.analytics_tools import generate_ops_report, get_fleet_trends
from db.vector_store import search_similar_incidents
from tools.fleet_tools import (
    compare_systems,
    detect_anomalies,
    get_fleet_summary,
    get_system_history,
    get_system_status,
    get_systems_by_zone,
)

ALL_TOOLS: list = [
    # ── Read tools ─────────────────────────────────────────────────────────
    get_system_status,       # single system full state
    get_fleet_summary,       # aggregate counts + systems needing attention
    detect_anomalies,        # find systems outside normal parameters
    get_system_history,      # last N hours of readings for one system
    compare_systems,         # side-by-side metric comparison
    get_systems_by_zone,     # retrieve systems inside a grid zone
    search_similar_incidents, # search similar past VPP incidents
    # ── Action tools ───────────────────────────────────────────────────────
    resolve_issue,           # apply a remediation action
    escalate_issue,          # raise a human-intervention ticket
    update_system_config,    # update physical/config fields post field-work
    # ── Analytics tools ────────────────────────────────────────────────────
    get_fleet_trends,        # hour-by-hour metric aggregation across fleet
    generate_ops_report,     # structured operational report with all sections
]

# Convenience lookup — used by eval harness to validate tool call sequences
TOOL_MAP: dict = {t.name: t for t in ALL_TOOLS}