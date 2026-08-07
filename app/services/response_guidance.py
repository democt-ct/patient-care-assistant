"""回答内嵌升级指引与记忆个性化（V2 阶段 4 / 6）。

- 阶段 4：普通风险问题不再硬拦截，在正常回答中自然内嵌升级指引，并把
  ``risk_level`` 标为对应等级；确定性强信号（自伤/自杀危机、明确高危）
  仍由安全门禁短路，不进入本模块。
- 阶段 6：按患者偏好（``memory_preferences``）调整风险提醒强度与术语表达。

本模块只做确定性文本装配，不调用 LLM。
"""

from __future__ import annotations

from typing import Any, Optional

# 普通风险关键词：命中后在正常回答末尾内嵌升级指引（不硬拦截）
_ESCALATION_KEYWORDS = ("疼痛", "发麻", "麻木", "不适")
_ESCALATION_SUFFIX = "如果症状剧烈、伴大汗、呼吸困难或意识异常，请立即拨打 120 或前往急诊。"


def embed_escalation_guidance(answer: str, question: str) -> tuple[str, str]:
    """返回 (answer, risk_level)。普通风险症状内嵌升级指引，不拦截回答。"""
    text = (question or "").strip()
    current = answer or ""
    if any(keyword in text for keyword in _ESCALATION_KEYWORDS) and _ESCALATION_SUFFIX not in current:
        return current.rstrip() + "\n\n" + _ESCALATION_SUFFIX, "urgent"
    return current, "routine"


def personalize_response(
    answer: str,
    *,
    risk_level: str = "routine",
    preferences: Optional[dict[str, Any]] = None,
) -> tuple[str, dict[str, Any]]:
    """按患者偏好调整回答；返回 (answer, applied_flags)。"""
    prefs = preferences or {}
    applied: dict[str, Any] = {"personalized": False}
    text = answer or ""

    risk_alert_level = str(prefs.get("risk_alert_level") or "medium").lower()
    if risk_alert_level in ("high", "strong") and risk_level in ("urgent", "emergency"):
        reminder = "请务必重视：如症状加重或出现呼吸困难、意识异常，请立即拨打 120 或前往急诊。"
        if reminder not in text:
            text = text.rstrip() + "\n\n" + reminder
            applied["risk_reminder_strengthened"] = True
            applied["personalized"] = True

    medical_term_level = str(prefs.get("medical_term_level") or "plain").lower()
    if medical_term_level == "plain" and risk_level != "emergency":
        note = "（已按你的偏好尽量用通俗语言解释；如有需要可进一步追问）"
        if note not in text:
            text = text.rstrip() + "\n\n" + note
            applied["plain_language_note"] = True
            applied["personalized"] = True

    answer_length = str(prefs.get("answer_length") or "standard").lower()
    if answer_length == "brief":
        # 出于安全考虑不截断医疗内容，仅标记精简模式供前端/后续扩展使用
        applied["brief_mode"] = True
        applied["personalized"] = True

    return text, applied
