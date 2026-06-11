"""
db/bigquery_client.py

Google BigQuery client mock using a local DuckDB instance.
Supports exact BigQuery query and load patterns with sequential file-sharing.
"""

from pathlib import Path
import pandas as pd

# Global client cache
_bq_client_cache = None


class BigQueryClient:
    """
    Mock Google BigQuery client executing SQL queries locally on DuckDB.
    Opens and closes connections on-demand to avoid locking files across processes.
    """
    def __init__(self):
        self.db_path = str(Path(__file__).parent.parent / "data" / "gridmind_bq.db")
        # Ensure parent directories exist
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.init_table()

    def init_table(self) -> None:
        """
        Create the time-series telemetry table.
        """
        import duckdb
        with duckdb.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS telemetry (
                    system_id VARCHAR,
                    timestamp TIMESTAMP,
                    solar_output_kw DOUBLE,
                    expected_output_kw DOUBLE,
                    battery_soc_pct DOUBLE,
                    grid_feed_in_kw DOUBLE,
                    status VARCHAR
                )
            """)

    def query(self, query_str: str):
        """
        Emulate the bigquery.Client().query() call pattern.
        """
        class MockQueryJob:
            def __init__(self, db_path, sql):
                self.db_path = db_path
                self.sql = sql

            def to_dataframe(self) -> pd.DataFrame:
                import duckdb
                with duckdb.connect(self.db_path) as conn:
                    return conn.query(self.sql).to_df()

            def result(self) -> list[dict]:
                df = self.to_dataframe()
                return df.to_dict(orient="records")

        return MockQueryJob(self.db_path, query_str)

    def load_telemetry(self, readings: list[dict]) -> None:
        """
        Bulk load telemetry records into DuckDB.
        """
        if not readings:
            return

        df = pd.DataFrame(readings)
        df["timestamp"] = pd.to_datetime(df["timestamp"])

        import duckdb
        with duckdb.connect(self.db_path) as conn:
            conn.register("new_data", df)
            conn.execute("""
                INSERT INTO telemetry
                SELECT 
                    system_id,
                    timestamp,
                    solar_output_kw,
                    expected_output_kw,
                    battery_soc_pct,
                    grid_feed_in_kw,
                    status
                FROM new_data
                WHERE NOT EXISTS (
                    SELECT 1 FROM telemetry t
                    WHERE t.system_id = new_data.system_id
                    AND t.timestamp = new_data.timestamp
                )
            """)
            conn.unregister("new_data")


def get_bq_client() -> BigQueryClient:
    """
    Get the global BigQuery mock client instance.
    """
    global _bq_client_cache
    if _bq_client_cache is None:
        _bq_client_cache = BigQueryClient()
    return _bq_client_cache


def sync_json_to_duckdb() -> None:
    """
    Load data from fleet_store into the DuckDB telemetry table.
    """
    from data.fleet_store import load_fleet
    client = get_bq_client()

    try:
        fleet = load_fleet()
    except Exception:
        # Fallback if fleet doesn't exist yet
        return

    readings = []
    for s in fleet:
        system_id = s["system_id"]
        for r in s.get("history", []):
            if r.get("timestamp"):
                readings.append({
                    "system_id":          system_id,
                    "timestamp":          r["timestamp"],
                    "solar_output_kw":    r.get("solar_output_kw"),
                    "expected_output_kw": r.get("expected_output_kw"),
                    "battery_soc_pct":    r.get("battery_soc_pct"),
                    "grid_feed_in_kw":    r.get("grid_feed_in_kw"),
                    "status":             r.get("status"),
                })

    if readings:
        client.load_telemetry(readings)
