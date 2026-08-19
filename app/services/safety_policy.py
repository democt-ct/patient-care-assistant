"""安全策略执行与最终决策（Bounded Safety）。

确定性 Safety Policy 优先级高于 LLM Judge：
- 命中禁止动作（剂量/停药/换药/处方）的 RECOMMENDATION/ACTION Claim → PROHIBITED；
- 即使证据充分，禁止动作仍然不放行（有证据 ≠ 有权限执行）；
- Final Decision 统一为 PASS / PARTIAL / CLARIFY / REFUSE / ESCALATE；
- PARTIAL 时按「替换 + 安全提示」裁剪回答，全部写入 notes/trace。
"""

from __future__ import annotations

import re
from typing import Optional

from app.schemas.retrieval import (
    Claim,
    ClaimType,
    EvidenceCheck,
    EvidenceStatus,
    FinalDecision,
    SafetyStatus,
    SupportStatus,
    TaskContract,
    TaskType,
)
from app.services.claim_extraction import _split_sentences

_DOSE_ACTION_PATTERNS = (
    r"停药|停用|减量|加量|换药|替换|减药|加药",
    r"吃几片|吃多少|用多少|剂量|毫克|微克|mg\b",
    r"开药|处方|给我开|开个",
)

_DRUG_USE_PATTERNS = (
    r"(?:服用|使用|吃).{0,6}(?:阿司匹林|布洛芬|缬沙坦|氨氯地平|二甲双胍|格列美脲|"
    r"奥美拉唑|头孢|青霉素|磺胺|硝酸甘油)",
)

_ALL_ACTION_PATTERNS = (*_DOSE_ACTION_PATTERNS, *_DRUG_USE_PATTERNS)

_CLINICAL_DEFER_MARKERS = (
    "医生指导", "药师指导", "指导下", "遵医嘱", "咨询医生", "咨询药师",
)

_QUESTION_FORBIDDEN_PATTERNS = (
    r"(?:可以|能不能|能否|应该|需要|是否|要不要).{0,10}(?:停药|停用|减量|加量|换药|换|停)",
    r"吃几片|吃多少|用多少|剂量|毫克|微克|mg\b|给我开|开个|处方",
)

_NEGATION_PREFIX = re.compile(r"(?:不|别|勿|禁|避免)")


def _action_verb_matched(text: str, patterns=_ALL_ACTION_PATTERNS) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def _has_negation_before_action(text: str) -> bool:
    for pattern in _ALL_ACTION_PATTERNS:
        for match in re.finditer(pattern, text):
            before = text[max(0, match.start() - 4) : match.start()]
            if _NEGATION_PREFIX.search(before):
                return True
    return False


def _question_requests_forbidden(question: str) -> bool:
    text = question or ""
    return any(re.search(pattern, text) for pattern in _QUESTION_FORBIDDEN_PATTERNS)


def enforce_claim_safety(
    claims: list[Claim],
    contract: Optional[TaskContract] = None,
) -> list[Claim]:
    """对 RECOMMENDATION / ACTION 论断执行确定性安全策略。"""
    for claim in claims:
        if claim.claim_type not in (ClaimType.RECOMMENDATION, ClaimType.ACTION):
            continue
        if _has_negation_before_action(claim.text or ""):
            claim.safety_status = SafetyStatus.ALLOWED
            claim.notes.append("negated_safety_warning")
            continue
        if _action_verb_matched(claim.text or "", _DOSE_ACTION_PATTERNS):
            claim.safety_status = SafetyStatus.PROHIBITED
            claim.support_status = SupportStatus.UNSUPPORTED
            claim.notes.append("prohibited_action_by_safety_policy")
        elif _action_verb_matched(claim.text or "", _DRUG_USE_PATTERNS):
            if any(marker in (claim.text or "") for marker in _CLINICAL_DEFER_MARKERS):
                claim.safety_status = SafetyStatus.RESTRICTED
                claim.notes.append("deferred_to_clinician")
            else:
                claim.safety_status = SafetyStatus.PROHIBITED
                claim.support_status = SupportStatus.UNSUPPORTED
                claim.notes.append("prohibited_action_by_safety_policy")
        elif contract is not None and contract.requires_clinician_oversight:
            claim.safety_status = SafetyStatus.NEEDS_OVERSIGHT
        else:
            claim.safety_status = SafetyStatus.ALLOWED
    return claims


