# GridMind

**Autonomous Virtual Power Plant (VPP) Operations Agent** — monitors, diagnoses, and resolves faults across a fleet of 50 solar energy systems using a LangGraph agent, a PyTorch machine learning classifier, a PostgreSQL relational layer, a FAISS vector store, a DuckDB time-series layer (BigQuery mock), dbt transformations, Airflow orchestration, and a React dashboard.

---

## ⚡ What It Does

GridMind continuously monitors a fleet of 50 distributed solar energy systems. When it detects an anomaly (inverter fault, battery drain, offline system, low output) via its **PyTorch classifier model**, the agent:
1. **Triages the anomaly** using a **LangGraph StateGraph** and retrieves historical incident context from a **FAISS vector store**.
2. **Applies automated remediation** (BMS reset, inverter restart, reconnection attempt, or flag clearing).
3. **Verifies the fix** by checking the system's post-remediation status.
4. **Escalates to a human operator** (via relational tickets) only if the fix fails or if the anomaly requires manual intervention.
5. **Ingests and transforms telemetry** continuously using **dbt** and **DuckDB** to generate real-time metrics and historical trends.

```
       Operator prompt / Pipeline Cron
                     │
                     ▼
       Intent Router ──► out of scope? → refused immediately
                     │
                     ▼
              LangGraph Agent
    ┌─────────────────────────────────┐
    │  monitor_node → get_fleet_summary()
    │  detect_node  → detect_anomalies() [PyTorch classifier model]
    │  triage_node  → LLM + search_similar_incidents() [FAISS index]
    │  action_node  → resolve_issue() or escalate_issue() [PostgreSQL]
    │  verify_node  → get_system_status() confirms fix landed
    │  report_node  → generate_ops_report()
    └─────────────────────────────────┘
                     │
                     ▼
     Structured report + trace written to disk
```

---

## 📂 Project Structure

```
gridmind/
├── data/
│   ├── generate_fleet.py        # Generates 50 systems with Berlin district coordinates
│   ├── generate_history.py      # Generates 24h hourly telemetry per system
│   ├── fleet_store.py           # Atomic PostgreSQL read/write with graceful JSON fallback
│   ├── fleet.json               # Local fallback JSON database file
│   └── escalations.json         # Local fallback escalations file
│
├── tools/
│   ├── fleet_tools.py           # VPP monitoring & telemetry tools (including get_systems_by_zone)
│   ├── action_tools.py          # Deterministic remediation and escalation tools
│   ├── analytics_tools.py       # SQL-based analytics over DuckDB/BigQuery
│   ├── geo.py                   # Geospatial utilities (Haversine, zoning, nearest-neighbor)
│   └── registry.py              # Core tool definitions and single registration import point
│
├── db/
│   ├── models.py                # SQLAlchemy declarative models (Postgres schema)
│   ├── session.py               # SQL engine and session context with cached offline check
│   ├── vector_store.py          # FAISS indexing with pure-Python local TF-IDF fallback
│   └── bigquery_client.py       # DuckDB-backed Google BigQuery mock client
│
├── ml/
│   ├── anomaly_model.py         # PyTorch MLP classification neural network architecture
│   ├── train.py                 # PyTorch CPU training script (~2-3s runtime)
│   ├── infer.py                 # Predictor wrapper calling the saved weights
│   └── anomaly_model.pt         # Saved PyTorch model weights
│
├── dbt_project/
│   ├── dbt_project.yml          # dbt project configurations
│   ├── profiles.yml             # dbt profile connecting to the local DuckDB database
│   └── models/                  # SQL transformations (staging and KPI marts)
│       ├── staging/stg_telemetry.sql
│       └── marts/fleet_health.sql & anomaly_summary.sql
│
├── airflow/
│   ├── dags/
│   │   └── gridmind_pipeline.py # Airflow DAG defining telemetry sync, dbt run, and agent session
│   └── run_pipeline.py          # Sequential DAG simulator script
│
├── agent/
│   ├── state.py                 # LangGraph VPPState definition
│   ├── nodes.py                 # Graph nodes injecting FAISS incidents context
│   ├── graph.py                 # Compiled StateGraph routing
│   └── runner.py                # Command-line entrypoint & CLI
│
├── API/
│   └── main.py                  # FastAPI server orchestrating 12 endpoints & intent routing
│
├── frontend/                    # Vite-React frontend monitoring dashboard
├── tests/                       # Unit tests (database, geo, ML, vector store, dbt)
├── evals/                       # Automated scenario evaluation suite (15 scenarios)
├── traces/                      # Trace directories tracking agent steps
├── requirements.txt             # Python packages
└── README.md
```

---

## ⚙️ Installation & Setup

