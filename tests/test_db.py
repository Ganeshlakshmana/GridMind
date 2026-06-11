import unittest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import Base, System, Anomaly, Action, Escalation

class TestDatabaseLayer(unittest.TestCase):
    def setUp(self):
        # Create an in-memory SQLite database for unit testing
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        SessionLocal = sessionmaker(bind=self.engine)
        self.session = SessionLocal()

    def tearDown(self):
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)

    def test_create_and_query_system(self):
        # Insert a new system
        sys_obj = System(
            system_id="SYS_TEST_001",
            location="Berlin-Mitte",
            latitude=52.51,
            longitude=13.40,
            system_type="solar_battery",
            solar_capacity_kw=15.0,
            solar_output_kw=8.5,
            expected_output_kw=10.0,
            battery_soc_pct=82.0,
            grid_feed_in_kw=5.0,
            status="healthy",
            anomaly_type="healthy",
            last_updated=datetime.now(timezone.utc).isoformat(),
            alerts=[],
            history=[]
        )
        self.session.add(sys_obj)
        self.session.commit()

        # Query it back
        queried = self.session.query(System).filter_by(system_id="SYS_TEST_001").first()
        self.assertIsNotNone(queried)
        self.assertEqual(queried.location, "Berlin-Mitte")
        self.assertEqual(queried.battery_soc_pct, 82.0)

    def test_anomaly_log(self):
        # Create system first
        sys_obj = System(
            system_id="SYS_TEST_002",
            location="Neukölln",
            latitude=52.46,
            longitude=13.40,
            system_type="solar_only",
            solar_capacity_kw=10.0,
            solar_output_kw=0.0,
            expected_output_kw=5.0,
            grid_feed_in_kw=0.0,
            status="degraded",
            anomaly_type="low_output",
            last_updated=datetime.now(timezone.utc).isoformat()
        )
        self.session.add(sys_obj)
        self.session.commit()

        # Create anomaly record
        anomaly_obj = Anomaly(
            system_id="SYS_TEST_002",
            anomaly_type="low_output",
            detected_at=datetime.now(timezone.utc),
            status="active"
        )
        self.session.add(anomaly_obj)
        self.session.commit()

        # Query anomaly
        queried = self.session.query(Anomaly).filter_by(system_id="SYS_TEST_002").first()
        self.assertIsNotNone(queried)
        self.assertEqual(queried.anomaly_type, "low_output")
        self.assertEqual(queried.status, "active")

    def test_action_audit_log(self):
        sys_obj = System(
            system_id="SYS_TEST_003",
            location="Pankow",
            latitude=52.57,
            longitude=13.40,
            system_type="solar_battery",
            solar_capacity_kw=10.0,
            solar_output_kw=5.0,
            expected_output_kw=5.0,
            grid_feed_in_kw=4.0,
            status="healthy",
            last_updated=datetime.now(timezone.utc).isoformat()
        )
        self.session.add(sys_obj)
        
        action_obj = Action(
            system_id="SYS_TEST_003",
            action_type="restart_inverter",
            notes="Inverter restarted successfully",
            timestamp=datetime.now(timezone.utc),
            success=True
        )
        self.session.add(action_obj)
        self.session.commit()

        queried = self.session.query(Action).filter_by(system_id="SYS_TEST_003").first()
        self.assertIsNotNone(queried)
        self.assertEqual(queried.action_type, "restart_inverter")
        self.assertTrue(queried.success)

    def test_escalation(self):
        sys_obj = System(
            system_id="SYS_TEST_004",
            location="Spandau",
            latitude=52.51,
            longitude=13.25,
            system_type="solar_battery",
            solar_capacity_kw=12.0,
            solar_output_kw=0.0,
            expected_output_kw=6.0,
            grid_feed_in_kw=0.0,
            status="offline",
            last_updated=datetime.now(timezone.utc).isoformat()
        )
        self.session.add(sys_obj)

        esc_obj = Escalation(
            ticket_id="TICKET-12345",
            system_id="SYS_TEST_004",
            reason="System offline for >3 consecutive readings",
            severity="high",
            created_at=datetime.now(timezone.utc).isoformat(),
            status="open"
        )
        self.session.add(esc_obj)
        self.session.commit()

        queried = self.session.query(Escalation).filter_by(ticket_id="TICKET-12345").first()
        self.assertIsNotNone(queried)
        self.assertEqual(queried.system_id, "SYS_TEST_004")
        self.assertEqual(queried.severity, "high")
        self.assertEqual(queried.status, "open")

if __name__ == "__main__":
    unittest.main()
