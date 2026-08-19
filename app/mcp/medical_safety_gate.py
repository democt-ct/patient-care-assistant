"""Deterministic safety gate for patient-facing medical conversations.

This module deliberately runs before any LLM call.  It only blocks classes of
requests for which a general-purpose model must not make an individualised
clinical decision without an approved, traceable evidence source.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from app.mcp.triage import TriageLevel, triage


class SafetyGateAction(str, Enum):
    ALLOW = "allow"
    EMERGENCY = "emergency"
    CLINICIAN_REVIEW = "clinician_review"
    CRISIS = "crisis"


@dataclass(frozen=True)
class SafetyGateDecision:
    action: SafetyGateAction
    reason: str = ""
    detected_signals: tuple[str, ...] = ()
    # ── Bounded Safety 扩展（保留原字段兼容）──
    risk_level: str = "routine"  # routine / urgent / emergency
    risk_signals: tuple[str, ...] = ()
    restricted_actions: tuple[str, ...] = ()
    prohibited_actions: tuple[str, ...] = ()
    requires_clinical_oversight: bool = False

    @property
    def blocked(self) -> bool:
        return self.action is not SafetyGateAction.ALLOW


# These patterns denote requests to make a patient-specific medication or
# treatment decision.  Education about a drug is not blocked by itself.
_CLINICAL_DECISION_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"(?:停药|停用|减量|加量|换药|替换).{0,12}(?:药|针|片|剂|治疗)", "medication_change"),
    (r"(?:药|针|片|剂).{0,12}(?:能不能停|要不要停|怎么停|怎么减|怎么加)", "medication_change"),
    (r"(?:能否|能不能|可以|是否|要不要).{0,8}(?:自己)?(?:停药|停用|减量|加量|换药)", "medication_change"),
    (r"(?:吃几片|吃多少|用多少|剂量|毫克|mg\b|μg\b|微克|单位)", "dose_request"),
    (r"(?:漏服|忘吃|漏吃|多吃|过量|服多了)", "medication_incident"),
    (r"(?:一起吃|同时吃|联用|相互作用|药物冲突|配伍)", "drug_interaction"),
    (r"(?:给我开|开个|处方|推荐.*(?:药|治疗)|用什么药)", "treatment_recommendation"),
)

# 自伤/自杀危机信号：不进入自由生成，直接给危机干预指引。
_CRISIS_PATTERNS: tuple[str, ...] = (
    r"自杀|自伤|割腕|轻生|不想活|不想活了|伤害自己|结束生命|活不下去|想死",
)


def evaluate_medical_safety(question: str) -> SafetyGateDecision:
    """Classify only the cases that must not reach free-form generation."""
    text = (question or "").strip()
    if not text:
        return SafetyGateDecision(SafetyGateAction.ALLOW)

    if any(re.search(pattern, text, re.IGNORECASE) for pattern in _CRISIS_PATTERNS):
        return SafetyGateDecision(
            SafetyGateAction.CRISIS,
            reason="self_harm_crisis",
            detected_signals=("self_harm",),
            risk_level="emergency",
            risk_signals=("self_harm",),
            prohibited_actions=("self_treatment", "diagnosis"),
            requires_clinical_oversight=True,
        )

    triage_result = triage(text)
    if triage_result.level is TriageLevel.EMERGENCY:
        return SafetyGateDecision(
            SafetyGateAction.EMERGENCY,
            reason="emergency_symptom",
            detected_signals=tuple(triage_result.detected_symptoms),
            risk_level="emergency",
            risk_signals=tuple(triage_result.detected_symptoms),
            restricted_actions=("self_treatment", "medication_advice"),
            prohibited_actions=("diagnosis",),
            requires_clinical_oversight=True,
        )

    matched = tuple(
        signal for pattern, signal in _CLINICAL_DECISION_PATTERNS if re.search(pattern, text, re.IGNORECASE)
    )
    if matched:
        return SafetyGateDecision(
            SafetyGateAction.CLINICIAN_REVIEW,
            reason="high_risk_clinical_decision",
            detected_signals=matched,
            risk_level="urgent",
            risk_signals=matched,
            restricted_actions=tuple(matched),
            prohibited_actions=("dose_change", "stop_medication", "drug_switch", "prescribe"),
            requires_clinical_oversight=True,
        )
    return SafetyGateDecision(SafetyGateAction.ALLOW)


def format_safety_gate_response(decision: SafetyGateDecision) -> str:
    """Return a non-diagnostic, actionable response without LLM generation."""
    if decision.action is SafetyGateAction.CRISIS:
        return (
            "你的描述让我很担心。请先确保自己当下的安全：联系信任的家人或朋友陪在你身边，"
            "或拨打全国心理援助热线 12356（24 小时）。如果你已经伤害自己或身边有立即的危险，"
            "请马上拨打 120 或前往最近的急诊。你不需要独自面对，有人可以帮你。"
        )
    if decision.action is SafetyGateAction.EMERGENCY:
        return (
            "你描述的情况可能需要紧急医疗评估。请立即拨打 120 或前往最近的急诊，"
            "不要等待线上回复，也不要自行调整药物。"
        )
    if decision.action is SafetyGateAction.CLINICIAN_REVIEW:
        return (
            "这涉及个体化用药或治疗决定。为避免错误剂量、相互作用或停药风险，"
            "我不能据此给出具体调整方案。请携带药品名称、规格、当前用法和最近的"
            "检验结果，尽快向开方医生或药师核实；如出现严重不适，请立即就医。"
        )
    return ""
