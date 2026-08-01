"""Build and maintain evidence-backed, patient-confirmed care plans."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.core.time_utils import as_utc, utc_now
from app.models.care_plan import CareCase, CarePlan, CarePlanItem, CarePlanItemEvent
from app.models.medical_record import MedicalRecord
from app.models.visit_record import VisitRecord


_SENTENCE_SPLIT = re.compile(r"[\n。；;]+")
_DUE_PATTERN = re.compile(r"(\d+|[一二两三四五六七八九十]+)\s*(天|周|个月|月)后")
_TASK_RULES = (
    ("follow_up", ("复诊", "随访", "门诊"), "安排复诊或随访"),
    ("test", ("复查", "检查", "化验", "CT", "MRI", "超声", "抽血"), "完成医嘱中的复查或检查"),
    ("monitor", ("观察", "监测", "记录", "测量"), "按医嘱观察并记录症状或指标"),
)

FOLLOW_UP_REMINDER_INTERVAL = timedelta(hours=24)
OVERDUE_ESCALATION_DELAY = timedelta(hours=48)
MAX_REMINDERS_BEFORE_COORDINATOR_CASE = 2


def _next_monitoring_time(item: CarePlanItem, now: datetime) -> Optional[datetime]:
    """Schedule a non-clinical check-in without changing the medical plan."""
    due_at = as_utc(item.due_at)
    if due_at is None:
        return None
    return max(now, due_at - timedelta(hours=48))


def _open_follow_up_case(db: Session, item: CarePlanItem, *, reason: str, note: str) -> bool:
    existing_case = (
        db.query(CareCase)
        .filter(
            CareCase.care_plan_item_id == item.id,
            CareCase.status.in_(("open", "acknowledged")),
        )
        .first()
    )
    if existing_case is not None:
        return False
    item.care_cases.append(
        CareCase(
            patient_id=item.patient_id,
            hospital_id=item.care_plan.hospital_id,
            reason=reason,
            priority="high" if item.priority in ("high", "urgent") else "routine",
            patient_note=note,
        )
    )
    return True


def _activate_patient_follow_up(item: CarePlanItem, now: datetime) -> None:
    item.needs_patient_confirmation = True
    item.follow_up_status = "awaiting_acknowledgement"
    item.patient_acknowledged_at = None
    item.last_patient_response_at = None
    item.last_reminded_at = None
    item.reminder_count = 0
    item.next_reminder_at = now


def _parse_chinese_number(value: str) -> Optional[int]:
    if value.isdigit():
        return int(value)
    digits = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if value == "十":
        return 10
    if "十" in value:
        left, _, right = value.partition("十")
        tens = digits.get(left, 1) if left else 1
        ones = digits.get(right, 0) if right else 0
        return tens * 10 + ones
    return digits.get(value)


def _due_at(text: str, reference_time: datetime) -> Optional[datetime]:
    match = _DUE_PATTERN.search(text or "")
    if not match:
        return None
    amount = _parse_chinese_number(match.group(1))
    if amount is None:
        return None
    unit = match.group(2)
    days = amount if unit == "天" else amount * (7 if unit == "周" else 30)
    reference_time = as_utc(reference_time)
    return reference_time + timedelta(days=days)


def _candidate_tasks(source_type: str, source_id: str, reference_time: datetime, texts: list[str]) -> list[dict]:
    candidates: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for text in texts:
        for sentence in _SENTENCE_SPLIT.split(text or ""):
            excerpt = sentence.strip()
            if not excerpt:
                continue
            for task_type, keywords, title in _TASK_RULES:
                if any(keyword.lower() in excerpt.lower() for keyword in keywords):
                    key = (task_type, excerpt)
                    if key not in seen:
                        candidates.append(
                            {
                                "task_type": task_type,
                                "title": title,
                                "instructions": excerpt,
                                "due_at": _due_at(excerpt, reference_time),
                                "evidence_source_type": source_type,
                                "evidence_source_id": source_id,
                                "evidence_excerpt": excerpt,
                            }
                        )
                        seen.add(key)
                    break
    return candidates


def _load_source(db: Session, *, patient_id: str, source_type: str, source_id: str):
    if source_type == "visit_record":
        source = db.query(VisitRecord).filter(VisitRecord.id == source_id, VisitRecord.patient_id == patient_id).first()
        if source is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Visit record not found")
        return source, source.hospital_id, source.visit_date, source.visit_summary or "", source.follow_up_plan or ""
    source = db.query(MedicalRecord).filter(MedicalRecord.id == source_id, MedicalRecord.patient_id == patient_id).first()
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Medical record not found")
    return source, source.hospital_id, source.record_date, source.treatment_plan or "", source.notes or ""


def generate_care_plan(db: Session, *, patient_id: str, source_type: str, source_id: str) -> CarePlan:
    source, hospital_id, reference_time, primary_text, secondary_text = _load_source(
        db, patient_id=patient_id, source_type=source_type, source_id=source_id
    )
    existing = (
        db.query(CarePlan)
        .options(joinedload(CarePlan.items).joinedload(CarePlanItem.events))
        .filter(CarePlan.patient_id == patient_id, CarePlan.source_type == source_type, CarePlan.source_id == source_id)
        .first()
    )
    if existing:
        return existing

    source_label = "就诊" if source_type == "visit_record" else "病历"
    source_title = getattr(source, "department", None) or getattr(source, "title", None) or source_label
    plan = CarePlan(
        patient_id=patient_id,
        hospital_id=hospital_id,
        source_type=source_type,
        source_id=source_id,
        title=f"{source_title}后续安排",
        status="draft",
    )
    db.add(plan)
    candidates = _candidate_tasks(source_type, source_id, reference_time, [primary_text, secondary_text])
    medications = getattr(source, "medications", None)
    if source_type == "medical_record" and medications:
        candidates.append(
            {
                "task_type": "medication",
                "title": "按医嘱核对并完成用药",
                "instructions": "请按原始处方和药师说明执行，不要自行调整剂量或停药。",
                "due_at": None,
                "evidence_source_type": source_type,
                "evidence_source_id": source_id,
                "evidence_excerpt": medications.strip(),
            }
        )
    for candidate in candidates:
        plan.items.append(
            CarePlanItem(
                patient_id=patient_id,
                priority="routine",
                status="proposed",
                needs_patient_confirmation=True,
                **candidate,
            )
        )
    db.commit()
    return get_care_plan(db, plan.id)


def get_care_plan(db: Session, care_plan_id: str, *, patient_id: Optional[str] = None) -> CarePlan:
    plan = (
        db.query(CarePlan)
        .options(joinedload(CarePlan.items).joinedload(CarePlanItem.events))
        .filter(CarePlan.id == care_plan_id)
    )
    if patient_id:
        plan = plan.filter(CarePlan.patient_id == patient_id)
    plan = plan.first()
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Care plan not found")
    return plan


def list_care_plans(db: Session, *, patient_id: str, include_drafts: bool = True) -> list[CarePlan]:
    query = db.query(CarePlan).options(joinedload(CarePlan.items).joinedload(CarePlanItem.events)).filter(CarePlan.patient_id == patient_id)
    if not include_drafts:
        query = query.filter(CarePlan.status == "active")
    return query.order_by(CarePlan.updated_at.desc()).all()


def list_care_plan_review_queue(db: Session, *, hospital_id: str) -> list[CarePlan]:
    return (
        db.query(CarePlan)
        .options(joinedload(CarePlan.items).joinedload(CarePlanItem.events))
        .filter(CarePlan.hospital_id == hospital_id, CarePlan.status == "draft")
        .order_by(CarePlan.created_at.asc())
        .all()
    )


def publish_care_plan(
    db: Session,
    *,
    care_plan_id: str,
    hospital_id: str,
    clinician_id: str,
    clinician_note: Optional[str],
) -> CarePlan:
    plan = get_care_plan(db, care_plan_id)
    if plan.hospital_id != hospital_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Care plan not found")
    if plan.status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only draft care plans can be published")
    if not plan.items:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A care plan without verifiable items cannot be published")

    plan.status = "active"
    now = utc_now()
    plan.confirmed_at = now
    for item in plan.items:
        if item.status == "proposed":
            item.status = "pending"
            _activate_patient_follow_up(item, now)
            item.events.append(
                CarePlanItemEvent(
                    event_type="published",
                    note=clinician_note,
                    actor_type=f"clinician:{clinician_id}",
                )
            )
    db.commit()
    return get_care_plan(db, care_plan_id)


def confirm_care_plan(db: Session, *, care_plan_id: str, patient_id: str) -> CarePlan:
    plan = get_care_plan(db, care_plan_id, patient_id=patient_id)
    if plan.status == "draft":
        if not plan.items:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The source record has no verifiable care-plan items to confirm",
            )
        plan.status = "active"
        now = utc_now()
        plan.confirmed_at = now
        for item in plan.items:
            if item.status == "proposed":
                item.status = "pending"
                _activate_patient_follow_up(item, now)
                item.events.append(CarePlanItemEvent(event_type="confirmed", actor_type="patient"))
        db.commit()
    return get_care_plan(db, care_plan_id, patient_id=patient_id)


def update_care_plan_item(
    db: Session,
    *,
    item_id: str,
    patient_id: str,
    status_value: str,
    note: Optional[str],
    snoozed_until: Optional[datetime] = None,
) -> CarePlanItem:
    item = (
        db.query(CarePlanItem)
        .options(joinedload(CarePlanItem.events))
        .filter(CarePlanItem.id == item_id, CarePlanItem.patient_id == patient_id)
        .first()
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Care plan item not found")
    if item.status == "proposed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Confirm the care plan before updating a task")
    previous_status = item.status
    was_overdue = item.is_overdue
    now = utc_now()
    item.status = status_value
    if status_value == "completed":
        item.completed_at = now
        item.snoozed_until = None
        item.needs_patient_confirmation = False
        item.follow_up_status = "closed"
        item.last_patient_response_at = now
        item.execution_evidence_type = "patient_reported"
        item.next_reminder_at = None
    elif status_value == "skipped":
        item.completed_at = None
        item.snoozed_until = None
        item.needs_patient_confirmation = False
        item.follow_up_status = "closed"
        item.last_patient_response_at = now
        item.execution_evidence_type = "patient_reported_skipped"
        item.next_reminder_at = None
    elif status_value == "pending":
        item.completed_at = None
        item.snoozed_until = None
        item.follow_up_status = "monitoring"
        item.last_patient_response_at = now
        item.next_reminder_at = _next_monitoring_time(item, now)
    elif status_value == "snoozed":
        if snoozed_until is None or as_utc(snoozed_until) <= now:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="snoozed_until must be in the future")
        item.snoozed_until = as_utc(snoozed_until)
        item.follow_up_status = "monitoring"
        item.last_patient_response_at = now
        item.next_reminder_at = item.snoozed_until
    elif status_value == "needs_help":
        item.snoozed_until = None
        item.follow_up_status = "escalated"
        item.last_patient_response_at = now
        item.next_reminder_at = None
        _open_follow_up_case(
            db,
            item,
            reason="patient_needs_help",
            note=note or ("Patient requested hospital assistance after an overdue task." if was_overdue else "Patient requested hospital assistance."),
        )
    event_type = "reopened" if status_value == "pending" and previous_status != "pending" else status_value
    item.events.append(CarePlanItemEvent(event_type=event_type, note=note, actor_type="patient"))
    db.commit()
    db.refresh(item)
    return item


def acknowledge_care_plan_item(db: Session, *, item_id: str, patient_id: str) -> CarePlanItem:
    """Record that the patient has seen the task; this is not completion evidence."""
    item = (
        db.query(CarePlanItem)
        .options(joinedload(CarePlanItem.events))
        .filter(CarePlanItem.id == item_id, CarePlanItem.patient_id == patient_id)
        .first()
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Care plan item not found")
    if item.status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only pending tasks can be acknowledged")

    now = utc_now()
    if item.patient_acknowledged_at is None:
        item.patient_acknowledged_at = now
        item.events.append(CarePlanItemEvent(event_type="patient_acknowledged", actor_type="patient"))
    item.needs_patient_confirmation = False
    item.follow_up_status = "monitoring"
    item.last_patient_response_at = now
    item.next_reminder_at = _next_monitoring_time(item, now)
    db.commit()
    db.refresh(item)
    return item


def run_care_follow_up_cycle(db: Session, *, now: Optional[datetime] = None) -> dict[str, int]:
    """Create auditable in-app follow-up prompts and coordinator cases for exceptions.

    This routine deliberately does not infer clinical adherence. It only tracks patient
    acknowledgement, patient-reported completion, and missing responses.
    """
    current = as_utc(now) or utc_now()
    counters = {"reminders": 0, "overdue_follow_ups": 0, "coordinator_cases": 0}
    items = (
        db.query(CarePlanItem)
        .join(CarePlan)
        .options(joinedload(CarePlanItem.care_cases))
        .filter(CarePlan.status == "active", CarePlanItem.status == "pending")
        .all()
    )
    for item in items:
        due_at = as_utc(item.due_at)
        next_reminder_at = as_utc(item.next_reminder_at)
        if next_reminder_at is None or next_reminder_at > current:
            continue

        is_overdue = bool(due_at and due_at < current)
        item.last_reminded_at = current
        item.reminder_count = int(item.reminder_count or 0) + 1
        item.next_reminder_at = current + FOLLOW_UP_REMINDER_INTERVAL

        if is_overdue:
            item.follow_up_status = "follow_up_needed"
            item.events.append(
                CarePlanItemEvent(
                    event_type="overdue_follow_up_due",
                    note="Task is overdue and has not been confirmed as completed.",
                    actor_type="system",
                )
            )
            counters["overdue_follow_ups"] += 1
            if current - due_at >= OVERDUE_ESCALATION_DELAY and item.reminder_count >= MAX_REMINDERS_BEFORE_COORDINATOR_CASE:
                if _open_follow_up_case(
                    db,
                    item,
                    reason="unconfirmed_follow_up",
                    note="The patient has not confirmed execution after scheduled follow-up reminders.",
                ):
                    counters["coordinator_cases"] += 1
                item.follow_up_status = "escalated"
                item.next_reminder_at = None
        else:
            item.follow_up_status = "reminder_due"
            item.events.append(
                CarePlanItemEvent(
                    event_type="reminder_due",
                    note="In-app follow-up reminder is due; external delivery can be connected by a notification provider.",
                    actor_type="system",
                )
            )
            counters["reminders"] += 1

    if any(counters.values()):
        db.commit()
    return counters


def reactivate_due_snoozed_tasks(db: Session, *, now: Optional[datetime] = None) -> int:
    current = as_utc(now) or utc_now()
    items = (
        db.query(CarePlanItem)
        .filter(CarePlanItem.status == "snoozed", CarePlanItem.snoozed_until.isnot(None), CarePlanItem.snoozed_until <= current)
        .all()
    )
    for item in items:
        item.status = "pending"
        item.snoozed_until = None
        item.follow_up_status = "monitoring"
        item.next_reminder_at = _next_monitoring_time(item, current)
        item.events.append(CarePlanItemEvent(event_type="snooze_expired", actor_type="system"))
    if items:
        db.commit()
    return len(items)


def list_care_cases(
    db: Session,
    *,
    hospital_id: str,
    status_value: Optional[str] = None,
    assignee_id: Optional[str] = None,
) -> list[CareCase]:
    query = db.query(CareCase).filter(CareCase.hospital_id == hospital_id)
    if status_value:
        query = query.filter(CareCase.status == status_value)
    if assignee_id:
        query = query.filter(CareCase.assignee_id == assignee_id)
    return query.order_by(CareCase.priority.desc(), CareCase.created_at.asc()).all()


def acknowledge_care_case(
    db: Session,
    *,
    case_id: str,
    hospital_id: str,
    assignee_id: Optional[str],
    coordinator_note: Optional[str],
) -> CareCase:
    case = db.query(CareCase).filter(CareCase.id == case_id, CareCase.hospital_id == hospital_id).first()
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Care case not found")
    if case.status == "open":
        case.status = "acknowledged"
        case.acknowledged_at = utc_now()
    case.assignee_id = assignee_id or case.assignee_id
    case.coordinator_note = coordinator_note or case.coordinator_note
    db.commit()
    db.refresh(case)
    return case


def resolve_care_case(
    db: Session,
    *,
    case_id: str,
    hospital_id: str,
    assignee_id: Optional[str],
    coordinator_note: Optional[str],
) -> CareCase:
    case = acknowledge_care_case(
        db,
        case_id=case_id,
        hospital_id=hospital_id,
        assignee_id=assignee_id,
        coordinator_note=coordinator_note,
    )
    case.status = "resolved"
    case.resolved_at = utc_now()
    db.commit()
    db.refresh(case)
    return case
