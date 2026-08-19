"""Task Contract 注册表（Bounded Safety）—— 确定性行为边界。

``build_task_contract(route)`` 在现有 ``RetrievalRoute`` 基础上扩展出完整
任务契约（允许/禁止动作、允许工具、证据要求、Claim 类型边界、回退策略），
由路由确定后固定，LLM 不得修改。
"""

from __future__ import annotations

from typing import Optional

from app.schemas.retrieval import (
    ClaimType,
    EvidenceRequirement,
    EvidenceSourceType,
    RetrievalRoute,
    TaskContract,
    TaskType,
)

_LEGACY_TO_CANONICAL: dict[TaskType, TaskType] = {
    TaskType.FACT_VERIFICATION: TaskType.PATIENT_FACT_LOOKUP,
    TaskType.MEDICATION_ALLERGY_CHECK: TaskType.MEDICATION_RECONCILIATION,
    TaskType.REPORT_COMPREHENSION: TaskType.PATIENT_RECORD_INTERPRETATION,
    TaskType.LONGITUDINAL_COMPARISON: TaskType.PATIENT_RECORD_INTERPRETATION,
    TaskType.RISK_TRIAGE: TaskType.EMERGENCY_TRIAGE,
    TaskType.GENERAL_HEALTH_EDUCATION: TaskType.GENERAL_MEDICAL_EDUCATION,
}


def canonical_task(task) -> TaskType:
    """把旧任务值归一化为 canonical 任务；已是 canonical 的原样返回。"""
    try:
        value = TaskType(task)
    except ValueError:
        value = TaskType(str(task))
    return _LEGACY_TO_CANONICAL.get(value, value)


def _req(
    kind: EvidenceSourceType,
    *,
    required: bool = False,
    preferred: bool = False,
    note: str = "",
) -> EvidenceRequirement:
    return EvidenceRequirement(
        evidence_type=kind,
        required=required,
        preferred=preferred,
        note=note,
    )


_PATIENT_TOOLS = ["get_patient_profile", "get_medical_records", "get_visit_records"]
_RECORD_TOOLS = ["get_medical_records", "get_visit_records", "get_patient_profile"]


