"""规则手册知识块（V2 阶段 3）—— 已审核知识（review_status=approved）。

把「各类问题如何处理 / 话术 / 流程」整理为已审核知识块，走
``clinical_knowledge_governance`` 准入（``--publish`` 发布），对话时按路由
任务注入系统提示词。source_id 使用注册表内 ``hospital_approved_content``
（允许 internal URI）。

运行时注入是确定性「RAG」：按 RetrievalRoute.task 检索对应知识块，
不依赖向量库，保证离线可用；``scripts/import_rulebook_knowledge.py`` 负责
治理准入校验与 JSON 导出，便于审计。
"""

from __future__ import annotations

from typing import Any, Optional

from app.schemas.retrieval import RetrievalRoute, TaskType

REVIEWED_BY = "patient-care-assistant@internal"
REVIEWED_AT = "2026-08-07"
SOURCE_URL = "internal://rulebook/v2"

_TASK_LABELS = {
    TaskType.FACT_VERIFICATION: "病历事实核验",
    TaskType.MEDICATION_ALLERGY_CHECK: "用药与过敏核对",
    TaskType.REPORT_COMPREHENSION: "报告理解",
    TaskType.LONGITUDINAL_COMPARISON: "历史纵向比较",
    TaskType.RISK_TRIAGE: "风险分流",
    TaskType.VISIT_PREPARATION: "就医准备",
    TaskType.GENERAL_HEALTH_EDUCATION: "一般健康教育",
    TaskType.GENERAL_MEDICAL_EDUCATION: "一般健康教育",
    TaskType.MEDICATION_EDUCATION: "药物教育（非个体化）",
    TaskType.MEDICATION_DOSING: "个体化剂量决策（禁止）",
    TaskType.MEDICATION_RECONCILIATION: "用药与过敏核对",
    TaskType.PATIENT_FACT_LOOKUP: "病历事实核验",
    TaskType.PATIENT_RECORD_INTERPRETATION: "记录解读",
    TaskType.SYMPTOM_TRIAGE: "症状分流",
    TaskType.CLINICAL_DECISION: "临床决策（禁止）",
    TaskType.EMERGENCY_TRIAGE: "急诊分流",
}

