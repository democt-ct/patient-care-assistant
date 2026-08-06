"""证据策略（充分性 / 缺失 / 冲突 / 高风险）的确定性测试。"""

from app.schemas.retrieval import (
    EvidenceDecision,
    EvidenceItem,
    EvidencePack,
    EvidenceStatus,
    RetrievalRoute,
    RetrievalSource,
    TaskType,
)
from app.services.evidence_policy import detect_conflicts, evaluate_evidence


def _item(field, value, source_id="record-001", record_date="2026-07-01", source_type="visit_record"):
    return EvidenceItem(
        evidence_id=f"ev-{source_id}-{field}",
        source_type=source_type,
        source_id=source_id,
        record_date=record_date,
        field=field,
        value=value,
    )


def _med_route():
    return RetrievalRoute(
        task=TaskType.MEDICATION_ALLERGY_CHECK,
        sources=[RetrievalSource.STRUCTURED_PATIENT_FACT],
        required_facts=["allergy_history", "current_medications"],
        forbidden_actions=["dose_change", "stop_medication"],
        max_retrieval_rounds=1,
    )


def test_sufficient_evidence_generates():
    pack = EvidencePack(items=[
        _item("allergy_history", "青霉素过敏", source_id="profile-1", source_type="patient_profile"),
        _item("medications", "缬沙坦 160mg qd", source_id="record-1"),
    ])
    check = evaluate_evidence(pack, _med_route())

    assert check.status is EvidenceStatus.SUFFICIENT
    assert check.decision is EvidenceDecision.GENERATE
    assert check.coverage == 1.0


def test_missing_facts_triggers_one_bounded_retry_then_clarify():
    pack = EvidencePack(items=[_item("allergy_history", "无已知药物过敏", source_id="profile-1", source_type="patient_profile")])
    route = _med_route()

    first = evaluate_evidence(pack, route, attempt=1, max_attempts=2)
    second = evaluate_evidence(pack, route, attempt=2, max_attempts=2)

    assert first.status is EvidenceStatus.MISSING
    assert first.decision is EvidenceDecision.RETRIEVE_AGAIN
    assert first.missing_facts == ["current_medications"]
    assert second.decision is EvidenceDecision.CLARIFY
    assert second.attempt == 2


def test_conflict_detected_and_never_guesses_latest():
    pack = EvidencePack(items=[
        _item("allergy_history", "青霉素过敏", source_id="profile-1", source_type="patient_profile", record_date=None),
        _item("allergy_history", "无药物过敏", source_id="record-2", source_type="visit_record", record_date=None),
    ])

    conflicts = detect_conflicts(pack)
    assert len(conflicts) == 1
    assert conflicts[0].field == "allergy_history"
    assert {value["source_id"] for value in conflicts[0].values} == {"profile-1", "record-2"}

    check = evaluate_evidence(pack, _med_route())
    assert check.status is EvidenceStatus.CONFLICT
    assert check.decision is EvidenceDecision.CLARIFY


def test_cross_date_diagnosis_change_is_not_a_conflict():
    """不同就诊日期的诊断变化是病情进展，不是来源冲突。"""
    pack = EvidencePack(items=[
        _item("diagnosis", "高血压 2级（高危）", source_id="record-1", record_date="2025-09-15"),
        _item("diagnosis", "高血压 2级，药物控制可", source_id="record-2", record_date="2025-12-01"),
    ])
    assert detect_conflicts(pack) == []


def test_allergy_with_caution_marker_is_ambiguity_conflict():
    """主档同时出现过敏与慎用（如青霉素过敏 + 头孢慎用）需医生确认。"""
    pack = EvidencePack(items=[
        _item(
            "allergy_history",
            "青霉素过敏（皮疹）；头孢类慎用（既往轻度皮疹）",
            source_id="profile-1",
            source_type="patient_profile",
            record_date=None,
        ),
    ])
    check = evaluate_evidence(pack, _med_route())

    assert check.status is EvidenceStatus.CONFLICT
    assert check.decision is EvidenceDecision.CLARIFY
    assert any("慎用" in conflict.note for conflict in check.conflicts)


def test_allergy_ambiguity_only_for_medication_questions():
    """无关问题（如问医生是谁、问当前用药）不得因主档含“慎用”被判冲突。"""
    pack = EvidencePack(items=[
        _item(
            "allergy_history",
            "青霉素过敏（皮疹）；头孢类慎用（既往轻度皮疹）",
            source_id="profile-1",
            source_type="patient_profile",
            record_date=None,
        ),
    ])
    check = evaluate_evidence(pack, _med_route(), question="我最近一次看病的医生是谁？")
    check_meds = evaluate_evidence(pack, _med_route(), question="我吃什么药控制血压？")

    assert check.conflicts == []
    assert check.status in (EvidenceStatus.MISSING, EvidenceStatus.SUFFICIENT)
    assert check_meds.conflicts == []


def test_medication_with_zero_evidence_is_high_risk_refusal():
    pack = EvidencePack()
    check = evaluate_evidence(pack, _med_route())

    assert check.status is EvidenceStatus.HIGH_RISK
    assert check.decision is EvidenceDecision.REFUSE


def test_education_task_with_zero_evidence_is_not_refused():
    """健康教育没有必需事实，零证据不得触发高危拒答（避免过度拒答）。"""
    route = RetrievalRoute(
        task=TaskType.GENERAL_HEALTH_EDUCATION,
        sources=[RetrievalSource.CLINICAL_KNOWLEDGE],
        required_facts=[],
        forbidden_actions=["individualized_advice"],
        max_retrieval_rounds=1,
    )
    check = evaluate_evidence(EvidencePack(), route)

    assert check.status is EvidenceStatus.SUFFICIENT
    assert check.decision is EvidenceDecision.GENERATE


def test_medication_dose_change_is_not_a_conflict():
    """不同日期的用药调整属于纵向变化，不自动判为冲突。"""
    pack = EvidencePack(items=[
        _item("medications", "缬沙坦 80mg qd", source_id="record-1", record_date="2025-09-15"),
        _item("medications", "缬沙坦 160mg qd", source_id="record-2", record_date="2025-12-01"),
    ])
    assert detect_conflicts(pack) == []