_CONTRACTS: dict[TaskType, dict] = {
    TaskType.GENERAL_MEDICAL_EDUCATION: {
        "allowed_actions": ["explain_general_knowledge", "explain_precautions", "explain_escalation_signals"],
        "forbidden_actions": ["prescribe", "change_dose", "stop_medication", "recommend_switch", "diagnose_patient"],
        "allowed_tools": [],
        "allowed_evidence_sources": [
            EvidenceSourceType.REVIEWED_KNOWLEDGE,
            EvidenceSourceType.TRUSTED_MEDICAL_SOURCE,
            EvidenceSourceType.MODEL_KNOWLEDGE,
        ],
        "evidence_requirements": [
            _req(EvidenceSourceType.REVIEWED_KNOWLEDGE, preferred=True, note="已审核知识优先"),
            _req(EvidenceSourceType.TRUSTED_MEDICAL_SOURCE, preferred=True, note="可信医学来源次选"),
            _req(EvidenceSourceType.MODEL_KNOWLEDGE, note="低风险通识允许有限模型知识兜底"),
        ],
        "required_patient_fields": [],
        "allowed_claim_types": [ClaimType.GENERAL_KNOWLEDGE],
        "forbidden_claim_types": [
            ClaimType.PATIENT_FACT,
            ClaimType.CLINICAL_INTERPRETATION,
            ClaimType.RECOMMENDATION,
            ClaimType.ACTION,
        ],
        "max_retrieval_rounds": 1,
        "requires_clinician_oversight": False,
        "fallback_strategy": "model_knowledge_limited",
    },
    TaskType.MEDICATION_EDUCATION: {
        "allowed_actions": [
            "explain_mechanism",
            "explain_indication",
            "explain_general_precautions",
            "explain_side_effects",
        ],
        "forbidden_actions": ["prescribe", "change_dose", "stop_medication", "recommend_switch", "give_dose"],
        "allowed_tools": [],
        "allowed_evidence_sources": [
            EvidenceSourceType.REVIEWED_KNOWLEDGE,
            EvidenceSourceType.TRUSTED_MEDICAL_SOURCE,
            EvidenceSourceType.MODEL_KNOWLEDGE,
        ],
        "evidence_requirements": [
            _req(EvidenceSourceType.REVIEWED_KNOWLEDGE, preferred=True, note="已审核知识优先"),
            _req(EvidenceSourceType.TRUSTED_MEDICAL_SOURCE, preferred=True, note="可信药品说明书次选"),
            _req(EvidenceSourceType.MODEL_KNOWLEDGE, note="低风险药物通识允许有限模型知识兜底"),
        ],
        "required_patient_fields": [],
        "allowed_claim_types": [ClaimType.GENERAL_KNOWLEDGE],
        "forbidden_claim_types": [
            ClaimType.PATIENT_FACT,
            ClaimType.CLINICAL_INTERPRETATION,
            ClaimType.RECOMMENDATION,
            ClaimType.ACTION,
        ],
        "max_retrieval_rounds": 1,
        "requires_clinician_oversight": False,
        "fallback_strategy": "model_knowledge_limited",
    },
    TaskType.MEDICATION_DOSING: {
        "allowed_actions": ["explain_limitations", "refer_to_doctor", "report_patient_facts"],
        "forbidden_actions": ["give_dose", "change_dose", "stop_medication", "recommend_switch", "prescribe"],
        "allowed_tools": _PATIENT_TOOLS,
        "allowed_evidence_sources": [
            EvidenceSourceType.PATIENT_RECORD,
            EvidenceSourceType.TRUSTED_MEDICAL_SOURCE,
        ],
        "evidence_requirements": [
            _req(EvidenceSourceType.PATIENT_RECORD, required=True, note="个体化剂量必须有患者用药/病历上下文"),
            _req(EvidenceSourceType.TRUSTED_MEDICAL_SOURCE, required=True, note="剂量调整必须有可信医学来源"),
        ],
        "required_patient_fields": ["current_medications", "diagnosis"],
        "allowed_claim_types": [ClaimType.PATIENT_FACT, ClaimType.GENERAL_KNOWLEDGE],
        "forbidden_claim_types": [ClaimType.RECOMMENDATION, ClaimType.ACTION],
        "max_retrieval_rounds": 1,
        "requires_clinician_oversight": True,
        "fallback_strategy": "refuse",
    },
    TaskType.MEDICATION_RECONCILIATION: {
        "allowed_actions": [
            "report_allergy_history",
            "report_current_medications",
            "flag_conflict",
            "refer_to_doctor",
        ],
        "forbidden_actions": ["prescribe", "change_dose", "stop_medication", "recommend_switch", "conclude_safety"],
        "allowed_tools": _PATIENT_TOOLS,
        "allowed_evidence_sources": [
            EvidenceSourceType.PATIENT_RECORD,
            EvidenceSourceType.REVIEWED_KNOWLEDGE,
            EvidenceSourceType.TRUSTED_MEDICAL_SOURCE,
        ],
        "evidence_requirements": [
            _req(EvidenceSourceType.PATIENT_RECORD, required=True, note="过敏/用药核对必须有患者记录"),
            _req(EvidenceSourceType.REVIEWED_KNOWLEDGE, preferred=True, note="已审核知识优先"),
            _req(EvidenceSourceType.TRUSTED_MEDICAL_SOURCE, preferred=True, note="可信来源次选"),
        ],
        "required_patient_fields": ["allergy_history", "current_medications"],
        "allowed_claim_types": [ClaimType.PATIENT_FACT, ClaimType.GENERAL_KNOWLEDGE],
        "forbidden_claim_types": [ClaimType.RECOMMENDATION, ClaimType.ACTION],
        "max_retrieval_rounds": 1,
        "requires_clinician_oversight": True,
        "fallback_strategy": "clarify",
    },
    TaskType.PATIENT_FACT_LOOKUP: {
        "allowed_actions": ["report_fact", "cite_record", "report_absence"],
        "forbidden_actions": ["diagnose_patient", "infer_condition", "treatment_recommendation"],
        "allowed_tools": _PATIENT_TOOLS,
        "allowed_evidence_sources": [EvidenceSourceType.PATIENT_RECORD],
        "evidence_requirements": [
            _req(EvidenceSourceType.PATIENT_RECORD, required=True, note="患者事实必须来自结构化记录"),
        ],
        "required_patient_fields": [],
        "allowed_claim_types": [ClaimType.PATIENT_FACT],
        "forbidden_claim_types": [
            ClaimType.CLINICAL_INTERPRETATION,
            ClaimType.RECOMMENDATION,
            ClaimType.ACTION,
        ],
        "max_retrieval_rounds": 0,
        "requires_clinician_oversight": False,
        "fallback_strategy": "clarify",
    },
    TaskType.PATIENT_RECORD_INTERPRETATION: {
        "allowed_actions": ["explain_record", "compare_records", "describe_trend", "flag_for_doctor"],
        "forbidden_actions": ["diagnose_patient", "treatment_recommendation", "conclude_disease"],
        "allowed_tools": _RECORD_TOOLS,
        "allowed_evidence_sources": [
            EvidenceSourceType.PATIENT_RECORD,
            EvidenceSourceType.REVIEWED_KNOWLEDGE,
            EvidenceSourceType.TRUSTED_MEDICAL_SOURCE,
        ],
        "evidence_requirements": [
            _req(EvidenceSourceType.PATIENT_RECORD, required=True, note="记录解读必须有患者记录"),
            _req(EvidenceSourceType.REVIEWED_KNOWLEDGE, preferred=True, note="已审核知识辅助解释"),
        ],
        "required_patient_fields": ["timeline_records", "report_facts"],
        "allowed_claim_types": [ClaimType.PATIENT_FACT, ClaimType.CLINICAL_INTERPRETATION],
        "forbidden_claim_types": [ClaimType.RECOMMENDATION, ClaimType.ACTION],
        "max_retrieval_rounds": 1,
        "requires_clinician_oversight": True,
        "fallback_strategy": "clarify",
    },
    TaskType.SYMPTOM_TRIAGE: {
        "allowed_actions": ["ask_clarifying", "give_general_guidance", "explain_escalation_signals", "escalate"],
        "forbidden_actions": ["diagnose_patient", "prescribe", "change_dose", "stop_medication"],
        "allowed_tools": ["get_patient_profile"],
        "allowed_evidence_sources": [
            EvidenceSourceType.REVIEWED_KNOWLEDGE,
            EvidenceSourceType.TRUSTED_MEDICAL_SOURCE,
            EvidenceSourceType.PATIENT_RECORD,
        ],
        "evidence_requirements": [
            _req(EvidenceSourceType.REVIEWED_KNOWLEDGE, preferred=True, note="已审核知识优先"),
            _req(EvidenceSourceType.PATIENT_RECORD, preferred=True, note="有患者记录时辅助核对"),
        ],
        "required_patient_fields": [],
        "allowed_claim_types": [ClaimType.GENERAL_KNOWLEDGE, ClaimType.PATIENT_FACT],
        "forbidden_claim_types": [ClaimType.RECOMMENDATION, ClaimType.ACTION],
        "max_retrieval_rounds": 1,
        "requires_clinician_oversight": False,
        "fallback_strategy": "model_knowledge_limited",
    },
    TaskType.CLINICAL_DECISION: {
        "allowed_actions": ["report_facts", "refer_to_doctor", "explain_limitations"],
        "forbidden_actions": ["decide_treatment", "prescribe", "change_dose", "stop_medication", "recommend_switch"],
        "allowed_tools": _PATIENT_TOOLS,
        "allowed_evidence_sources": [
            EvidenceSourceType.PATIENT_RECORD,
            EvidenceSourceType.TRUSTED_MEDICAL_SOURCE,
        ],
        "evidence_requirements": [
            _req(EvidenceSourceType.PATIENT_RECORD, required=True, note="临床决策必须有患者记录"),
            _req(EvidenceSourceType.TRUSTED_MEDICAL_SOURCE, required=True, note="临床决策必须有可信医学来源"),
        ],
        "required_patient_fields": ["diagnosis", "current_medications"],
        "allowed_claim_types": [ClaimType.PATIENT_FACT, ClaimType.GENERAL_KNOWLEDGE],
        "forbidden_claim_types": [ClaimType.CLINICAL_INTERPRETATION, ClaimType.RECOMMENDATION, ClaimType.ACTION],
        "max_retrieval_rounds": 1,
        "requires_clinician_oversight": True,
        "fallback_strategy": "refuse",
    },
    TaskType.EMERGENCY_TRIAGE: {
        "allowed_actions": ["give_emergency_guidance", "escalate"],
        "forbidden_actions": ["diagnose_patient", "treat", "advise_medication"],
        "allowed_tools": [],
        "allowed_evidence_sources": [],
        "evidence_requirements": [],
        "required_patient_fields": [],
        "allowed_claim_types": [ClaimType.GENERAL_KNOWLEDGE],
        "forbidden_claim_types": [ClaimType.RECOMMENDATION, ClaimType.ACTION, ClaimType.CLINICAL_INTERPRETATION],
        "max_retrieval_rounds": 0,
        "requires_clinician_oversight": True,
        "fallback_strategy": "escalate",
    },
    TaskType.VISIT_PREPARATION: {
        "allowed_actions": ["summarize_records", "list_questions"],
        "forbidden_actions": ["diagnose_patient", "treat", "prescribe"],
        "allowed_tools": _RECORD_TOOLS,
        "allowed_evidence_sources": [EvidenceSourceType.PATIENT_RECORD],
        "evidence_requirements": [
            _req(EvidenceSourceType.PATIENT_RECORD, required=True, note="就医准备必须基于患者记录"),
        ],
        "required_patient_fields": ["visit_records", "diagnosis", "medications"],
        "allowed_claim_types": [ClaimType.PATIENT_FACT, ClaimType.GENERAL_KNOWLEDGE],
        "forbidden_claim_types": [ClaimType.RECOMMENDATION, ClaimType.ACTION, ClaimType.CLINICAL_INTERPRETATION],
        "max_retrieval_rounds": 1,
        "requires_clinician_oversight": False,
        "fallback_strategy": "clarify",
    },
}


