import uuid
from datetime import datetime
from app.core.time_utils import utc_now

from sqlalchemy import Column, DateTime, Float, Integer, String, Text

from app.core.database import Base


class AuditLog(Base):
    """Audit log for patient data access tracking."""

    __tablename__ = "audit_log"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    patient_id = Column(String(36), nullable=True, index=True)
    hospital_id = Column(String(64), nullable=True)
    endpoint = Column(String(255), nullable=False)
    method = Column(String(10), nullable=False)
    action = Column(String(50), nullable=False, index=True)
    status_code = Column(String(10), nullable=True)
    client_ip = Column(String(50), nullable=True)
    auth_verified = Column(String(10), nullable=True)
    details = Column(Text, nullable=True)
    duration_ms = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class EvaluationRun(Base):
    """Persisted, versioned result of one offline or console evaluation case."""

    __tablename__ = "evaluation_runs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id = Column(String(36), nullable=False, index=True)
    case_id = Column(String(100), nullable=False, index=True)
    case_version = Column(String(64), nullable=False)
    scoring_version = Column(String(32), nullable=False)
    status = Column(String(16), nullable=False, default="completed", index=True)
    passed = Column(String(8), nullable=False)
    total_score = Column(Float, nullable=False)
    duration_seconds = Column(Float, nullable=True)
    model_version = Column(String(255), nullable=True)
    prompt_version = Column(String(255), nullable=True)
    knowledge_base_version = Column(String(255), nullable=True)
    trace_id = Column(String(64), nullable=True, index=True)
    result_json = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)
