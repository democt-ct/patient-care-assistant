"""检索路由与 Agent 输出契约的 Schema 回归测试。"""

import pytest
from pydantic import ValidationError

from app.config.evaluation_cases import EVALUATION_CASES
from app.schemas.retrieval import (
    AgentOutputContract,
    EvidenceCheck,
    EvidenceConflict,
    EvidenceDecision,
    EvidenceItem,
    EvidencePack,
    EvidenceReviewStatus,
    EvidenceSource,
    EvidenceStatus,
    NextAction,
    RetrievalRoute,
    RetrievalSource,
    RiskLevel,
    TaskType,
)


def test_task_enum_values_match_evaluation_cases():
    """阶段 0 冻结的评估用例必须与阶段 A 的任务枚举一致。"""
    valid_tasks = {task.value for task in TaskType}
    valid_scenarios = {"fact_verification", "medication_allergy", "risk_triage", "evidence_conflict"}
    assert len(EVALUATION_CASES) >= 40
    for case in EVALUATION_CASES:
        assert case["task"] in valid_tasks, case["id"]
        assert case["split"] in {"dev", "test"}, case["id"]
        assert case.get("golden_scenario") in valid_scenarios or case.get("golden_scenario") is None, case["id"]


def test_retrieval_route_roundtrip():
    route = RetrievalRoute(
        task=TaskType.MEDICATION_ALLERGY_CHECK,
        sources=[RetrievalSource.STRUCTURED_PATIENT_FACT, RetrievalSource.CLINICAL_KNOWLEDGE],
        required_facts=["allergy_history", "current_medications"],
        forbidden_actions=["dose_change", "stop_medication"],
        max_retrieval_rounds=1,
        route_reason="medication_or_allergy_keywords",
    )

    restored = RetrievalRoute.model_validate(route.model_dump(mode="json"))

    assert restored == route
    assert restored.max_retrieval_rounds <= 2


def test_evidence_item_roundtrip_and_defaults():
    item = EvidenceItem(
        evidence_id="ev-001",
        source_type="visit_record",
        source_id="hospital-record-001",
        record_date="2026-07-01",
        field="diagnosis",
        value="原发性高血压 2级",
    )

    restored = EvidenceItem.model_validate(item.model_dump(mode="json"))

    assert restored == item
    assert restored.version == "current"
    assert restored.review_status is EvidenceReviewStatus.REVIEWED


def test_evidence_pack_and_check_roundtrip():
    source = EvidenceSource(source_id="hospital-record-001", record_type="visit_record", record_date="2026-07-01")
    pack = EvidencePack(
        items=[EvidenceItem(
            evidence_id="ev-001",
            source_type="visit_record",
            source_id="hospital-record-001",
            record_date="2026-07-01",
            field="allergy_history",
            value="青霉素过敏",
        )],
        sources=[source],
        missing_facts=["current_medications"],
        conflicts=[],
        coverage=0.6,
    )
    check = EvidenceCheck(
        status=EvidenceStatus.MISSING,
        coverage=0.6,
        missing_facts=["current_medications"],
        conflicts=[],
        decision=EvidenceDecision.RETRIEVE_AGAIN,
        attempt=1,
        max_attempts=2,
    )

    restored_pack = EvidencePack.model_validate(pack.model_dump(mode="json"))
    restored_check = EvidenceCheck.model_validate(check.model_dump(mode="json"))

    assert restored_pack == pack
    assert restored_check == check


def test_evidence_conflict_carries_both_sources():
    conflict = EvidenceConflict(
        field="current_medications",
        values=[
            {"value": "阿司匹林", "source_id": "record-001", "record_date": "2026-06-01"},
            {"value": "未用药", "source_id": "record-002", "record_date": "2026-07-01"},
        ],
        note="两条记录不一致",
    )

    restored = EvidenceConflict.model_validate(conflict.model_dump(mode="json"))

    assert len(restored.values) == 2
    assert {item["record_date"] for item in restored.values} == {"2026-06-01", "2026-07-01"}


def test_output_contract_defaults_are_safe():
    contract = AgentOutputContract(answer="请核对原始记录。")

    assert contract.risk_level is RiskLevel.ROUTINE
    assert contract.next_action is NextAction.VIEW_RECORDS
    assert contract.agent_trajectory == []


def test_invalid_task_enum_rejected():
    with pytest.raises(ValueError):
        TaskType("not_a_task")

    with pytest.raises(ValidationError):
        RetrievalRoute.model_validate({
            "task": "not_a_task",
            "sources": [RetrievalSource.NO_RETRIEVAL.value],
            "max_retrieval_rounds": 3,
        })