### 1. Initialize Virtual Environment & Install Dependencies

```bash
python -m venv venv
venv\Scripts\activate          # Windows
source venv/bin/activate        # macOS/Linux
pip install -r requirements.txt
```

### 2. Configure Environment

Create a `.env` file in the root directory:

```bash
ANTHROPIC_API_KEY=sk-ant-...     # Required for agent decision-making
DATABASE_URL=postgresql://postgres:password@localhost:5432/gridmind  # Optional (falls back to local JSON files)
```

### 3. Generate Telemetry & Ingest into DuckDB

Generates fleet structures, creates historical telemetry files, and syncs them to the DuckDB analytics database:

```bash
python -m data.generate_fleet --seed 42
python -m data.generate_history --seed 42
```

### 4. Train the PyTorch Anomaly Classifier

Train the MLP neural network on local telemetry to detect anomalies. The model compiles instantly on CPU:

```bash
python -m ml.train
```

### 5. Compile dbt Transformation Models

Ensure the dbt project compiles correctly and runs the transformations on your DuckDB telemetry:

```bash
dbt compile --project-dir dbt_project --profiles-dir dbt_project
dbt run --project-dir dbt_project --profiles-dir dbt_project
```

---

## 🚀 Running the System

### Run the Airflow Pipeline Simulator
Simulate the end-to-end VPP operations pipeline. This runs telemetry generation, BigQuery ingestion, dbt models, LangGraph agent triage, and escalation alerts in sequence:

```bash
# Set OMP bypass to avoid FAISS/PyTorch conflict on Windows
$env:KMP_DUPLICATE_LIB_OK="TRUE"  # PowerShell
python -m airflow.run_pipeline
```

### Run the Agent via CLI
Directly run the LangGraph VPP agent to diagnose the fleet and resolve issues:

```bash
python -m agent.runner "Run a full fleet diagnostic and fix what you can."
```

### Start the FastAPI Backend

```bash
uvicorn api.main:app --reload --port 8080
```
Interactive documentation is available at `http://localhost:8080/docs`.

### Start the React Dashboard Frontend

```bash
cd frontend
npm install
npm run dev
```
Open `http://localhost:3000` to view the UI dashboard.

---

## 🧪 Testing & Evals

### Run Unit Tests
GridMind features an isolated unit test suite covering geo utilities, database CRUD, ML models, vector store lookups, and dbt project compilation:

```bash
$env:KMP_DUPLICATE_LIB_OK="TRUE"
python -m unittest discover -s tests
```

### Run Eval Suite
Run the 15 agent evaluation scenarios. This verifies correct remediation, guardrail refusals, and proper intent routing:

```bash
python -m evals.runner
```
**Current pass rate: 15/15 (100% success)**

---

## 🛠️ Integrated Tools

| Tool | Source | Description |
|---|---|---|
| `get_system_status` | `tools/fleet_tools.py` | Fetches the full current state of a single system |
| `get_fleet_summary` | `tools/fleet_tools.py` | Retrieves overall metrics (total capacity, output, attention checklist) |
| `get_systems_by_zone` | `tools/fleet_tools.py` | Retrieves all solar systems located in a specific grid zone |
| `detect_anomalies` | `tools/fleet_tools.py` | Evaluates telemetry using the PyTorch MLP classifier model |
| `get_system_history` | `tools/fleet_tools.py` | Fetches the last N hours of time-series readings from DuckDB |
| `search_similar_incidents` | `db/vector_store.py` | Queries a FAISS index of historical escalations to guide current triage |
| `resolve_issue` | `tools/action_tools.py` | Executes BMS resets, inverter restarts, and other auto-remediations |
| `escalate_issue` | `tools/action_tools.py` | Logs escalation tickets inside PostgreSQL or JSON database layers |
| `get_fleet_trends` | `tools/analytics_tools.py` | Queries DuckDB using SQL to aggregate fleet metrics |
| `generate_ops_report` | `tools/analytics_tools.py` | Assembles a high-level operational diagnostics markdown report |

---

## 🛡️ Guardrails & Resilience

- **Out of Scope Protection**: Every chat request goes through an intent classifier (Fast API router) powered by Claude Haiku to bypass the agent and query data structures directly, or block prompts unrelated to VPP operations.
- **Relational Fallback**: If a PostgreSQL instance is offline or unreachable, SQLAlchemy functions catch connection errors, log a warning, and fall back to local JSON flat-files (`fleet.json` and `escalations.json`) without interrupting operational flows.
- **Vector Search Fallback**: If API keys are missing or offline, the FAISS vector store utilizes a custom local TF-IDF text encoder to continue providing context lookup capabilities.

---

## 📝 License

MIT