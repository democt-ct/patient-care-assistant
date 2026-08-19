"""Agentic RAG 输出契约与证据模型（患者医疗信息核验与就医导航 Agent）。

设计依据：``docs/patient_medical_information_agent_design.md`` 与
``docs/执行计划.md`` 阶段 A。本模块是任务路由、证据包和 Agent 输出契约的
【唯一权威定义】，消费方包括：

  - ``app/services/retrieval_router.py``      任务分类与检索路由（阶段 B）
  - ``app/services/agentic_retrieval.py``     EvidencePack 组装（阶段 C）
  - ``app/services/evidence_policy.py``       证据判定（阶段 C）
  - ``app/services/citation_validator.py``    引用校验（阶段 C）
  - ``app/mcp/llm_router/output_contract.py`` 统一输出装配

禁止在其它模块硬编码任务枚举或输出字段副本。
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class TaskType(str, Enum):
    """用户任务类型。聊天只是交互界面，所有请求先归入任务类型。

    Bounded Safety 升级后新增 9 类 canonical 任务；旧值保留为兼容别名，
    通过 :func:`app.services.task_contract.canonical_task` 归一化。
    """

    # ── 兼容别名（legacy，保留以便旧用例/持久化数据解析）──
    FACT_VERIFICATION = "fact_verification"
    MEDICATION_ALLERGY_CHECK = "medication_allergy_check"
    REPORT_COMPREHENSION = "report_comprehension"
    LONGITUDINAL_COMPARISON = "longitudinal_comparison"
    RISK_TRIAGE = "risk_triage"
    VISIT_PREPARATION = "visit_preparation"
    GENERAL_HEALTH_EDUCATION = "general_health_education"

    # ── canonical 任务（Bounded Safety）──
    GENERAL_MEDICAL_EDUCATION = "general_medical_education"
    MEDICATION_EDUCATION = "medication_education"
    MEDICATION_DOSING = "medication_dosing"
    MEDICATION_RECONCILIATION = "medication_reconciliation"
    PATIENT_FACT_LOOKUP = "patient_fact_lookup"
    PATIENT_RECORD_INTERPRETATION = "patient_record_interpretation"
    SYMPTOM_TRIAGE = "symptom_triage"
    CLINICAL_DECISION = "clinical_decision"
    EMERGENCY_TRIAGE = "emergency_triage"


class EvidenceSourceType(str, Enum):
    """证据来源分层（Bounded Safety）：回答中的每个论断按此分层引用证据。"""

    PATIENT_RECORD = "patient_record"
    REVIEWED_KNOWLEDGE = "reviewed_knowledge"
    TRUSTED_MEDICAL_SOURCE = "trusted_medical_source"
    MODEL_KNOWLEDGE = "model_knowledge"


class TrustLevel(str, Enum):
    """证据可信度分层。"""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ClaimType(str, Enum):
    """回答中关键论断的类型（Claim-level Validation 的分类基准）。"""

    PATIENT_FACT = "patient_fact"
    GENERAL_KNOWLEDGE = "general_knowledge"
    CLINICAL_INTERPRETATION = "clinical_interpretation"
    RECOMMENDATION = "recommendation"
    ACTION = "action"


class SupportStatus(str, Enum):
    """单条 Claim 的证据支持状态。"""

    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    INSUFFICIENT = "insufficient"
    CONFLICT = "conflict"
    UNSUPPORTED = "unsupported"


class SafetyStatus(str, Enum):
    """单条 Claim 的安全策略状态。"""

    ALLOWED = "allowed"
    RESTRICTED = "restricted"
    PROHIBITED = "prohibited"
    NEEDS_OVERSIGHT = "needs_oversight"


class FinalDecision(str, Enum):
    """最终回答决策（Evidence Validation + Safety Enforcement 的汇总裁定）。"""

    PASS = "pass"
    PARTIAL = "partial"
    CLARIFY = "clarify"
    REFUSE = "refuse"
    ESCALATE = "escalate"


class EvidenceRequirement(BaseModel):
    """Task Contract 中某类证据的要求（required / preferred / optional）。"""

    evidence_type: EvidenceSourceType
    required: bool = False
    preferred: bool = False
    note: str = ""


class TaskContract(BaseModel):
    """Task Contract：任务的行为边界，LLM 不得修改。

    由 :func:`app.services.task_contract.build_task_contract` 从
    ``RetrievalRoute`` 确定性构建，约束后续检索、生成与验证。
    """

    task_type: TaskType
    allowed_actions: list[str] = Field(default_factory=list)
    forbidden_actions: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    allowed_evidence_sources: list[EvidenceSourceType] = Field(default_factory=list)
    evidence_requirements: list[EvidenceRequirement] = Field(default_factory=list)
    required_patient_fields: list[str] = Field(default_factory=list)
    allowed_claim_types: list[ClaimType] = Field(default_factory=list)
    forbidden_claim_types: list[ClaimType] = Field(default_factory=list)
    max_retrieval_rounds: int = Field(default=1, ge=0, le=2)
    requires_clinician_oversight: bool = False
    fallback_strategy: str = "refuse"


class Claim(BaseModel):
    """回答中的单条论断及其验证/安全状态。"""

    claim_id: str = Field(..., description="论断 ID，如 claim-001")
    text: str = Field(..., description="论断文本（来自回答，不含病历原文）")
    claim_type: ClaimType = Field(..., description="论断类型")
    required_evidence_types: list[EvidenceSourceType] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list, description="支撑该论断的证据 ID")
    support_status: SupportStatus = Field(default=SupportStatus.INSUFFICIENT)
    safety_status: SafetyStatus = Field(default=SafetyStatus.ALLOWED)
    notes: list[str] = Field(default_factory=list)


class RetrievalSource(str, Enum):
    """允许的有限数据源枚举。Agent 不得调用枚举之外的检索入口。"""

    STRUCTURED_PATIENT_FACT = "structured_patient_fact"
    MEDICAL_TIMELINE = "medical_timeline"
    CLINICAL_KNOWLEDGE = "clinical_knowledge"
    CARE_PLAN_CONTEXT = "care_plan_context"
    REPORT_CONTEXT = "report_context"
    NO_RETRIEVAL = "no_retrieval"


class EvidenceReviewStatus(str, Enum):
    """证据审核状态：只允许已审核证据进入默认检索结果。"""

    REVIEWED = "reviewed"
    PENDING = "pending"
    REJECTED = "rejected"


class RetrievalRoute(BaseModel):
    """任务路由结果：任务、允许数据源、所需字段与禁止动作。"""

    task: TaskType = Field(..., description="任务类型")
    sources: list[RetrievalSource] = Field(..., description="允许的数据源（有限枚举）")
    required_facts: list[str] = Field(default_factory=list, description="完成任务所需的结构化字段")
    forbidden_actions: list[str] = Field(
        default_factory=list,
        description="禁止动作，如 dose_change / stop_medication / diagnosis_inference",
    )
    max_retrieval_rounds: int = Field(default=1, ge=0, le=2, description="最大检索轮数（补检索上限）")
    route_reason: str = Field(default="", description="命中规则的简短说明，仅用于轨迹摘要")


class EvidenceSource(BaseModel):
    """单条证据的来源标识，用于引用校验与患者可读来源摘要。"""

    source_id: str = Field(..., description="来源标识，如 hospital-record-001")
    record_type: str = Field(..., description="记录类型，如 visit_record / medical_record / knowledge_chunk")
    record_date: Optional[str] = Field(None, description="记录日期")
    version: str = Field(default="current", description="知识/记录版本")


class EvidenceItem(BaseModel):
    """最小证据项：回答中每个可引用事实都对应一个 EvidenceItem。

    ``source_type`` 保留旧字符串语义（patient_profile / medical_record /
    visit_record / knowledge_chunk）；``evidence_kind`` 为 Bounded Safety
    新增的证据分层（PATIENT_RECORD / REVIEWED_KNOWLEDGE /
    TRUSTED_MEDICAL_SOURCE / MODEL_KNOWLEDGE）。
    """

    evidence_id: str = Field(..., description="证据唯一 ID，如 ev-001")
    source_type: str = Field(..., description="来源类型：patient_profile / medical_record / visit_record / knowledge_chunk")
    source_id: str = Field(..., description="来源标识，如 hospital-record-001")
    record_date: Optional[str] = Field(None, description="记录日期")
    field: str = Field(..., description="事实字段名，如 allergy_history / diagnosis")
    value: str = Field(..., description="事实值（患者可读摘要，不含病历正文）")
    version: str = Field(default="current", description="记录/知识版本")
    review_status: EvidenceReviewStatus = Field(
        default=EvidenceReviewStatus.REVIEWED,
        description="审核状态；PENDING / REJECTED 不得进入默认检索结果",
    )
    evidence_kind: EvidenceSourceType = Field(
        default=EvidenceSourceType.PATIENT_RECORD,
        description="证据分层类型（Bounded Safety）",
    )
    trust_level: TrustLevel = Field(default=TrustLevel.MEDIUM, description="证据可信度")
    patient_specific: bool = Field(default=False, description="是否患者个体化证据")
    source_title: str = Field(default="", description="来源标题")
    source_uri: str = Field(default="", description="来源 URI/URL")


class EvidenceConflict(BaseModel):
    """同字段多来源不一致的证据冲突。"""

    field: str = Field(..., description="冲突字段")
    values: list[dict[str, Any]] = Field(
        ...,
        description="冲突取值列表，每项含 value / source_id / record_date",
    )
    note: str = Field(default="", description="冲突说明")


class EvidencePack(BaseModel):
    """一次检索统一转换的证据包。回答只能引用包内事实与审核知识。"""

    items: list[EvidenceItem] = Field(default_factory=list, description="结构化证据项")
    knowledge_hits: list[dict[str, Any]] = Field(
        default_factory=list,
        description="审核医学知识命中，每项含 source_id / version / content 摘要",
    )
    sources: list[EvidenceSource] = Field(default_factory=list, description="引用来源清单")
    missing_facts: list[str] = Field(default_factory=list, description="缺失的关键字段")
    conflicts: list[EvidenceConflict] = Field(default_factory=list, description="证据冲突")
    coverage: float = Field(default=0.0, ge=0.0, le=1.0, description="证据覆盖率")

    def evidence_by_kind(self, kind: EvidenceSourceType) -> list[EvidenceItem]:
        """按证据分层类型返回结构化证据项。"""
        return [item for item in self.items if item.evidence_kind is kind]

    def patient_evidence(self) -> list[EvidenceItem]:
        return self.evidence_by_kind(EvidenceSourceType.PATIENT_RECORD)

    def knowledge_by_kind(self, kind: EvidenceSourceType) -> list[dict[str, Any]]:
        """按证据分层类型返回知识命中（knowledge_hits 带 evidence_kind 标记）。"""
        return [hit for hit in self.knowledge_hits if hit.get("evidence_kind") == kind.value]

    def reviewed_knowledge(self) -> list[dict[str, Any]]:
        return self.knowledge_by_kind(EvidenceSourceType.REVIEWED_KNOWLEDGE)

    def trusted_sources(self) -> list[dict[str, Any]]:
        return self.knowledge_by_kind(EvidenceSourceType.TRUSTED_MEDICAL_SOURCE)

    def model_knowledge(self) -> list[dict[str, Any]]:
        return self.knowledge_by_kind(EvidenceSourceType.MODEL_KNOWLEDGE)

    def has_knowledge(self) -> bool:
        """是否存在任何外部/模型知识证据（reviewed / trusted / model）。"""
        return bool(self.knowledge_hits)


class EvidenceStatus(str, Enum):
    """证据充分性判定结果。"""

    SUFFICIENT = "sufficient"
    MISSING = "missing"
    CONFLICT = "conflict"
    HIGH_RISK = "high_risk"


class EvidenceJudgeVerdict(str, Enum):
    """LLM 证据法官（Evidence Judge）的判定结论（V2 双轨智能层）。"""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    CONFLICT = "conflict"
    INSUFFICIENT = "insufficient"


class ClaimBinding(BaseModel):
    """回答中关键论断与证据的显式绑定（claim → evidence_id）。"""

    claim: str = Field(..., description="论断摘要（回答派生，不含病历原文）")
    evidence_ids: list[str] = Field(default_factory=list, description="支持该论断的证据 ID")
    verdict: EvidenceJudgeVerdict = Field(..., description="该论断是否被证据支持")
    note: str = Field(default="", description="绑定说明（可选）")


class EvidenceJudgeResult(BaseModel):
    """LLM 证据法官的结构化判定结果；LLM 不可用时由确定性层兜底。"""

    verdict: EvidenceJudgeVerdict = Field(..., description="总体判定")
    claim_bindings: list[ClaimBinding] = Field(default_factory=list, description="论断→证据绑定")
    reason: str = Field(default="", description="判定摘要（不含患者隐私）")
    judge_source: str = Field(default="llm", description="llm / deterministic")
    model_version: str = Field(default="", description="判定模型版本")


class EvidenceDecision(str, Enum):
    """证据判定后的下一步决策。"""

    GENERATE = "generate"
    RETRIEVE_AGAIN = "retrieve_again"
    CLARIFY = "clarify"
    REFUSE = "refuse"
    ESCALATE = "escalate"


class EvidenceCheck(BaseModel):
    """证据充分性 / 冲突 / 风险检查结果。"""

    status: EvidenceStatus = Field(..., description="证据判定结果")
    coverage: float = Field(default=0.0, ge=0.0, le=1.0, description="证据覆盖率")
    missing_facts: list[str] = Field(default_factory=list, description="缺失的关键字段")
    conflicts: list[EvidenceConflict] = Field(default_factory=list, description="证据冲突")
    decision: EvidenceDecision = Field(..., description="下一步决策")
    attempt: int = Field(default=1, ge=1, description="当前检索轮次")
    max_attempts: int = Field(default=1, ge=1, le=2, description="允许的最大检索轮次")
    judge: Optional[EvidenceJudgeResult] = Field(None, description="LLM 证据法官判定（双轨智能层）")
    verdict_source: str = Field(default="deterministic", description="判定来源：llm / deterministic / hybrid")


class RiskLevel(str, Enum):
    """输出契约中的风险等级。"""

    ROUTINE = "routine"
    URGENT = "urgent"
    EMERGENCY = "emergency"


class NextAction(str, Enum):
    """输出契约中的建议下一步。"""

    CONTINUE_SUPPLEMENT = "continue_supplement"
    MONITOR_SYMPTOMS = "monitor_symptoms"
    VIEW_RECORDS = "view_records"
    CONTACT_DOCTOR = "contact_doctor"
    EMERGENCY_CARE = "emergency_care"


class AgentOutputContract(BaseModel):
    """每次 Agent 响应的五段输出契约。"""

    answer: str = Field(..., description="用户可读回答")
    evidence_summary: str = Field(default="", description="依据类型、日期和来源的简短说明")
    risk_level: RiskLevel = Field(default=RiskLevel.ROUTINE, description="风险等级")
    next_action: NextAction = Field(default=NextAction.VIEW_RECORDS, description="建议的下一步")
    agent_trajectory: list[dict[str, Any]] = Field(
        default_factory=list,
        description="安全阶段摘要，不含病历原文、工具参数和私有推理",
    )
