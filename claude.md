# GridMind VPP — Build Instructions for Claude Code

I'm building a Virtual Power Plant (VPP) autonomous operations platform that monitors, diagnoses,
and auto-remediates faults across 50 solar assets in Berlin. This document tells you exactly what
to build, in what order, and how each piece connects. Follow it top to bottom. Don't skip ahead.

---

## How the system fits together

```
[Telemetry Simulation] → [DuckDB / dbt] → [LangGraph Agent]
                                                  ↓
                          [FastAPI + React] ← [Postgres / JSON]
                          (intent router)    (tickets, actions)
```

The agent is the brain. FastAPI is the interface. DuckDB+dbt is the data pipeline.
Postgres stores state. Everything else feeds into or out of those four things.

---

## Task 1 — Geospatial utilities and fleet generation

**File to create: `tools/geo.py`**

I need five Berlin district zones (center, north, south, east, west), each with a lat/lon centroid.
Build these four functions:

- `haversine_distance(lat1, lon1, lat2, lon2)` — returns distance in km
- `get_grid_zone(lat, lon)` — returns the name of the closest zone centroid
- `grid_zone_clustering(systems)` — groups a list of asset dicts by their zone
- `nearest_neighbor_lookup(target_lat, target_lon, systems, k)` — returns the k closest assets sorted by distance

**File to modify: `data/generate_fleet.py`**

When generating each asset, jitter its `latitude` and `longitude` slightly around its district centroid
(±0.02 degrees is fine). Each asset must have both fields in its dict.

**Files to modify: `tools/fleet_tools.py` and `tools/registry.py`**

Register a tool called `get_systems_by_zone(zone_id: str)` that returns all assets in a given zone.
Wire it into the registry so the agent can call it.

---

## Task 2 — Postgres schema and resilient fallback

**File to create: `db/models.py`**

Four SQLAlchemy models:

- `System` — `system_id` (PK), `location`, `latitude`, `longitude`, `solar_capacity_kw`,
  `solar_output_kw`, `expected_output_kw`, `battery_soc_pct`, `status`, `anomaly_type`, `history` (JSON column)
- `Anomaly` — `id` (PK, autoincrement), `system_id` (FK → System), `anomaly_type`, `detected_at`, `status`
- `Action` — `id` (PK), `system_id` (FK → System), `action_type`, `notes`, `timestamp`, `success` (Boolean)
- `Escalation` — `ticket_id` (PK), `system_id` (FK → System), `reason`, `severity`, `created_at`, `status` (default `"open"`)

**File to create: `db/session.py`**

Set up SQLAlchemy engine + scoped session. Add `is_db_available() -> bool` that tests the connection.
Important: cache the result so it doesn't re-check on every agent step (TCP timeouts add up fast).

**File to modify: `data/fleet_store.py`**

Wrap `load_fleet` and `save_fleet` with a check against `is_db_available()`. If Postgres is up, use it.
If it's down, fall back silently to `data/fleet.json` and `data/escalations.json`. No errors, no noise —
just silent fallback.

---

## Task 3 — FAISS vector store for RAG

**File to create: `db/vector_store.py`**

Use `langchain_community.vectorstores` or raw `faiss` to build a vector index of past incidents.
Seed it with at least these cases:
- inverter fault → resolved by restart
- battery drain → resolved by BMS reset
- low output → resolved by panel cleaning schedule

**Fallback:** If no API key is present (OpenAI or Anthropic), don't crash. Instead, implement a
`CustomVectorEncoder` using TF-IDF or character-frequency embeddings with NumPy cosine similarity.
The agent should never know the difference.

Expose this as a registered tool:
```python
@tool
def search_similar_incidents(query_text: str) -> dict:
    ...
```

**File to modify: `agent/nodes.py`**

In `triage_node`, call `search_similar_incidents` for each active anomaly and inject the results
into the prompt as historical precedents before the agent decides what to do.

---

## Task 4 — PyTorch anomaly classifier

**File to create: `ml/anomaly_model.py`**

MLP classifier:
- Input: 4 features — `solar_output_kw`, `expected_output_kw`, `battery_soc_pct`, `has_battery`
- Output: 5 classes — `healthy`, `low_output`, `offline`, `battery_drain`, `inverter_fault`
- Architecture: `Linear(4,16) → ReLU → Linear(16,8) → ReLU → Linear(8,5)`