def build_task_contract(route: Optional[RetrievalRoute]) -> TaskContract:
    """从 RetrievalRoute 确定性构建 Task Contract。"""
    if route is None:
        return TaskContract(task_type=TaskType.GENERAL_MEDICAL_EDUCATION)
    task = canonical_task(route.task)
    spec = _CONTRACTS.get(task)
    if spec is None:
        spec = _CONTRACTS[TaskType.GENERAL_MEDICAL_EDUCATION]
    return TaskContract(
        task_type=task,
        allowed_actions=list(spec["allowed_actions"]),
        forbidden_actions=[*spec["forbidden_actions"], *route.forbidden_actions],
        allowed_tools=list(spec["allowed_tools"]),
        allowed_evidence_sources=list(spec["allowed_evidence_sources"]),
        evidence_requirements=list(spec["evidence_requirements"]),
        required_patient_fields=[*spec["required_patient_fields"], *route.required_facts],
        allowed_claim_types=list(spec["allowed_claim_types"]),
        forbidden_claim_types=list(spec["forbidden_claim_types"]),
        max_retrieval_rounds=route.max_retrieval_rounds,
        requires_clinician_oversight=spec["requires_clinician_oversight"],
        fallback_strategy=spec["fallback_strategy"],
    )


def contract_summary_text(contract: TaskContract) -> str:
    """把任务契约渲染为注入给 LLM 的确定性约束块。"""
    if contract is None:
        return ""
    lines = [
        "以下为本轮任务契约，属于不可更改的确定性约束：",
        f"- 任务类型：{contract.task_type.value}",
        f"- 允许动作：{'、'.join(contract.allowed_actions) or '无'}",
        f"- 禁止动作：{'、'.join(contract.forbidden_actions) or '无'}",
        f"- 允许工具：{'、'.join(contract.allowed_tools) or '无（无需调用工具）'}",
        f"- 允许证据来源：{'、'.join(source.value for source in contract.allowed_evidence_sources) or '无'}",
        f"- 允许论断类型：{'、'.join(claim.value for claim in contract.allowed_claim_types) or '无'}",
    ]
    if contract.requires_clinician_oversight:
        lines.append("- 需要医生/药师监督：是（不得给出个体化结论）")
    return "\n".join(lines)
