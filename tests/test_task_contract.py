"""Task Contract 注册表测试（Bounded Safety M1）。"""

from __future__ import annotations

from app.schemas.retrieval import (
    ClaimType,
    EvidenceSourceType,
    TaskType,
)
from app.services.retrieval_router import route_question
from app.services.task_contract import (
    build_task_contract,
    canonical_task,
    contract_summary_text,
)


def test_canonical_task_maps_legacy_values():
    assert canonical_task(TaskType.FACT_VERIFICATION) is TaskType.PATIENT_FACT_LOOKUP
    assert canonical_task(TaskType.MEDICATION_ALLERGY_CHECK) is TaskType.MEDICATION_RECONCILIATION
    assert canonical_task(TaskType.GENERAL_HEALTH_EDUCATION) is TaskType.GENERAL_MEDICAL_EDUCATION
    assert canonical_task(TaskType.RISK_TRIAGE) is TaskType.EMERGENCY_TRIAGE
    assert canonical_task(TaskType.PATIENT_FACT_LOOKUP) is TaskType.PATIENT_FACT_LOOKUP


def test_canonical_task_accepts_string_values():
    assert canonical_task("fact_verification") is TaskType.PATIENT_FACT_LOOKUP
    assert canonical_task("medication_education") is TaskType.MEDICATION_EDUCATION


def test_build_task_contract_merges_route_boundaries():
    route = route_question("我青霉素过敏，能用头孢吗？")
    contract = build_task_contract(route)
    assert contract.task_type is TaskType.MEDICATION_RECONCILIATION
    assert "dose_change" in contract.forbidden_actions
    assert "conclude_safety" in contract.forbidden_actions
    assert EvidenceSourceType.PATIENT_RECORD in contract.allowed_evidence_sources
    assert contract.requires_clinician_oversight is True


def test_education_contract_allows_limited_model_fallback():
    contract = build_task_contract(route_question("阿莫西林是治什么的？"))
    assert contract.task_type is TaskType.MEDICATION_EDUCATION
    assert contract.fallback_strategy == "model_knowledge_limited"
    assert contract.required_patient_fields == []
    assert contract.allowed_claim_types == [ClaimType.GENERAL_KNOWLEDGE]


def test_dosing_contract_requires_oversight_and_trusted_source():
    contract = build_task_contract(route_question("缬沙坦我应该吃几片？"))
    assert contract.task_type is TaskType.MEDICATION_DOSING
    assert contract.requires_clinician_oversight is True
    assert contract.fallback_strategy == "refuse"
    required = {
        req.evidence_type for req in contract.evidence_requirements if req.required
    }
    assert EvidenceSourceType.PATIENT_RECORD in required
    assert EvidenceSourceType.TRUSTED_MEDICAL_SOURCE in required


def test_contract_summary_text_injects_constraints():
    contract = build_task_contract(route_question("阿司匹林是什么药？"))
    text = contract_summary_text(contract)
    assert "任务类型" in text
    assert "medication_education" in text
    assert "禁止动作" in text


def test_default_contract_for_none_route_is_general_education():
    contract = build_task_contract(None)
    assert contract.task_type is TaskType.GENERAL_MEDICAL_EDUCATION


def test_legacy_route_for_task_returns_canonical():
    from app.services.retrieval_router import route_for_task

    route = route_for_task(TaskType.FACT_VERIFICATION)
    assert route.task is TaskType.PATIENT_FACT_LOOKUP
