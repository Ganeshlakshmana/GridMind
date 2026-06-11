"""
airflow/dags/gridmind_pipeline.py

Airflow DAG orchestrating VPP telemetry generation, ingestion, dbt modeling,
agent run, and alerting.
"""

from datetime import datetime, timedelta
import os
import subprocess

# Standard Airflow imports (we support standard DAG imports, and import safely)
try:
    from airflow import DAG
    from airflow.operators.python import PythonOperator
except ImportError:
    # Safe fallback when running local simulation
    DAG = None
    PythonOperator = None


default_args = {
    'owner': 'gridmind',
    'depends_on_past': False,
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}


def generate_telemetry() -> None:
    """Task 1: Simulate new sensor readings."""
    print("Generating telemetry...")
    # In simulation, we call the generate scripts
    from data.generate_fleet import build_fleet, validate, main as gen_fleet
    from data.generate_history import main as gen_hist
    import sys

    # Backup sys.argv
    old_args = sys.argv
    sys.argv = [sys.argv[0], "--seed", "42"]
    try:
        gen_fleet()
        gen_hist()
    finally:
        sys.argv = old_args


def ingest_to_bigquery() -> None:
    """Task 2: Sync raw JSON fleet telemetry to BigQuery/DuckDB."""
    print("Ingesting telemetry to BigQuery...")
    from db.bigquery_client import sync_json_to_duckdb
    sync_json_to_duckdb()
    print("Telemetry synced to BigQuery (DuckDB table 'telemetry').")


def run_dbt_models() -> None:
    """Task 3: Execute dbt transformation models."""
    print("Running dbt models...")
    import sys
    project_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "dbt_project"
    )
    
    # Locate dbt executable relative to the current virtualenv Python binary
    dbt_bin = "dbt"
    python_dir = os.path.dirname(sys.executable)
    possible_dbt = os.path.join(python_dir, "dbt.exe" if os.name == "nt" else "dbt")
    if os.path.exists(possible_dbt):
        dbt_bin = possible_dbt

    # Execute dbt run locally
    result = subprocess.run(
        [dbt_bin, "run", "--profiles-dir", "."],
        cwd=project_dir,
        capture_output=True,
        text=True,
        shell=True,
    )
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)
        raise RuntimeError(f"dbt run failed: {result.stderr}")


def run_agent_session() -> None:
    """Task 4: Run LangGraph operational diagnostic and resolve issues."""
    print("Running LangGraph agent diagnostics...")
    from agent.runner import run_session
    report = run_session("Run a full fleet diagnostic and fix what you can.")
    print(f"Agent session complete. Health score: {report.get('executive_summary', {}).get('health_score_pct')}%")


def alert_on_escalations() -> None:
    """Task 5: Check ticket counts and alert if above threshold."""
    print("Checking escalations count...")
    from data.fleet_store import load_escalations
    escalations = load_escalations()
    open_tickets = [e for e in escalations if e.get("status") == "open"]
    if len(open_tickets) > 3:
        print(f"ALERT: High volume of open escalations: {len(open_tickets)} tickets!")
    else:
        print(f"Status check OK. Open escalations count: {len(open_tickets)}")


# ── DAG Declaration ─────────────────────────────────────────────────────────

if DAG is not None:
    with DAG(
        'gridmind_pipeline',
        default_args=default_args,
        description='Autonomous Virtual Power Plant Operations Ingestion & Remediation Pipeline',
        schedule_interval=timedelta(hours=1),
        start_date=datetime(2026, 6, 1),
        catchup=False,
    ) as dag:

        t1 = PythonOperator(
            task_id='generate_telemetry',
            python_callable=generate_telemetry,
        )

        t2 = PythonOperator(
            task_id='ingest_to_bigquery',
            python_callable=ingest_to_bigquery,
        )

        t3 = PythonOperator(
            task_id='run_dbt_models',
            python_callable=run_dbt_models,
        )

        t4 = PythonOperator(
            task_id='run_agent_session',
            python_callable=run_agent_session,
        )

        t5 = PythonOperator(
            task_id='alert_on_escalations',
            python_callable=alert_on_escalations,
        )

        t1 >> t2 >> t3 >> t4 >> t5
