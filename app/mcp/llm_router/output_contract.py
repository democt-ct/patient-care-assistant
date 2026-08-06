"""统一输出装配：安全响应、结构化直答与 Agent 回答输出同一五段契约。

契约定义见 ``app/schemas/retrieval.py:AgentOutputContract``。
本模块只做确定性装配，不调用 LLM；缺省字段给保守默认值，保持既有 SSE 字段兼容。
"""

from __future__ import annotations

from typing import Any, Optional

from app.schemas.retrieval import (
    EvidenceStatus,
    NextAction,
    RiskLevel,
)


def _build_evidence_summary(
    result: dict[str, Any],
    evidence_check: dict[str, Any],
    safety_action: Optional[str],
) -> str:
    if safety_action == "crisis":
        return "检测到自伤/危机信号，本回答仅提供心理援助与就医指引，未使用病历数据。"
    if safety_action == "emergency":
        return "系统检测到紧急风险信号，本回答仅提供急救/就医指引，未使用病历数据。"
    if safety_action == "clinician_review":
        return "本回答未给出个体化方案，请以开方医生或药师意见为准。"

    status = evidence_check.get("status")
    if status == EvidenceStatus.CONFLICT.value:
        return "回答引用了多个来源，其中存在不一致记录，已列出双方来源与日期。"
    if status in (EvidenceStatus.MISSING.value, EvidenceStatus.HIGH_RISK.value) or evidence_check.get("sufficient") is False:
        return "未检索到足够证据，未生成个体化结论。"

    tool_result = result.get("tool_result") or {}
    data = tool_result.get("data")
    if isinstance(data, dict) and any(
        data.get(key)
        for key in ("patient", "medical_records", "visit_records", "knowledge_hits", "sources")
    ):
        return "回答依据：结构化病历/就诊记录与审核知识（详见来源摘要）。"
    return "回答依据：未检索到可引用记录，仅提供一般性说明。"


def assemble_output_contract(
    result: dict[str, Any],
    *,
    safety_action: Optional[str] = None,
) -> dict[str, Any]:
    """补齐五段输出契约字段并返回同一 ``result`` 字典。

    ``safety_action`` 为安全门禁动作（``emergency`` / ``clinician_review``），
    传入时以确定性门禁结论为准，不覆盖为更低风险等级。
    """
    result.setdefault("answer", "")
    evidence_check = result.get("evidence_check") or {}

    if safety_action in ("emergency", "crisis"):
        result["risk_level"] = RiskLevel.EMERGENCY.value
        result["next_action"] = NextAction.EMERGENCY_CARE.value
    elif safety_action == "clinician_review":
        result["risk_level"] = RiskLevel.URGENT.value
        result["next_action"] = NextAction.CONTACT_DOCTOR.value
    else:
        status = evidence_check.get("status")
        if status == EvidenceStatus.HIGH_RISK.value:
            result["risk_level"] = RiskLevel.URGENT.value
            result["next_action"] = NextAction.CONTACT_DOCTOR.value
        elif status == EvidenceStatus.CONFLICT.value:
            result.setdefault("risk_level", RiskLevel.ROUTINE.value)
            result["next_action"] = NextAction.CONTACT_DOCTOR.value
        elif status == EvidenceStatus.MISSING.value or evidence_check.get("sufficient") is False:
            result.setdefault("risk_level", RiskLevel.ROUTINE.value)
            result["next_action"] = NextAction.CONTINUE_SUPPLEMENT.value
        else:
            result.setdefault("risk_level", RiskLevel.ROUTINE.value)
            result.setdefault("next_action", NextAction.VIEW_RECORDS.value)

    result.setdefault("evidence_summary", _build_evidence_summary(result, evidence_check, safety_action))
    return result
