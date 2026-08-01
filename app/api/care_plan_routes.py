import os

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.care_plan import (
    CareCaseRead,
    CareCaseResolveRequest,
    CarePlanGenerateRequest,
    CarePlanItemRead,
    CarePlanItemStatusUpdate,
    CarePlanPublishRequest,
    CarePlanRead,
)
from app.services.care_plan_service import (
    acknowledge_care_case,
    acknowledge_care_plan_item,
    confirm_care_plan,
    generate_care_plan,
    get_care_plan,
    list_care_cases,
    list_care_plan_review_queue,
    list_care_plans,
    resolve_care_case,
    publish_care_plan,
    update_care_plan_item,
)


router = APIRouter(prefix="/api/v1/care-plans", tags=["照护计划（care-plans）"])


def require_care_coordinator_access(
    x_care_coordinator_key: str | None = Header(default=None),
):
    """Keep hospital work queues separate from patient-facing token access."""
    configured_key = os.getenv("CARE_COORDINATOR_API_KEY", "").strip()
    is_production = os.getenv("PATIENT_AGENT_ENV", "").lower() in ("production", "prod")
    if is_production and not configured_key:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Coordinator access is not configured")
    if configured_key and x_care_coordinator_key != configured_key:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid coordinator access key")


def require_clinician_access(
    x_clinician_key: str | None = Header(default=None),
):
    configured_key = os.getenv("CLINICIAN_API_KEY", "").strip()
    is_production = os.getenv("PATIENT_AGENT_ENV", "").lower() in ("production", "prod")
    if is_production and not configured_key:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Clinician access is not configured")
    if configured_key and x_clinician_key != configured_key:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid clinician access key")


@router.post("/generate", response_model=CarePlanRead, summary="从已有病历生成待确认照护计划")
def post_generate_care_plan(
    payload: CarePlanGenerateRequest,
    patient_id: str = Query(...),
    db: Session = Depends(get_db),
):
    if payload.patient_id != patient_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="patient_id does not match request body")
    return generate_care_plan(
        db,
        patient_id=payload.patient_id,
        source_type=payload.source_type,
        source_id=payload.source_id,
    )


@router.get("", response_model=list[CarePlanRead], summary="读取患者照护计划")
def get_care_plans(
    patient_id: str = Query(...),
    include_drafts: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    return list_care_plans(db, patient_id=patient_id, include_drafts=include_drafts)


@router.get("/review-queue", response_model=list[CarePlanRead], summary="读取医生待审核照护计划")
def get_care_plan_review_queue(
    hospital_id: str = Query(...),
    _: None = Depends(require_clinician_access),
    db: Session = Depends(get_db),
):
    return list_care_plan_review_queue(db, hospital_id=hospital_id)


@router.post("/{care_plan_id}/publish", response_model=CarePlanRead, summary="医生审核并发布照护计划")
def post_publish_care_plan(
    care_plan_id: str,
    payload: CarePlanPublishRequest,
    hospital_id: str = Query(...),
    _: None = Depends(require_clinician_access),
    db: Session = Depends(get_db),
):
    return publish_care_plan(
        db,
        care_plan_id=care_plan_id,
        hospital_id=hospital_id,
        clinician_id=payload.clinician_id,
        clinician_note=payload.clinician_note,
    )


@router.get("/{care_plan_id}", response_model=CarePlanRead, summary="读取照护计划详情")
def get_care_plan_detail(care_plan_id: str, patient_id: str = Query(...), db: Session = Depends(get_db)):
    return get_care_plan(db, care_plan_id, patient_id=patient_id)


@router.post("/{care_plan_id}/confirm", response_model=CarePlanRead, summary="确认照护计划")
def post_confirm_care_plan(care_plan_id: str, patient_id: str = Query(...), db: Session = Depends(get_db)):
    return confirm_care_plan(db, care_plan_id=care_plan_id, patient_id=patient_id)


@router.patch("/items/{item_id}", response_model=CarePlanItemRead, summary="更新待办状态")
def patch_care_plan_item(
    item_id: str,
    payload: CarePlanItemStatusUpdate,
    patient_id: str = Query(...),
    db: Session = Depends(get_db),
):
    if payload.patient_id != patient_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="patient_id does not match request body")
    return update_care_plan_item(
        db,
        item_id=item_id,
        patient_id=payload.patient_id,
        status_value=payload.status,
        note=payload.note,
        snoozed_until=payload.snoozed_until,
    )


@router.post("/items/{item_id}/acknowledge", response_model=CarePlanItemRead, summary="患者确认已知晓待办")
def post_acknowledge_care_plan_item(
    item_id: str,
    patient_id: str = Query(...),
    db: Session = Depends(get_db),
):
    return acknowledge_care_plan_item(db, item_id=item_id, patient_id=patient_id)


@router.get("/cases/queue", response_model=list[CareCaseRead], summary="读取医院照护协作队列")
def get_care_case_queue(
    hospital_id: str = Query(...),
    status_value: str | None = Query(default=None, alias="status"),
    assignee_id: str | None = Query(default=None),
    _: None = Depends(require_care_coordinator_access),
    db: Session = Depends(get_db),
):
    return list_care_cases(db, hospital_id=hospital_id, status_value=status_value, assignee_id=assignee_id)


@router.post("/cases/{case_id}/acknowledge", response_model=CareCaseRead, summary="确认接手照护协作单")
def post_acknowledge_care_case(
    case_id: str,
    payload: CareCaseResolveRequest,
    hospital_id: str = Query(...),
    _: None = Depends(require_care_coordinator_access),
    db: Session = Depends(get_db),
):
    return acknowledge_care_case(
        db,
        case_id=case_id,
        hospital_id=hospital_id,
        assignee_id=payload.assignee_id,
        coordinator_note=payload.coordinator_note,
    )


@router.post("/cases/{case_id}/resolve", response_model=CareCaseRead, summary="解决照护协作单")
def post_resolve_care_case(
    case_id: str,
    payload: CareCaseResolveRequest,
    hospital_id: str = Query(...),
    _: None = Depends(require_care_coordinator_access),
    db: Session = Depends(get_db),
):
    return resolve_care_case(
        db,
        case_id=case_id,
        hospital_id=hospital_id,
        assignee_id=payload.assignee_id,
        coordinator_note=payload.coordinator_note,
    )
