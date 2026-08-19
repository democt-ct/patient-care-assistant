"""Claim 级证据验证（Bounded Safety）—— 确定性为主，LLM Judge 语义收紧。

每条论断按 claim_type + Task Contract 的 EvidenceRequirement 判定
SUPPORTED / PARTIALLY_SUPPORTED / INSUFFICIENT / CONFLICT / UNSUPPORTED，
并完成 evidence_ids 绑定。LLM Judge 只允许收紧结论，不允许放行。
"""

from __future__ import annotations

import re
from typing import Optional

from app.schemas.retrieval import (
    Claim,
    ClaimType,
    EvidenceCheck,
    EvidenceJudgeResult,
    EvidenceJudgeVerdict,
    EvidencePack,
    EvidenceSourceType,
    SupportStatus,
    TaskContract,
    TaskType,
)
from app.services.citation_validator import _DATE_RE, _DOSE_RE, _KNOWN_DRUGS
from app.services.safety_policy import _has_negation_before_action

_FIELD_LABELS = {
    "allergy_history": ("过敏", "过敏史"),
    "current_medications": ("用药", "服用", "药物", "药"),
    "diagnosis": ("诊断", "确诊"),
    "visit_records": ("就诊", "看诊", "复诊"),
    "surgeries": ("手术", "置换", "切除"),
    "physician": ("医生",),
    "emergency_contact": ("联系人",),
    "timeline_records": ("上次", "最近", "日期"),
    "report_facts": ("指标", "报告", "检查"),
}

_GENERIC_CARE_MARKERS = (
    "就医", "拨打 120", "急诊", "热线", "复诊", "监测", "休息", "饮食",
    "运动", "低盐", "多喝水", "测量", "咨询医生", "咨询药师", "遵医嘱",
    "医生指导", "药师指导", "指导下",
)

_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9]{2,}")


def _content_tokens(content: str) -> set[str]:
    """返回内容中的整词 token 与 2-gram（用于 paraphrase 语义绑定）。"""
    runs = [token for token in _TOKEN_RE.findall(content or "") if len(token) >= 2]
    tokens = set(runs)
    for run in runs:
        if len(run) >= 3:
            tokens.update(run[index : index + 2] for index in range(len(run) - 1))
    return tokens


def _bind_patient_evidence(claim: Claim, pack: EvidencePack) -> list[str]:
    text = claim.text or ""
    bound: list[str] = []
    for item in pack.patient_evidence():
        labels = _FIELD_LABELS.get(item.field, ())
        if any(label in text for label in labels):
            bound.append(item.evidence_id)
            continue
        if any(
            drug in item.value and drug in text
            for drug in _KNOWN_DRUGS
        ):
            bound.append(item.evidence_id)
            continue
        value_tokens = _content_tokens(item.value)
        if value_tokens and value_tokens & _content_tokens(text):
            bound.append(item.evidence_id)
    return bound


def _bind_knowledge(claim: Claim, pack: EvidencePack) -> tuple[list[str], bool, bool]:
    """绑定知识证据，返回 (evidence_ids, has_reviewed_or_trusted, has_any)。"""
    text = claim.text or ""
    claim_tokens = _content_tokens(text)
    claim_drugs = {drug for drug in _KNOWN_DRUGS if drug in text}
    bound: list[str] = []
    has_reviewed_or_trusted = False
    for hit in pack.knowledge_hits:
        kind = hit.get("evidence_kind", EvidenceSourceType.REVIEWED_KNOWLEDGE.value)
        content = str(hit.get("content") or "")
        hit_tokens = _content_tokens(content)
        matched = bool(claim_tokens & hit_tokens)
        if not matched and claim_drugs:
            matched = any(drug in content for drug in claim_drugs)
        if matched:
            bound.append(str(hit.get("source_id") or hit.get("content") or "")[:64])
            if kind in (
                EvidenceSourceType.REVIEWED_KNOWLEDGE.value,
                EvidenceSourceType.TRUSTED_MEDICAL_SOURCE.value,
            ):
                has_reviewed_or_trusted = True
    return bound, has_reviewed_or_trusted, bool(pack.knowledge_hits)


def _entity_unsupported(claim: Claim, pack: EvidencePack) -> list[str]:
    """按实体粒度核对：论断中的药物/日期/剂量必须能在证据包中找到。"""
    text = claim.text or ""
    pack_text = " ".join(
        [item.value for item in pack.items]
        + [item.record_date or "" for item in pack.items if item.record_date]
        + [str(hit.get("content", "")) for hit in pack.knowledge_hits]
    ).lower()
    flagged: list[str] = []
    for drug in _KNOWN_DRUGS:
        if drug in text and drug not in pack_text:
            flagged.append(drug)
    for date in _DATE_RE.findall(text):
        if date not in pack_text:
            flagged.append(date)
    for dose in _DOSE_RE.findall(text):
        if dose.lower() not in pack_text:
            flagged.append(dose)
    return flagged


def _is_medication_or_treatment(text: str) -> bool:
    """该论断是否属于需要证据支撑的用药/治疗建议（排除通用就医/照护建议）。"""
    if any(marker in text for marker in _GENERIC_CARE_MARKERS):
        return False
    return bool(
        re.search(
            r"(?:停药|减量|加量|换药|停用|替换|剂量|吃几片|吃多少|服用|使用|"
            r"开药|处方|注射|输液|抗生素|消炎药|止痛药)",
            text,
        )
    )