**File to create: `ml/train.py`**

Pull features and labels from asset history. Train on CPU for 100 epochs using `CrossEntropyLoss`
and `Adam`. Save weights to `ml/anomaly_model.pt`.

**File to create: `ml/infer.py`**

Expose `predict_anomaly(system_dict: dict) -> str | None`. If `anomaly_model.pt` doesn't exist,
call `train_model()` automatically before running inference. Never require the user to manually train first.

**File to modify: `tools/fleet_tools.py`**

Replace whatever anomaly detection logic exists in `detect_anomalies` with a call to `predict_anomaly`
as the primary path.

---

## Task 5 — DuckDB BigQuery mock layer

**File to create: `db/bigquery_client.py`**

Build a `BigQueryClient` backed by DuckDB at `data/gridmind_bq.db`. It needs:

- `query(sql_str)` — returns a mock job object with `.result()` and `.to_dataframe()`
- `load_telemetry(readings)` — bulk inserts using `INSERT INTO telemetry SELECT ... WHERE NOT EXISTS`

**Critical**: Open and close the DuckDB connection inside every method using `with duckdb.connect(...) as conn`.
Do not hold a connection open at the class level. This prevents lock conflicts when dbt runs in parallel.

---

## Task 6 — dbt transformation models

**Create a dbt project at `dbt_project/`.**

`dbt_project.yml` and `profiles.yml` should point to DuckDB:

```yaml
gridmind:
  outputs:
    dev:
      type: duckdb
      path: ../data/gridmind_bq.db
      threads: 1
  target: dev
```

Three SQL models:
- `models/staging/stg_telemetry.sql` — casts raw columns to correct types
- `models/marts/fleet_health.sql` — computes availability score per asset
- `models/marts/anomaly_summary.sql` — aggregates anomaly type frequencies across the fleet

---

## Task 7 — Airflow orchestration

**File to create: `airflow/dags/gridmind_pipeline.py`**

One DAG with this task chain:
```
generate_telemetry >> ingest_to_bigquery >> run_dbt_models >> run_agent_session >> alert_on_escalations
```

**File to create: `airflow/run_pipeline.py`**

A standalone script that runs the same tasks sequentially without Airflow's scheduler.
This is for local testing — someone should be able to run the full pipeline with one command.

---

## Task 8 — FastAPI intent router

**File to modify: `api/main.py`**

The `/chat` endpoint needs intent classification using `claude-haiku`. Two paths:

- **Simple data queries** (`show_status`, `show_anomalies`, `show_system`, `show_trends`) — skip LangGraph entirely.
  Execute the tool directly and return the result. This saves 1–3 seconds per request.
- **Operational intents** (`agent_run`) — start the full LangGraph loop.

The intent classifier output should be one of those string labels. Route based on that label.

---

## Verification — make sure this all works

Run the eval suite:
```bash
python -m evals.runner
```
All 15 scenarios must pass.

Run unit tests:
```bash

$env:KMP_DUPLICATE_LIB_OK="TRUE"

python -m unittest discover -s tests
```

These five test files all need 100% pass rate:
- `tests/test_geo.py` — zone assignment and haversine distances
- `tests/test_db.py` — in-memory SQL operations against the models
- `tests/test_ml.py` — MLP output shapes and prediction values
- `tests/test_vector_store.py` — FAISS path and fallback cosine similarity path
- `tests/test_dbt.py` — dbt project compiles without errors

---

## A few things to keep in mind

- **Postgres is optional.** The system must work end-to-end with just local JSON files.
  Never let a missing DB connection cause a crash anywhere in the agent loop.

- **API keys are optional.** The vector store fallback must work without any LLM API key configured.

- **DuckDB connections must be per-method.** Sharing a single connection across threads or
  processes will cause silent corruption or lock errors when dbt runs.

- **The ML model must self-bootstrap.** If `anomaly_model.pt` is missing, train it. Don't ask the
  user to run a separate training script.

- **Intent routing must actually save latency.** The whole point of bypassing LangGraph for simple
  queries is speed. Make sure the bypass path is genuinely direct — no unnecessary LLM calls.