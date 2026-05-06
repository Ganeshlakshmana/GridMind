# GridMind

**Autonomous VPP Operations Agent** — monitors, diagnoses, and resolves faults across a fleet of solar energy systems using a LangGraph agent, 10 production tools, and a React dashboard.

---

## What It Does

GridMind continuously watches a fleet of 50 solar energy systems. When it detects an anomaly — inverter fault, battery drain, offline system, low output — it triages the issue, applies the right remediation automatically, verifies the fix, and escalates to a human only when necessary. The entire cycle runs in under 30 seconds.

```
Operator prompt
      │
      ▼
Intent Router ──► out of scope? → refused immediately
      │
      ▼
LangGraph Agent
  monitor_node   → get_fleet_summary()
  detect_node    → detect_anomalies()
  triage_node    → LLM decides: fix / escalate / monitor
  action_node    → resolve_issue() or escalate_issue()
  verify_node    → get_system_status() confirms fix landed
  report_node    → generate_ops_report()
      │
      ▼
Structured report + trace written to disk
```

---

## Project Structure

```
gridmind/
├── data/
│   ├── generate_fleet.py        # Task 1  — generates 50 systems with anomaly distribution
│   ├── generate_history.py      # Task 2  — 24h hourly telemetry per system
│   ├── fleet_store.py           # Task 3  — atomic read/write, in-memory cache
│   ├── fleet.json               # generated — do not commit
│   └── escalations.json         # generated — do not commit
│
├── tools/
│   ├── fleet_tools.py           # 5 read tools
│   ├── action_tools.py          # 3 write tools
│   ├── analytics_tools.py       # 2 analytics tools
│   └── registry.py              # ALL_TOOLS list — single import point
│
├── agent/
│   ├── state.py                 # VPPState TypedDict
│   ├── nodes.py                 # 7 node functions
│   ├── graph.py                 # compiled LangGraph StateGraph
│   └── runner.py                # run_session() entrypoint + CLI
│
├── observability/
│   ├── tracer.py                # writes traces/session_<id>.json after every run
│   └── session_dashboard.py     # CLI summary of any session trace
│
├── mcp_server/
│   └── server.py                # FastMCP — all 10 tools over MCP protocol
│
├── api/
│   └── main.py                  # FastAPI — 12 endpoints, intent router, guardrails
│
├── frontend/
│   ├── App.jsx                  # React dashboard
│   ├── index.html
│   ├── vite.config.js
│   └── src/main.jsx
│
├── evals/
│   ├── scenarios.py             # 15 eval scenarios
│   ├── runner.py                # runs all scenarios, scores, writes results
│   └── results/                 # timestamped JSON results per run
│
├── traces/                      # runtime session traces — do not commit
├── .env                         # API keys — do not commit
├── requirements.txt
└── README.md
```

---

## Quickstart

### 1. Install dependencies

```bash
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

### 2. Set API key

```bash
# .env
ANTHROPIC_API_KEY=sk-ant-...
```

### 3. Generate fleet data

```bash
python -m data.generate_fleet --seed 42
python -m data.generate_history --seed 42
```

### 4. Run the agent

```bash
python -m agent.runner "Run a full fleet diagnostic and fix what you can."
```

### 5. View session dashboard

```bash
python -m observability.session_dashboard
```

### 6. Start the API

```bash
uvicorn api.main:app --reload --port 8080
```

### 7. Start the frontend

```bash
cd frontend
npm install vite @vitejs/plugin-react react react-dom recharts
npm run dev
```

Open `http://localhost:3000`

---

## Tools

| Tool | Type | Description |
|---|---|---|
| `get_system_status` | read | Full state of one system |
| `get_fleet_summary` | read | Aggregate counts, output, attention list |
| `detect_anomalies` | read | Systems outside normal parameters |
| `get_system_history` | read | Last N hours of readings |
| `compare_systems` | read | Side-by-side metric comparison |
| `resolve_issue` | action | Apply restart / reset / reconnect / clear |
| `escalate_issue` | action | Raise human-intervention ticket |
| `update_system_config` | action | Update physical config post field-work |
| `get_fleet_trends` | analytics | Hour-by-hour metric aggregation |
| `generate_ops_report` | analytics | Structured ops report, all sections |

---

## Agent Actions

| Anomaly | Auto Action |
|---|---|
| `inverter_fault` | `restart_inverter` |
| `battery_drain` | `reset_battery_management` |
| `low_output` | `clear_low_output_flag` |
| `offline` | `force_reconnect` → escalate if fails |

---

## API Endpoints

```
POST /chat                         # intent-routed chat (use from UI)
POST /run                          # direct full agent session
GET  /fleet                        # all 50 systems
GET  /fleet/summary                # aggregate summary
GET  /fleet/{system_id}            # single system
POST /fleet/{system_id}/resolve    # resolve an issue
POST /fleet/{system_id}/escalate   # raise escalation ticket
GET  /anomalies                    # detect anomalous systems
GET  /trends                       # fleet metric trends
GET  /report                       # full ops report
GET  /escalations                  # open tickets
GET  /traces                       # list session traces
GET  /traces/{session_id}          # single trace
```

Interactive docs at `http://localhost:8080/docs`

---

## MCP Server

Exposes all 10 tools over the MCP protocol for Claude Desktop and Claude Code.

```bash
# stdio (Claude Desktop)
python -m mcp_server.server

# SSE / HTTP
python -m mcp_server.server --transport sse --port 8000
```

**Claude Desktop config** (`%APPDATA%/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "gridmind": {
      "command": "python",
      "args": ["-m", "mcp_server.server"],
      "cwd": "D:/GridMind"
    }
  }
}
```

---

## Evals

```bash
python -m evals.runner --list          # list all 15 scenarios
python -m evals.runner --scenario S02  # run one scenario
python -m evals.runner                 # run full suite
```

**Current pass rate: 15/15 (100%)**

| Range | What's tested |
|---|---|
| S01–S09 | Full agent — triage, actions, verification |
| S10–S11 | Guardrails — out-of-scope prompts refused |
| S12–S14 | Intent routing — direct queries bypass agent |
| S15 | Prompt injection refused |

Results written to `evals/results/run_<timestamp>.json`

---

## Guardrails

Every `/chat` request is classified by a fast Haiku call before any tool runs:

| Intent | Action |
|---|---|
| `agent_run` | Full LangGraph session |
| `show_status` | `get_fleet_summary()` direct |
| `show_anomalies` | `detect_anomalies()` direct |
| `show_system` | `get_system_status()` direct |
| `show_trends` | `get_fleet_trends()` direct |
| `show_escalations` | `load_escalations()` direct |
| `out_of_scope` | Refused — no tools called |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Agent | LangGraph, LangChain, Claude claude-opus-4-5 |
| Intent classifier | Claude Haiku (fast, cheap) |
| API | FastAPI, Uvicorn |
| MCP server | FastMCP |
| Frontend | React, Vite, Recharts |
| Data | Python, Pandas, Faker |
| Evals | Custom harness, 15 scenarios |

---

## Environment Variables

```bash
ANTHROPIC_API_KEY=sk-ant-...     # required
LANGSMITH_API_KEY=...            # optional — LangSmith tracing
```

---

## Resetting the Fleet

```bash
# Full reset to clean state (seed 42)
python -m data.generate_fleet --seed 42
python -m data.generate_history --seed 42

# Custom seed for reproducible testing
python -m data.generate_fleet --seed 99
python -m data.generate_history --seed 99
```

---

## License

MIT