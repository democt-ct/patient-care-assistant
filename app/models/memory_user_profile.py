import uuid
from datetime import datetime
from app.core.time_utils import utc_now

from sqlalchemy import Column, DateTime, String, Text

from app.core.database import Base


class MemoryUserProfile(Base):
    __tablename__ = "memory_user_profiles"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    patient_id = Column(String(36), nullable=False, unique=True, index=True)
    hospital_id = Column(String(64), nullable=False, index=True)
    profile_summary = Column(Text, nullable=False)
    communication_preference = Column(String(50), nullable=True)
    risk_focus = Column(String(255), nullable=True)
    focus_topics = Column(Text, nullable=True)
    care_needs = Column(Text, nullable=True)
    source_summary = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
