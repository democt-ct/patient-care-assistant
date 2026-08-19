"""Claim 级证据验证测试（Bounded Safety M2）。"""

from __future__ import annotations

from app.schemas.retrieval import (
    Claim,
    ClaimType,
    EvidenceItem,
    EvidencePack,
    EvidenceSourceType,
    SupportStatus,
)
from app.services.claim_validator import validate_claims
from app.services.retrieval_router import route_question
from app.services.task_contract import build_task_contract


def _claim(text: str, claim_type: ClaimType) -> Claim:
    return Claim(claim_id="claim-001", text=text, claim_type=claim_type)


def _patient_item(field: str, value: str, evidence_id: str = "ev-p1") -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        source_type="patient_profile",
        source_id="profile-1",
        record_date=None,
        field=field,
        value=value,
        evidence_kind=EvidenceSourceType.PATIENT_RECORD,
        patient_specific=True,
    )


def test_patient_fact_supported_when_bound_to_record():
    pack = EvidencePack(items=[_patient_item("allergy_history", "青霉素过敏")])
    claims = validate_claims(
        [_claim("你对青霉素过敏。", ClaimType.PATIENT_FACT)],
        pack,
    )
    assert claims[0].support_status is SupportStatus.SUPPORTED
    assert claims[0].evidence_ids == ["ev-p1"]


def test_patient_fact_insufficient_without_record():
    claims = validate_claims(
        [_claim("你目前正在服用阿司匹林。", ClaimType.PATIENT_FACT)],
        EvidencePack(),
    )
    # 无记录且论断包含证据包外的药物实体 → 判定为 UNSUPPORTED（更强）
    assert claims[0].support_status is SupportStatus.UNSUPPORTED


def test_general_knowledge_supported_with_reviewed_knowledge():
    pack = EvidencePack(
        knowledge_hits=[
            {"source_id": "k1", "content": "阿司匹林属于抗血小板药物", "evidence_kind": "reviewed_knowledge"}
        ]
    )
    claims = validate_claims(
        [_claim("阿司匹林属于抗血小板药物。", ClaimType.GENERAL_KNOWLEDGE)],
        pack,
    )
    assert claims[0].support_status is SupportStatus.SUPPORTED
    assert "k1" in claims[0].evidence_ids


def test_general_education_allows_model_knowledge_fallback():
    contract = build_task_contract(route_question("阿司匹林是什么药？"))
    claims = validate_claims(
        [_claim("阿司匹林是一种解热镇痛药。", ClaimType.GENERAL_KNOWLEDGE)],
        EvidencePack(),
        contract,
    )
    assert claims[0].support_status is SupportStatus.SUPPORTED
    assert "model_knowledge_fallback" in claims[0].notes


def test_clinical_interpretation_requires_patient_evidence():
    claims = validate_claims(
        [_claim("你的血压最近控制良好。", ClaimType.CLINICAL_INTERPRETATION)],
        EvidencePack(),
    )
    assert claims[0].support_status is SupportStatus.INSUFFICIENT
    assert "missing_patient_evidence" in claims[0].notes


def test_entity_not_in_pack_is_unsupported():
    pack = EvidencePack(items=[_patient_item("diagnosis", "原发性高血压 2级")])
    claims = validate_claims(
        [_claim("你正在服用缬沙坦。", ClaimType.PATIENT_FACT)],
        pack,
    )
    assert claims[0].support_status is SupportStatus.UNSUPPORTED


def test_negated_safety_warning_is_supported():
    claims = validate_claims(
        [_claim("你不能自行停药，请咨询医生。", ClaimType.RECOMMENDATION)],
        EvidencePack(),
    )
    assert claims[0].support_status is SupportStatus.SUPPORTED


def test_evidence_conflict_marks_claims_conflict():
    pack = EvidencePack(
        items=[
            _patient_item("allergy_history", "青霉素过敏", evidence_id="ev-a"),
            _patient_item("allergy_history", "无药物过敏", evidence_id="ev-b"),
        ]
    )
    claims = validate_claims(
        [_claim("你对青霉素过敏。", ClaimType.PATIENT_FACT)],
        pack,
        evidence_check=__import__(
            "app.schemas.retrieval",
            fromlist=["EvidenceCheck"],
        ).EvidenceCheck(
            status="conflict",
            coverage=0.5,
            missing_facts=[],
            conflicts=[
                {
                    "field": "allergy_history",
                    "values": [
                        {"value": "青霉素过敏", "source_id": "ev-a", "record_date": None},
                        {"value": "无药物过敏", "source_id": "ev-b", "record_date": None},
                    ],
                    "note": "冲突",
                }
            ],
            decision="clarify",
        ),
    )
    assert claims[0].support_status is SupportStatus.CONFLICT