def decide_final(
    claims: list[Claim],
    evidence_check: Optional[EvidenceCheck] = None,
    contract: Optional[TaskContract] = None,
    question: str = "",
    *,
    deterministic_direct: bool = False,
) -> tuple[FinalDecision, list[str]]:
    """汇总证据验证 + 安全策略，产出最终决策与原因。"""
    reasons: list[str] = []
    if contract is not None and contract.task_type is TaskType.EMERGENCY_TRIAGE:
        return FinalDecision.ESCALATE, ["emergency_triage_task"]
    if evidence_check is not None:
        if evidence_check.status is EvidenceStatus.HIGH_RISK:
            return FinalDecision.REFUSE, ["evidence_high_risk_no_evidence"]
        if evidence_check.status is EvidenceStatus.CONFLICT:
            return FinalDecision.CLARIFY, ["evidence_conflict"]

    prohibited = [
        claim for claim in claims if claim.safety_status is SafetyStatus.PROHIBITED
    ]
    if prohibited:
        if _question_requests_forbidden(question):
            return FinalDecision.REFUSE, ["prohibited_action_requested_by_user"]
        reasons.append(
            "prohibited_claims:" + ",".join(claim.claim_id for claim in prohibited[:3])
        )
        return FinalDecision.PARTIAL, reasons

    conflicts = [
        claim for claim in claims if claim.support_status is SupportStatus.CONFLICT
    ]
    if conflicts:
        return FinalDecision.CLARIFY, ["claim_evidence_conflict"]

    patient_insufficient = [
        claim
        for claim in claims
        if claim.support_status in (SupportStatus.INSUFFICIENT, SupportStatus.UNSUPPORTED)
        and claim.claim_type in (ClaimType.PATIENT_FACT, ClaimType.CLINICAL_INTERPRETATION)
    ]
    if patient_insufficient:
        has_supported = any(
            claim.support_status is SupportStatus.SUPPORTED
            and claim.safety_status is not SafetyStatus.PROHIBITED
            for claim in claims
        )
        if not has_supported:
            return (
                FinalDecision.CLARIFY,
                [
                    "missing_patient_evidence:"
                    + ",".join(claim.claim_id for claim in patient_insufficient[:3])
                ],
            )
        return (
            FinalDecision.PARTIAL,
            [
                "missing_patient_evidence:"
                + ",".join(claim.claim_id for claim in patient_insufficient[:3])
            ],
        )

    if (
        evidence_check is not None
        and evidence_check.status is EvidenceStatus.MISSING
        and evidence_check.missing_facts
    ):
        return (
            FinalDecision.CLARIFY,
            [f"missing_facts:{','.join(evidence_check.missing_facts[:3])}"],
        )

    insufficient = [
        claim
        for claim in claims
        if claim.support_status in (SupportStatus.INSUFFICIENT, SupportStatus.UNSUPPORTED)
    ]
    if insufficient:
        if contract is not None and contract.requires_clinician_oversight and contract.task_type in (
            TaskType.MEDICATION_DOSING,
            TaskType.CLINICAL_DECISION,
        ):
            return FinalDecision.REFUSE, ["insufficient_evidence_high_risk_task"]
        return (
            FinalDecision.PARTIAL,
            ["insufficient_claims:" + ",".join(claim.claim_id for claim in insufficient[:3])],
        )

    return FinalDecision.PASS, ["all_claims_supported"]


def prune_answer(
    answer: str,
    claims: list[Claim],
    decision: FinalDecision,
    reasons: list[str],
) -> tuple[str, list[str]]:
    """PARTIAL 时按「替换 + 安全提示」裁剪回答；其余决策不改动回答。"""
    notes: list[str] = []
    if decision is not FinalDecision.PARTIAL:
        return answer, notes
    pruned = [
        claim
        for claim in claims
        if claim.support_status in (SupportStatus.INSUFFICIENT, SupportStatus.UNSUPPORTED)
        or claim.safety_status is SafetyStatus.PROHIBITED
    ]
    if not pruned:
        return answer, notes

    sentences = _split_sentences(answer or "")
    replaced: dict[int, str] = {}
    for claim in pruned:
        text = claim.text or ""
        for index, sentence in enumerate(sentences):
            if text and (text in sentence or sentence in text):
                if claim.safety_status is SafetyStatus.PROHIBITED:
                    replaced[index] = ""
                    notes.append(f"removed_prohibited:{claim.claim_id}")
                else:
                    replaced[index] = "（当前病历无法确认）"
                    notes.append(f"replaced_insufficient:{claim.claim_id}")
                break
    if not replaced:
        return answer, notes

    rebuilt = "".join(replaced.get(index, sentence) for index, sentence in enumerate(sentences))
    if any(claim.safety_status is SafetyStatus.PROHIBITED for claim in pruned):
        rebuilt = (rebuilt.rstrip() + " 已移除超出权限或无法核验的建议，请以医生或药师意见为准。").strip()
        notes.append("safety_note_appended")
    return rebuilt, notes
