from datetime import datetime, timedelta, timezone

import pytest
from app.core.time_utils import as_utc
from fastapi import HTTPException

from app.models.patient import Patient
from app.models.medical_record import MedicalRecord
from app.models.visit_record import VisitRecord
from app.services.care_plan_service import (
    acknowledge_care_plan_item,
    confirm_care_plan,
    generate_care_plan,
    list_care_cases,
    publish_care_plan,
    reactivate_due_snoozed_tasks,
    run_care_follow_up_cycle,
    update_care_plan_item,
)


def _seed_visit(db_session):
    patient = Patient(
        hospital_id="hospital-a",
        patient_code="CARE001",
        full_name="照护计划测试患者",
    )
    db_session.add(patient)
    db_session.flush()
    visit = VisitRecord(
        patient_id=patient.id,
        hospital_id=patient.hospital_id,
        visit_type="outpatient",
        department="心内科",
        visit_summary="病情稳定。",
        follow_up_plan="两周后复诊并复查血常规；每天记录血压变化。",
        visit_date=datetime(2026, 7, 1),
    )
    db_session.add(visit)
    db_session.commit()
    return patient, visit


def test_plan_is_created_from_record_evidence_and_requires_confirmation(db_session):
    patient, visit = _seed_visit(db_session)

    plan = generate_care_plan(
        db_session,
        patient_id=patient.id,
        source_type="visit_record",
        source_id=visit.id,
    )

    assert plan.status == "draft"
    assert plan.items
    assert all(item.status == "proposed" for item in plan.items)
    assert all(item.evidence_source_id == visit.id for item in plan.items)
    assert any(as_utc(item.due_at) == datetime(2026, 7, 15, tzinfo=timezone.utc) for item in plan.items)

    active_plan = confirm_care_plan(db_session, care_plan_id=plan.id, patient_id=patient.id)

    assert active_plan.status == "active"
    assert all(item.status == "pending" for item in active_plan.items)


def test_task_completion_creates_a_patient_event(db_session):
    patient, visit = _seed_visit(db_session)
    plan = generate_care_plan(
        db_session,
        patient_id=patient.id,
        source_type="visit_record",
        source_id=visit.id,
    )
    active_plan = confirm_care_plan(db_session, care_plan_id=plan.id, patient_id=patient.id)

    updated = update_care_plan_item(
        db_session,
        item_id=active_plan.items[0].id,
        patient_id=patient.id,
        status_value="completed",
        note="已完成",
    )

    assert updated.status == "completed"
    assert updated.completed_at is not None
    assert updated.events[-1].event_type == "completed"


def test_clinician_can_publish_a_draft_plan(db_session):
    patient, visit = _seed_visit(db_session)
    plan = generate_care_plan(
        db_session,
        patient_id=patient.id,
        source_type="visit_record",
        source_id=visit.id,
    )

    published = publish_care_plan(
        db_session,
        care_plan_id=plan.id,
        hospital_id=patient.hospital_id,
        clinician_id="doctor-demo",
        clinician_note="已核对原始随访计划",
    )

    assert published.status == "active"
    assert all(item.status == "pending" for item in published.items)
    assert all(item.events[-1].event_type == "published" for item in published.items)


def test_source_must_belong_to_the_requested_patient(db_session):
    patient, visit = _seed_visit(db_session)

    with pytest.raises(HTTPException) as exc_info:
        generate_care_plan(
            db_session,
            patient_id="someone-else",
            source_type="visit_record",
            source_id=visit.id,
        )

    assert exc_info.value.status_code == 404


def test_patient_cannot_confirm_another_patients_plan(db_session):
    patient, visit = _seed_visit(db_session)
    plan = generate_care_plan(
        db_session,
        patient_id=patient.id,
        source_type="visit_record",
        source_id=visit.id,
    )

    with pytest.raises(HTTPException) as exc_info:
        confirm_care_plan(db_session, care_plan_id=plan.id, patient_id="someone-else")

    assert exc_info.value.status_code == 404


def test_medication_task_references_existing_prescription_without_generating_a_dose(db_session):
    patient, _ = _seed_visit(db_session)
    record = MedicalRecord(
        patient_id=patient.id,
        hospital_id=patient.hospital_id,
        record_type="outpatient",
        title="复诊病历",
        medications="药物 A；药物 B",
    )
    db_session.add(record)
    db_session.commit()

    plan = generate_care_plan(
        db_session,
        patient_id=patient.id,
        source_type="medical_record",
        source_id=record.id,
    )

    medication = next(item for item in plan.items if item.task_type == "medication")
    assert medication.evidence_excerpt == "药物 A；药物 B"
    assert "剂量" in medication.instructions


