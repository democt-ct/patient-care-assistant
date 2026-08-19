"""安全策略执行与最终决策测试（Bounded Safety M2）。"""

from __future__ import annotations

from app.schemas.retrieval import (
    Claim,
    ClaimType,
    EvidenceCheck,
    EvidenceDecision,
    EvidenceStatus,
    FinalDecision,
    SafetyStatus,
    SupportStatus,
)
from app.services.retrieval_router import route_question
from app.services.safety_policy import (
    decide_final,
    enforce_claim_safety,
    prune_answer,
)
from app.services.task_contract import build_task_contract


def _claim(text: str, claim_type: ClaimType, status: SupportStatus = SupportStatus.SUPPORTED) -> Claim:
    return Claim(
        claim_id=f"claim-{text[:4]}",
        text=text,
        claim_type=claim_type,
        support_status=status,
    )


def test_dose_change_is_prohibited_even_with_evidence():
    contract = build_task_contract(route_question("缬沙坦我应该吃几片？"))
    claims = enforce_claim_safety(
        [_claim("你应该把缬沙坦剂量减少一半。", ClaimType.RECOMMENDATION)],
        contract,
    )
    assert claims[0].safety_status is SafetyStatus.PROHIBITED
    assert claims[0].support_status is SupportStatus.UNSUPPORTED


def test_prohibited_request_by_user_yields_refuse():
    contract = build_task_contract(route_question("缬沙坦我应该吃几片？"))
    claims = enforce_claim_safety(
        [_claim("你应该把缬沙坦剂量减少一半。", ClaimType.RECOMMENDATION)],
        contract,
    )
    decision, reasons = decide_final(
        claims,
        contract=contract,
        question="缬沙坦我应该吃几片？",
    )
    assert decision is FinalDecision.REFUSE
    assert any("prohibited" in reason for reason in reasons)


def test_negated_warning_is_allowed():
    contract = build_task_contract(route_question("高血压注意什么？"))
    claims = enforce_claim_safety(
        [_claim("不要自行停药，请咨询医生。", ClaimType.RECOMMENDATION)],
        contract,
    )
    assert claims[0].safety_status is SafetyStatus.ALLOWED
    assert "negated_safety_warning" in claims[0].notes


def test_mixed_claims_produce_partial_and_prune():
    contract = build_task_contract(route_question("我目前在吃阿司匹林，应该注意什么？"))
    claims = [
        _claim("阿司匹林属于抗血小板药物。", ClaimType.GENERAL_KNOWLEDGE),
        _claim("你目前正在服用阿司匹林。", ClaimType.PATIENT_FACT, SupportStatus.INSUFFICIENT),
        _claim("你应该把阿司匹林剂量减少一半。", ClaimType.RECOMMENDATION, SupportStatus.UNSUPPORTED),
    ]
    claims = enforce_claim_safety(claims, contract)
    decision, reasons = decide_final(
        claims,
        contract=contract,
        question="我目前在吃阿司匹林，应该注意什么？",
    )
    assert decision is FinalDecision.PARTIAL
    answer, notes = prune_answer(
        "阿司匹林属于抗血小板药物。你目前正在服用阿司匹林。你应该把阿司匹林剂量减少一半。",
        claims,
        decision,
        reasons,
    )
    assert "阿司匹林属于抗血小板药物" in answer
    assert "当前病历无法确认" in answer
    assert "剂量减少一半" not in answer
    assert any("removed_prohibited" in note for note in notes)


def test_emergency_task_escalates():
    contract = build_task_contract(route_question("我现在胸痛、呼吸困难怎么办？"))
    decision, reasons = decide_final([], contract=contract, question="我现在胸痛、呼吸困难怎么办？")
    assert decision is FinalDecision.ESCALATE


def test_evidence_conflict_yields_clarify():
    check = EvidenceCheck(
        status=EvidenceStatus.CONFLICT,
        coverage=0.5,
        missing_facts=[],
        conflicts=[],
        decision=EvidenceDecision.CLARIFY,
    )
    decision, _ = decide_final([], evidence_check=check)
    assert decision is FinalDecision.CLARIFY


def test_all_supported_yields_pass():
    contract = build_task_contract(route_question("阿司匹林是什么药？"))
    claims = enforce_claim_safety(
        [_claim("阿司匹林是一种解热镇痛药。", ClaimType.GENERAL_KNOWLEDGE)],
        contract,
    )
    decision, _ = decide_final(claims, contract=contract, question="阿司匹林是什么药？")
    assert decision is FinalDecision.PASS
