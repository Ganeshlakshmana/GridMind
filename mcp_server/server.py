"""
mcp_server/server.py

FastMCP server exposing all 10 GridMind tools over the MCP protocol.
Supports stdio (Claude Desktop) and SSE/HTTP (Claude Code, HTTP clients).

The same tools used by the LangGraph agent are served here — one
implementation, two consumption paths.

Usage:
    python -m mcp_server.server                   # stdio (Claude Desktop)
    python -m mcp_server.server --transport sse   # SSE on localhost:8000
    python -m mcp_server.server --transport http  # Streamable HTTP on localhost:8000

Claude Desktop config (%APPDATA%/Claude/claude_desktop_config.json):
    {
      "mcpServers": {
        "gridmind": {
          "command": "python",
          "args": ["-m", "mcp_server.server"],
          "cwd": "D:/GridMind"
        }
      }
    }
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

import fastmcp
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Import LangChain tools — used as the implementation layer
from tools.registry import TOOL_MAP  # noqa: E402


# ── Server factory ────────────────────────────────────────────────────────────

def build_server() -> fastmcp.FastMCP:
    """
    Create and return a configured FastMCP server with all 10 tools registered.
    Each tool is registered via @mcp.tool() with explicit typed signatures so
    FastMCP can generate correct MCP JSON schemas regardless of Python version.
    """
    mcp = fastmcp.FastMCP(
        name="GridMind",
        instructions=(
            "GridMind is a Virtual Power Plant (VPP) operations agent. "
            "Use these tools to monitor, diagnose, and resolve issues across "
            "a fleet of 50 solar energy systems in Berlin. "
            "Read tools: get_system_status, get_fleet_summary, detect_anomalies, "
            "get_system_history, compare_systems. "
            "Action tools: resolve_issue, escalate_issue, update_system_config. "
            "Analytics tools: get_fleet_trends, generate_ops_report."
        ),
    )

    # ── Read tools ────────────────────────────────────────────────────────────

    @mcp.tool(
        name="get_system_status",
        description=TOOL_MAP["get_system_status"].description,
    )
    def get_system_status(system_id: str) -> dict:
        return TOOL_MAP["get_system_status"].invoke({"system_id": system_id})

    @mcp.tool(
        name="get_fleet_summary",
        description=TOOL_MAP["get_fleet_summary"].description,
    )
    def get_fleet_summary(status_filter: Optional[str] = None) -> dict:
        return TOOL_MAP["get_fleet_summary"].invoke({"status_filter": status_filter})

    @mcp.tool(
        name="detect_anomalies",
        description=TOOL_MAP["detect_anomalies"].description,
    )
    def detect_anomalies(
        anomaly_type: Optional[str] = None,
        threshold_pct: Optional[float] = None,
    ) -> dict:
        return TOOL_MAP["detect_anomalies"].invoke({
            "anomaly_type":  anomaly_type,
            "threshold_pct": threshold_pct,
        })

    @mcp.tool(
        name="get_system_history",
        description=TOOL_MAP["get_system_history"].description,
    )
    def get_system_history(system_id: str, hours_back: int = 24) -> dict:
        return TOOL_MAP["get_system_history"].invoke({
            "system_id":  system_id,
            "hours_back": hours_back,
        })

    @mcp.tool(
        name="compare_systems",
        description=TOOL_MAP["compare_systems"].description,
    )
    def compare_systems(system_ids: list[str]) -> dict:
        return TOOL_MAP["compare_systems"].invoke({"system_ids": system_ids})

    # ── Action tools ──────────────────────────────────────────────────────────

    @mcp.tool(
        name="resolve_issue",
        description=TOOL_MAP["resolve_issue"].description,
    )
    def resolve_issue(
        system_id: str,
        action: str,
        notes: Optional[str] = "",
    ) -> dict:
        return TOOL_MAP["resolve_issue"].invoke({
            "system_id": system_id,
            "action":    action,
            "notes":     notes,
        })

    @mcp.tool(
        name="escalate_issue",
        description=TOOL_MAP["escalate_issue"].description,
    )
    def escalate_issue(system_id: str, reason: str, severity: str) -> dict:
        return TOOL_MAP["escalate_issue"].invoke({
            "system_id": system_id,
            "reason":    reason,
            "severity":  severity,
        })

    @mcp.tool(
        name="update_system_config",
        description=TOOL_MAP["update_system_config"].description,
    )
    def update_system_config(system_id: str, config_fields: dict) -> dict:
        return TOOL_MAP["update_system_config"].invoke({
            "system_id":    system_id,
            "config_fields": config_fields,
        })

    # ── Analytics tools ───────────────────────────────────────────────────────

    @mcp.tool(
        name="get_fleet_trends",
        description=TOOL_MAP["get_fleet_trends"].description,
    )
    def get_fleet_trends(
        hours_back: int = 24,
        metric: str = "solar_output_kw",
    ) -> dict:
        return TOOL_MAP["get_fleet_trends"].invoke({
            "hours_back": hours_back,
            "metric":     metric,
        })

    @mcp.tool(
        name="generate_ops_report",
        description=TOOL_MAP["generate_ops_report"].description,
    )
    def generate_ops_report(
        include_sections: Optional[list[str]] = None,
    ) -> dict:
        return TOOL_MAP["generate_ops_report"].invoke({
            "include_sections": include_sections,
        })

    logger.info("GridMind MCP server ready — 10 tools registered")

    return mcp


# ── Module-level server instance ──────────────────────────────────────────────

import asyncio  # noqa: E402
mcp = build_server()


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="GridMind MCP server.")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "http"],
        default="stdio",
        help="Transport protocol (default: stdio).",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    logger.info("Starting GridMind MCP server — transport=%s", args.transport)

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    elif args.transport == "sse":
        mcp.run(transport="sse", host=args.host, port=args.port)
    elif args.transport == "http":
        mcp.run(transport="streamable-http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()