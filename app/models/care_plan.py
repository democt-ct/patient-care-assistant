import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.time_utils import as_utc, utc_now


class CarePlan(Base):
    __tablename__ = "care_plans"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    patient_id = Column(String(36), ForeignKey("patients.id"), nullable=False, index=True)
    hospital_id = Column(String(64), nullable=False, index=True)
    source_type = Column(String(32), nullable=False, index=True)
    source_id = Column(String(36), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    status = Column(String(32), nullable=False, default="draft", index=True)
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    items = relationship("CarePlanItem", back_populates="care_plan", cascade="all, delete-orphan")

    @property
    def pending_count(self) -> int:
        return sum(item.status == "pending" for item in self.items)

    @property
    def overdue_count(self) -> int:
        return sum(item.is_overdue for item in self.items)


class CarePlanItem(Base):
    __tablename__ = "care_plan_items"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    care_plan_id = Column(String(36), ForeignKey("care_plans.id"), nullable=False, index=True)
    patient_id = Column(String(36), ForeignKey("patients.id"), nullable=False, index=True)
    task_type = Column(String(32), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    instructions = Column(Text, nullable=True)
    priority = Column(String(16), nullable=False, default="routine", index=True)
    status = Column(String(32), nullable=False, default="proposed", index=True)
    due_at = Column(DateTime(timezone=True), nullable=True, index=True)
    evidence_source_type = Column(String(32), nullable=False)
    evidence_source_id = Column(String(36), nullable=False)
    evidence_excerpt = Column(Text, nullable=False)
    needs_patient_confirmation = Column(Boolean, nullable=False, default=True)
    follow_up_status = Column(String(32), nullable=False, default="awaiting_acknowledgement", index=True)
    patient_acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    last_patient_response_at = Column(DateTime(timezone=True), nullable=True)
    last_reminded_at = Column(DateTime(timezone=True), nullable=True)
    next_reminder_at = Column(DateTime(timezone=True), nullable=True, index=True)
    reminder_count = Column(Integer, nullable=False, default=0)
    execution_evidence_type = Column(String(32), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    snoozed_until = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    care_plan = relationship("CarePlan", back_populates="items")
    events = relationship("CarePlanItemEvent", back_populates="item", cascade="all, delete-orphan")
    care_cases = relationship("CareCase", back_populates="care_plan_item", cascade="all, delete-orphan")

    @property
    def is_overdue(self) -> bool:
        return bool(self.status == "pending" and self.due_at and as_utc(self.due_at) < utc_now())

    @property
    def is_snoozed(self) -> bool:
        return bool(self.status == "snoozed" and self.snoozed_until and as_utc(self.snoozed_until) > utc_now())

    @property
    def needs_follow_up(self) -> bool:
        return self.status == "pending" and self.follow_up_status in {
            "awaiting_acknowledgement", "reminder_due", "follow_up_needed", "escalated"
        }


class CarePlanItemEvent(Base):
    __tablename__ = "care_plan_item_events"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    care_plan_item_id = Column(String(36), ForeignKey("care_plan_items.id"), nullable=False, index=True)
    event_type = Column(String(32), nullable=False, index=True)
    note = Column(Text, nullable=True)
    actor_type = Column(String(32), nullable=False, default="patient")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    item = relationship("CarePlanItem", back_populates="events")


class CareCase(Base):
    __tablename__ = "care_cases"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    patient_id = Column(String(36), ForeignKey("patients.id"), nullable=False, index=True)
    hospital_id = Column(String(64), nullable=False, index=True)
    care_plan_item_id = Column(String(36), ForeignKey("care_plan_items.id"), nullable=False, index=True)
    reason = Column(String(64), nullable=False, index=True)
    priority = Column(String(16), nullable=False, default="routine", index=True)
    status = Column(String(32), nullable=False, default="open", index=True)
    patient_note = Column(Text, nullable=True)
    coordinator_note = Column(Text, nullable=True)
    assignee_id = Column(String(64), nullable=True, index=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    care_plan_item = relationship("CarePlanItem", back_populates="care_cases")

    @property
    def care_plan_item_title(self) -> str:
        return self.care_plan_item.title if self.care_plan_item else ""

    @property
    def care_plan_item_due_at(self):
        return self.care_plan_item.due_at if self.care_plan_item else None
