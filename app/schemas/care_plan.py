from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CarePlanGenerateRequest(BaseModel):
    patient_id: str
    source_type: Literal["visit_record", "medical_record"]
    source_id: str


class CarePlanItemStatusUpdate(BaseModel):
    patient_id: str
    status: Literal["pending", "completed", "skipped", "snoozed", "needs_help"]
    note: Optional[str] = Field(default=None, max_length=1000)
    snoozed_until: Optional[datetime] = None

    @model_validator(mode="after")
    def validate_snooze(self):
        if self.status == "snoozed" and self.snoozed_until is None:
            raise ValueError("snoozed_until is required when status is snoozed")
        return self


class CarePlanPublishRequest(BaseModel):
    clinician_id: str = Field(..., min_length=1, max_length=64)
    clinician_note: Optional[str] = Field(default=None, max_length=2000)


class CarePlanItemEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_type: str
    note: Optional[str] = None
    actor_type: str
    created_at: datetime


class CarePlanItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    care_plan_id: str
    patient_id: str
    task_type: str
    title: str
    instructions: Optional[str] = None
    priority: str
    status: str
    due_at: Optional[datetime] = None
    evidence_source_type: str
    evidence_source_id: str
    evidence_excerpt: str
    needs_patient_confirmation: bool
    follow_up_status: str
    patient_acknowledged_at: Optional[datetime] = None
    last_patient_response_at: Optional[datetime] = None
    last_reminded_at: Optional[datetime] = None
    next_reminder_at: Optional[datetime] = None
    reminder_count: int
    execution_evidence_type: Optional[str] = None
    needs_follow_up: bool
    is_overdue: bool
    snoozed_until: Optional[datetime] = None
    is_snoozed: bool
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    events: list[CarePlanItemEventRead] = Field(default_factory=list)


class CarePlanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    patient_id: str
    hospital_id: str
    source_type: str
    source_id: str
    title: str
    status: str
    confirmed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    pending_count: int
    overdue_count: int
    items: list[CarePlanItemRead] = Field(default_factory=list)


class CareCaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    patient_id: str
    hospital_id: str
    care_plan_item_id: str
    care_plan_item_title: str
    care_plan_item_due_at: Optional[datetime] = None
    reason: str
    priority: str
    status: str
    patient_note: Optional[str] = None
    coordinator_note: Optional[str] = None
    assignee_id: Optional[str] = None
    acknowledged_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class CareCaseResolveRequest(BaseModel):
    coordinator_note: Optional[str] = Field(default=None, max_length=2000)
    assignee_id: Optional[str] = Field(default=None, max_length=64)