def test_empty_draft_cannot_be_confirmed(db_session):
    patient, _ = _seed_visit(db_session)
    empty_visit = VisitRecord(
        patient_id=patient.id,
        hospital_id=patient.hospital_id,
        visit_type="outpatient",
        department="普通门诊",
        visit_date=datetime(2026, 7, 2),
    )
    db_session.add(empty_visit)
    db_session.commit()
    plan = generate_care_plan(
        db_session,
        patient_id=patient.id,
        source_type="visit_record",
        source_id=empty_visit.id,
    )

    with pytest.raises(HTTPException) as exc_info:
        confirm_care_plan(db_session, care_plan_id=plan.id, patient_id=patient.id)

    assert exc_info.value.status_code == 409


def test_snoozed_task_reactivates_with_an_audit_event(db_session):
    patient, visit = _seed_visit(db_session)
    plan = generate_care_plan(db_session, patient_id=patient.id, source_type="visit_record", source_id=visit.id)
    plan = confirm_care_plan(db_session, care_plan_id=plan.id, patient_id=patient.id)
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)

    item = update_care_plan_item(
        db_session,
        item_id=plan.items[0].id,
        patient_id=patient.id,
        status_value="snoozed",
        note="明天再处理",
        snoozed_until=tomorrow,
    )
    assert item.status == "snoozed"
    assert as_utc(item.snoozed_until) == tomorrow

    count = reactivate_due_snoozed_tasks(db_session, now=tomorrow + timedelta(days=1))
    db_session.refresh(item)
    assert count == 1
    assert item.status == "pending"
    assert item.events[-1].event_type == "snooze_expired"


def test_needs_help_creates_one_open_care_case(db_session):
    patient, visit = _seed_visit(db_session)
    plan = generate_care_plan(db_session, patient_id=patient.id, source_type="visit_record", source_id=visit.id)
    plan = confirm_care_plan(db_session, care_plan_id=plan.id, patient_id=patient.id)

    for _ in range(2):
        update_care_plan_item(
            db_session,
            item_id=plan.items[0].id,
            patient_id=patient.id,
            status_value="needs_help",
            note="预约不上",
        )

    cases = list_care_cases(db_session, hospital_id=patient.hospital_id, status_value="open")
    assert len(cases) == 1
    assert cases[0].care_plan_item_id == plan.items[0].id
    assert cases[0].care_plan_item_title == plan.items[0].title
    assert cases[0].patient_note == "预约不上"


def test_patient_acknowledgement_is_not_treated_as_task_completion(db_session):
    patient, visit = _seed_visit(db_session)
    plan = generate_care_plan(db_session, patient_id=patient.id, source_type="visit_record", source_id=visit.id)
    plan = publish_care_plan(
        db_session,
        care_plan_id=plan.id,
        hospital_id=patient.hospital_id,
        clinician_id="doctor-demo",
        clinician_note=None,
    )

    item = acknowledge_care_plan_item(db_session, item_id=plan.items[0].id, patient_id=patient.id)

    assert item.status == "pending"
    assert item.patient_acknowledged_at is not None
    assert item.follow_up_status == "monitoring"
    assert item.execution_evidence_type is None
    assert item.events[-1].event_type == "patient_acknowledged"


def test_overdue_unconfirmed_task_is_escalated_to_a_coordinator_case(db_session):
    patient, visit = _seed_visit(db_session)
    plan = generate_care_plan(db_session, patient_id=patient.id, source_type="visit_record", source_id=visit.id)
    plan = publish_care_plan(
        db_session,
        care_plan_id=plan.id,
        hospital_id=patient.hospital_id,
        clinician_id="doctor-demo",
        clinician_note=None,
    )
    item = plan.items[0]
    item.due_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
    item.next_reminder_at = datetime(2026, 7, 3, tzinfo=timezone.utc)
    item.reminder_count = 1
    db_session.commit()

    result = run_care_follow_up_cycle(db_session, now=datetime(2026, 7, 4, tzinfo=timezone.utc))
    db_session.refresh(item)

    assert result["overdue_follow_ups"] == 1
    assert result["coordinator_cases"] == 1
    assert item.follow_up_status == "escalated"
    assert item.status == "pending"
    assert list_care_cases(db_session, hospital_id=patient.hospital_id, status_value="open")[0].reason == "unconfirmed_follow_up"
