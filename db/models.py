"""
db/models.py

SQLAlchemy declarative models for the GridMind relational layer.
"""

from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, JSON, ForeignKey
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class System(Base):
    __tablename__ = "systems"

    system_id = Column(String, primary_key=True)
    location = Column(String, nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    system_type = Column(String, nullable=False)
    solar_capacity_kw = Column(Float, nullable=False)
    solar_output_kw = Column(Float, nullable=False)
    expected_output_kw = Column(Float, nullable=False)
    battery_soc_pct = Column(Float, nullable=True)
    grid_feed_in_kw = Column(Float, nullable=False)
    status = Column(String, nullable=False)
    anomaly_type = Column(String, nullable=True)
    last_updated = Column(String, nullable=False)
    alerts = Column(JSON, default=list)
    history = Column(JSON, default=list)


class Anomaly(Base):
    __tablename__ = "anomalies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    system_id = Column(String, ForeignKey("systems.system_id"), nullable=False)
    anomaly_type = Column(String, nullable=False)
    detected_at = Column(DateTime, nullable=False)
    status = Column(String, nullable=False)


class Action(Base):
    __tablename__ = "actions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    system_id = Column(String, ForeignKey("systems.system_id"), nullable=False)
    action_type = Column(String, nullable=False)
    notes = Column(String, nullable=True)
    timestamp = Column(DateTime, nullable=False)
    success = Column(Boolean, nullable=False)


class Escalation(Base):
    __tablename__ = "escalations"

    ticket_id = Column(String, primary_key=True)
    system_id = Column(String, ForeignKey("systems.system_id"), nullable=False)
    reason = Column(String, nullable=False)
    severity = Column(String, nullable=False)
    created_at = Column(String, nullable=False)
    status = Column(String, nullable=False, default="open")
