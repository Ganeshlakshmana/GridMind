"""
airflow/run_pipeline.py

Local execution runner for the GridMind VPP operations pipeline.
Runs tasks sequentially to simulate an Airflow DAG run.
"""

import os
import sys
from pathlib import Path

# Fix OpenMP conflict between FAISS and PyTorch on Windows
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

# Add project root directory to sys.path
sys.path.append(str(Path(__file__).parent.parent))

from airflow.dags.gridmind_pipeline import (
    generate_telemetry,
    ingest_to_bigquery,
    run_dbt_models,
    run_agent_session,
    alert_on_escalations,
)


def main() -> None:
    print("\n" + "=" * 64)
    print("  GRIDMIND PIPELINE EXECUTION SIMULATOR")
    print("=" * 64 + "\n")

    # 1. Telemetry Generation
    print("Running Task 1/5: generate_telemetry")
    generate_telemetry()
    print("Task 1/5 complete.\n")

    # 2. Ingest to BigQuery (DuckDB)
    print("Running Task 2/5: ingest_to_bigquery")
    ingest_to_bigquery()
    print("Task 2/5 complete.\n")

    # 3. Run dbt models
    print("Running Task 3/5: run_dbt_models")
    try:
        run_dbt_models()
        print("Task 3/5 complete.\n")
    except Exception as e:
        print(f"Task 3/5 failed: {e}\n")
        sys.exit(1)

    # 4. Trigger LangGraph VPP Agent
    print("Running Task 4/5: run_agent_session")
    try:
        run_agent_session()
        print("Task 4/5 complete.\n")
    except Exception as e:
        print(f"Task 4/5 failed: {e}\n")
        sys.exit(1)

    # 5. Alert checks
    print("Running Task 5/5: alert_on_escalations")
    alert_on_escalations()
    print("Task 5/5 complete.\n")

    print("=" * 64)
    print("Pipeline Simulation Completed Successfully!")
    print("=" * 64 + "\n")


if __name__ == "__main__":
    main()