_RULEBOOK: dict[TaskType, dict[str, str]] = {
    TaskType.FACT_VERIFICATION: {
        "title": "病历事实核验",
        "handling": "只陈述患者结构化记录中的事实（诊断、过敏、用药、就诊医生、手术、复诊等），返回事实、日期与来源；不推断、不补全、不把常识当患者事实。",
        "answer_rules": "回答必须可追溯到证据包；来源冲突时列出双方日期与来源并转医生确认；证据缺失时澄清或拒答，不得编造。",
        "escalation": "如患者询问紧急症状或危险用药，按安全门禁处理。",
    },
    TaskType.MEDICATION_ALLERGY_CHECK: {
        "title": "用药与过敏核对",
        "handling": "核对过敏史与当前用药；禁止给出个体化剂量、停药、换药、药物相互作用结论。",
        "answer_rules": "先说明记录的过敏/用药事实，再给出风险提示；过敏+慎用边界必须转医生/药师确认；不替患者下临床结论。",
        "escalation": "如患者描述严重过敏反应（呼吸困难、喉头水肿、意识改变），提示立即拨打 120。",
    },
    TaskType.RISK_TRIAGE: {
        "title": "风险分流",
        "handling": "强信号（胸痛、呼吸困难、大出血、昏迷等）直接给急救/就医指引；自伤/自杀危机给 12356 心理援助热线与 120 指引。",
        "answer_rules": "不诊断、不建议自行处理；明确下一步（拨打 120 / 急诊 / 热线）。",
        "escalation": "本任务本身即升级路径，不进入自由生成。",
    },
    TaskType.VISIT_PREPARATION: {
        "title": "就医准备",
        "handling": "基于病历/时间线整理就诊摘要与问题清单；不新增未记录的信息。",
        "answer_rules": "区分记录事实与一般建议；清单仅供参考，以医生意见为准。",
        "escalation": "如主诉含强风险信号，按安全门禁处理。",
    },
    TaskType.GENERAL_HEALTH_EDUCATION: {
        "title": "一般健康教育",
        "handling": "使用审核临床知识回答非个体化问题（药物用途/副作用、生活方式等）；禁止给出针对个人的剂量或治疗方案。",
        "answer_rules": "明确这是通用知识而非个人诊疗建议；涉及用药时提醒遵医嘱。",
        "escalation": "如症状描述演变为强信号，提示尽快就医。",
    },
    TaskType.REPORT_COMPREHENSION: {
        "title": "报告理解",
        "handling": "区分报告事实与一般解释；异常指标提示由医生判读。",
        "answer_rules": "引用报告字段与日期；不下诊断结论。",
        "escalation": "危急值或强风险提示按安全门禁处理。",
    },
    TaskType.LONGITUDINAL_COMPARISON: {
        "title": "历史纵向比较",
        "handling": "比较不同日期记录的变化，描述趋势，不下诊断。",
        "answer_rules": "给出各日期数值与变化方向；不推断病因。",
        "escalation": "如变化显著且伴强风险信号，提示就医。",
    },
    TaskType.GENERAL_MEDICAL_EDUCATION: {
        "title": "一般健康教育",
        "handling": "使用审核临床知识回答非个体化问题（生活方式、科普等）；禁止给出针对个人的剂量或治疗方案。",
        "answer_rules": "明确这是通用知识而非个人诊疗建议；涉及用药时提醒遵医嘱。",
        "escalation": "如症状描述演变为强信号，提示尽快就医。",
    },
    TaskType.MEDICATION_EDUCATION: {
        "title": "药物教育（非个体化）",
        "handling": "解释药物作用机制、适应症、一般注意事项与副作用；不针对具体患者给剂量或方案。",
        "answer_rules": "区分通用药物知识与个体化用药结论；涉及用药时提醒遵医嘱。",
        "escalation": "如用户描述演变为个体化剂量/停药/换药请求，按禁止动作处理。",
    },
    TaskType.MEDICATION_DOSING: {
        "title": "个体化剂量决策（禁止）",
        "handling": "剂量、停药、换药、漏服、相互作用等个体化用药决策一律不给出方案。",
        "answer_rules": "说明需要医生/药师核实，提示携带药品信息就医；不得生成具体剂量。",
        "escalation": "如伴严重不适或过敏反应信号，提示立即就医。",
    },
    TaskType.MEDICATION_RECONCILIATION: {
        "title": "用药与过敏核对",
        "handling": "核对过敏史与当前用药；禁止给出个体化剂量、停药、换药、药物相互作用结论。",
        "answer_rules": "先说明记录的过敏/用药事实，再给出风险提示；过敏+慎用边界必须转医生/药师确认。",
        "escalation": "如患者描述严重过敏反应，提示立即拨打 120。",
    },
    TaskType.PATIENT_FACT_LOOKUP: {
        "title": "病历事实核验",
        "handling": "只陈述患者结构化记录中的事实（诊断、过敏、用药、就诊医生、手术、复诊等）。",
        "answer_rules": "回答必须可追溯到证据包；证据缺失时澄清或拒答，不得编造。",
        "escalation": "如患者询问紧急症状或危险用药，按安全门禁处理。",
    },
    TaskType.PATIENT_RECORD_INTERPRETATION: {
        "title": "记录解读",
        "handling": "解释报告/指标/就诊记录，比较不同日期变化，不下诊断结论。",
        "answer_rules": "区分记录事实与一般解释；异常指标提示由医生判读。",
        "escalation": "危急值或强风险提示按安全门禁处理。",
    },
    TaskType.SYMPTOM_TRIAGE: {
        "title": "症状分流",
        "handling": "低风险症状先澄清（持续时间、伴随症状），再给一般性就医指征；不诊断、不处方。",
        "answer_rules": "给出可操作的一般建议与升级信号；涉及个体化结论时转医生。",
        "escalation": "如症状描述演变为强风险信号，立即提示 120/急诊。",
    },
    TaskType.CLINICAL_DECISION: {
        "title": "临床决策（禁止）",
        "handling": "个体化治疗决策（处方、停药、换药、剂量调整）不给出方案。",
        "answer_rules": "拒绝并转医生/药师；可报告已记录的患者事实。",
        "escalation": "如伴紧急信号，提示立即就医。",
    },
    TaskType.EMERGENCY_TRIAGE: {
        "title": "急诊分流",
        "handling": "强信号（胸痛、呼吸困难、大出血、昏迷等）直接给急救/就医指引。",
        "answer_rules": "不诊断、不建议自行处理；明确下一步（拨打 120 / 急诊 / 热线）。",
        "escalation": "本任务本身即升级路径，不进入自由生成。",
    },
}


def rulebook_context_for(route: Optional[RetrievalRoute]) -> str:
    """按路由任务返回提示词注入块（已审核规则手册知识）。"""
    if route is None:
        return ""
    entry = _RULEBOOK.get(route.task)
    if entry is None:
        return ""
    lines = [
        "以下是从规则手册检索到的处理规范，请严格遵守：",
        f"- 任务：{entry['title']}",
        f"- 处理规范：{entry['handling']}",
        f"- 回答要求：{entry['answer_rules']}",
        f"- 升级指引：{entry['escalation']}",
    ]
    if route.forbidden_actions:
        lines.append(f"- 禁止动作：{'、'.join(route.forbidden_actions)}")
    return "\n".join(lines)


RULEBOOK_ENTRIES: list[dict[str, Any]] = [
    {
        "source_id": "hospital_approved_content",
        "source_type": "hospital_protocol",
        "source_url": SOURCE_URL,
        "title": entry["title"],
        "content": f"{entry['handling']}\n{entry['answer_rules']}\n{entry['escalation']}",
        "task": task.value,
        "review_status": "approved",
        "source_ref": "internal-rulebook-v2",
        "reviewed_by": REVIEWED_BY,
        "reviewed_at": REVIEWED_AT,
    }
    for task, entry in _RULEBOOK.items()
]
