import unittest
from pathlib import Path
import tempfile
import shutil

from db.bigquery_client import BigQueryClient

class TestBigQueryClient(unittest.TestCase):
    def setUp(self):
        # Create a temp dir for our temp duckdb database
        self.test_dir = tempfile.mkdtemp()
        self.db_path = str(Path(self.test_dir) / "test_gridmind_bq.db")
        
        # Instantiate client and override the db path
        self.client = BigQueryClient()
        self.client.db_path = self.db_path
        self.client.init_table()

    def tearDown(self):
        # Remove temporary directory and db file
        shutil.rmtree(self.test_dir)

    def test_init_table_and_insert(self):
        import duckdb
        # Verify table exists
        with duckdb.connect(self.client.db_path) as conn:
            tables = conn.execute("SHOW TABLES").fetchall()
            self.assertIn(("telemetry",), tables)

    def test_load_and_query_telemetry(self):
        readings = [
            {
                "system_id": "SYS_A",
                "timestamp": "2026-06-11T12:00:00+00:00",
                "solar_output_kw": 5.0,
                "expected_output_kw": 5.0,
                "battery_soc_pct": 100.0,
                "grid_feed_in_kw": 4.0,
                "status": "healthy"
            },
            {
                "system_id": "SYS_A",
                "timestamp": "2026-06-11T13:00:00+00:00",
                "solar_output_kw": 4.5,
                "expected_output_kw": 5.0,
                "battery_soc_pct": 98.0,
                "grid_feed_in_kw": 3.8,
                "status": "healthy"
            }
        ]
        
        self.client.load_telemetry(readings)
        
        # Query the telemetry table
        res_job = self.client.query("SELECT COUNT(*) as count FROM telemetry")
        res = res_job.result()
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["count"], 2)

        # Check duplicate insertion prevention
        self.client.load_telemetry(readings)
        res_job_2 = self.client.query("SELECT COUNT(*) as count FROM telemetry")
        res_2 = res_job_2.result()
        self.assertEqual(res_2[0]["count"], 2)

if __name__ == "__main__":
    unittest.main()