def _claim_allowed_by_contract(claim: Claim, contract: Optional[TaskContract]) -> bool:
    if contract is None:
        return True
    if contract.forbidden_claim_types and claim.claim_type in contract.forbidden_claim_types:
        return False
    if contract.allowed_claim_types and claim.claim_type not in contract.allowed_claim_types:
        return False
    return True


def _merge_judge(
    claim: Claim,
    judge: Optional[EvidenceJudgeResult],
) -> None:
    if judge is None or not judge.claim_bindings:
        return
    text = claim.text or ""
    for binding in judge.claim_bindings:
        binding_text = str(binding.claim or "").strip()
        if not binding_text:
            continue
        if binding_text in text or text in binding_text:
            # 只允许收紧，不允许把确定性的更严结论降级
            if binding.verdict is EvidenceJudgeVerdict.CONFLICT and claim.support_status is not SupportStatus.UNSUPPORTED:
                claim.support_status = SupportStatus.CONFLICT
                claim.notes.append("llm_judge_conflict")
            elif binding.verdict is EvidenceJudgeVerdict.UNSUPPORTED and claim.support_status is not SupportStatus.CONFLICT:
                claim.support_status = SupportStatus.UNSUPPORTED
                claim.notes.append("llm_judge_unsupported")
            elif binding.verdict is EvidenceJudgeVerdict.INSUFFICIENT and claim.support_status in (
                SupportStatus.SUPPORTED,
                SupportStatus.PARTIALLY_SUPPORTED,
            ):
                claim.support_status = SupportStatus.INSUFFICIENT
                claim.notes.append("llm_judge_insufficient")
            return


def validate_claims(
    claims: list[Claim],
    pack: EvidencePack,
    contract: Optional[TaskContract] = None,
    *,
    evidence_check: Optional[EvidenceCheck] = None,
    judge: Optional[EvidenceJudgeResult] = None,
    question: Optional[str] = None,
) -> list[Claim]:
    """逐条验证论断：绑定证据、判定支持状态、合并法官语义收紧。"""
    for claim in claims:
        if not _claim_allowed_by_contract(claim, contract):
            claim.notes.append(f"claim_type_forbidden_by_contract:{claim.claim_type.value}")
        patient_ids = _bind_patient_evidence(claim, pack)
        knowledge_ids, has_reviewed_or_trusted, has_any_knowledge = _bind_knowledge(claim, pack)
        claim.evidence_ids = list(dict.fromkeys([*patient_ids, *knowledge_ids]))

        if claim.claim_type is ClaimType.PATIENT_FACT:
            if patient_ids:
                claim.support_status = SupportStatus.SUPPORTED
            elif _entity_unsupported(claim, pack):
                claim.support_status = SupportStatus.UNSUPPORTED
                claim.notes.append("entity_not_in_pack")
            else:
                claim.support_status = SupportStatus.INSUFFICIENT
        elif claim.claim_type is ClaimType.GENERAL_KNOWLEDGE:
            if has_reviewed_or_trusted:
                claim.support_status = SupportStatus.SUPPORTED
            elif _model_knowledge_allowed(contract, claim):
                claim.support_status = SupportStatus.SUPPORTED
                claim.notes.append("model_knowledge_fallback")
            else:
                claim.support_status = SupportStatus.INSUFFICIENT
        elif claim.claim_type is ClaimType.CLINICAL_INTERPRETATION:
            if patient_ids and has_reviewed_or_trusted:
                claim.support_status = SupportStatus.SUPPORTED
            elif patient_ids and not has_reviewed_or_trusted:
                claim.support_status = SupportStatus.PARTIALLY_SUPPORTED
                claim.notes.append("missing_knowledge_evidence")
            elif not patient_ids:
                claim.support_status = SupportStatus.INSUFFICIENT
                claim.notes.append("missing_patient_evidence")
        else:  # RECOMMENDATION / ACTION
            if (
                not _is_medication_or_treatment(claim.text or "")
                or _has_negation_before_action(claim.text or "")
            ):
                claim.support_status = SupportStatus.SUPPORTED
                claim.notes.append("safety_warning_or_generic_guidance")
            elif patient_ids and has_reviewed_or_trusted:
                claim.support_status = SupportStatus.SUPPORTED
            elif patient_ids:
                claim.support_status = SupportStatus.INSUFFICIENT
                claim.notes.append("missing_knowledge_evidence")
            else:
                claim.support_status = SupportStatus.INSUFFICIENT
                claim.notes.append("missing_patient_evidence")

        _merge_judge(claim, judge)

    if evidence_check is not None and evidence_check.conflicts:
        for claim in claims:
            if claim.claim_type in (
                ClaimType.PATIENT_FACT,
                ClaimType.CLINICAL_INTERPRETATION,
            ) and claim.support_status in (
                SupportStatus.SUPPORTED,
                SupportStatus.PARTIALLY_SUPPORTED,
                SupportStatus.INSUFFICIENT,
            ):
                claim.support_status = SupportStatus.CONFLICT
                claim.notes.append("evidence_pack_conflict")
    return claims


def _model_knowledge_allowed(contract: Optional[TaskContract], claim: Claim) -> bool:
    if contract is None:
        return False
    if contract.fallback_strategy != "model_knowledge_limited":
        return False
    if claim.claim_type is not ClaimType.GENERAL_KNOWLEDGE:
        return False
    return contract.task_type in (
        TaskType.GENERAL_MEDICAL_EDUCATION,
        TaskType.MEDICATION_EDUCATION,
    )
