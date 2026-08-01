import uuid
from datetime import datetime
from app.core.time_utils import utc_now

from sqlalchemy import Column, DateTime, String, Text

from app.core.database import Base


class MemorySessionBufferMessage(Base):
    __tablename__ = "memory_session_buffer_messages"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(64), nullable=False, index=True)
    hospital_id = Column(String(64), nullable=True, index=True)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
