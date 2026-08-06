"""任务分类与检索路由（确定性优先，LLM 兜底预留）。

设计依据：``docs/patient_medical_information_agent_design.md`` 第 4.1 节与
``docs/执行计划.md`` 阶段 B。第一版使用关键词/正则规则覆盖四个黄金场景
（病历事实核验、用药与过敏核对、高风险分流、证据不足与冲突），输出
``RetrievalRoute``：任务、允许数据源、所需字段、禁止动作与补检索上限。

路由只负责【证据规划】，不决定调用哪个 MCP 工具；旧 ``chosen_tool`` 只负责
执行适配，两者不构成双重路由。LLM 分类器作为后续可插拔兜底，默认不启用，
保证离线与测试环境行为确定。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Optional

from app.schemas.retrieval import RetrievalRoute, RetrievalSource, TaskType


@dataclass(frozen=True)
class _TaskSpec:
    task: TaskType
    sources: tuple[RetrievalSource, ...]
    required_facts: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    max_retrieval_rounds: int
    patterns: tuple[str, ...]
    route_reason: str

    def to_route(self) -> RetrievalRoute:
        return RetrievalRoute(
            task=self.task,
            sources=list(self.sources),
            required_facts=list(self.required_facts),
            forbidden_actions=list(self.forbidden_actions),
            max_retrieval_rounds=self.max_retrieval_rounds,
            route_reason=self.route_reason,
        )


# 规则按优先级排列：高风险分流 → 药物教育 → 用药过敏 → 报告理解 → 纵向比较 →
# 就医准备 → 一般健康教育 → 病历事实（按子类型）→ 兜底。
_SPECS: tuple[_TaskSpec, ...] = (
    _TaskSpec(
        task=TaskType.RISK_TRIAGE,
        sources=(RetrievalSource.NO_RETRIEVAL,),
        required_facts=(),
        forbidden_actions=("self_treatment", "diagnosis"),
        max_retrieval_rounds=0,
        patterns=(
            r"胸痛|胸闷.{0,6}呼吸|呼吸困难|喘不上气|窒息|意识不清|昏迷|晕倒|晕厥|"
            r"大出血|抽搐|惊厥|口角歪斜|一侧肢体.{0,4}无力|卒中|中风|心梗|心肌梗死|"
            r"大量出血|喘不过气",
        ),
        route_reason="detected_emergency_or_urgent_symptom",
    ),
    # 一般药物教育（非个体化）：了解药物用途、副作用、一般用法等。
    # 与"用药过敏核对"的区别：个体化剂量/停药/换药仍归用药核对并拦截。
    _TaskSpec(
        task=TaskType.GENERAL_HEALTH_EDUCATION,
        sources=(RetrievalSource.CLINICAL_KNOWLEDGE,),
        required_facts=(),
        forbidden_actions=("individualized_advice",),
        max_retrieval_rounds=1,
        patterns=(
            r"(?:阿莫西林|头孢|青霉素|磺胺|布洛芬|阿司匹林|硝酸甘油|缬沙坦|氨氯地平|"
            r"二甲双胍|格列美脲|奥美拉唑|塞来昔布|他汀|药).{0,10}"
            r"(?:是治什么的|治什么|有什么用|作用|功效|副作用|不良反应|注意事项|禁忌|"
            r"什么时候吃|怎么吃|怎么用|用法|饭前|饭后|空腹|随餐|一天几次|一日几次)",
        ),
        route_reason="drug_education_keywords",
    ),
    # 用药与过敏核对按子类型拆分：过敏查询、当前用药、个体化决策、具体药品用法。
    _TaskSpec(
        task=TaskType.MEDICATION_ALLERGY_CHECK,
        sources=(RetrievalSource.STRUCTURED_PATIENT_FACT, RetrievalSource.CLINICAL_KNOWLEDGE),
        required_facts=("allergy_history",),
        forbidden_actions=("dose_change", "stop_medication", "start_medication", "drug_switch"),
        max_retrieval_rounds=1,
        patterns=(r"过敏",),
        route_reason="medication_allergy_lookup",
    ),
    _TaskSpec(
        task=TaskType.MEDICATION_ALLERGY_CHECK,
        sources=(RetrievalSource.STRUCTURED_PATIENT_FACT,),
        required_facts=("current_medications",),
        forbidden_actions=("dose_change", "stop_medication", "start_medication", "drug_switch"),
        max_retrieval_rounds=1,
        patterns=(r"吃什么药|什么药|用药|药物|现在吃|平时吃",),
        route_reason="current_medications_lookup",
    ),
    _TaskSpec(
        task=TaskType.MEDICATION_ALLERGY_CHECK,
        sources=(RetrievalSource.STRUCTURED_PATIENT_FACT, RetrievalSource.CLINICAL_KNOWLEDGE),
        required_facts=("allergy_history", "current_medications"),
        forbidden_actions=("dose_change", "stop_medication", "start_medication", "drug_switch"),
        max_retrieval_rounds=1,
        patterns=(
            r"停药|减量|加量|换药|吃几片|吃多少|剂量|漏服|相互作用|一起吃|同时吃|配伍",
        ),
        route_reason="individualized_medication_decision",
    ),
    _TaskSpec(
        task=TaskType.MEDICATION_ALLERGY_CHECK,
        sources=(RetrievalSource.STRUCTURED_PATIENT_FACT,),
        required_facts=("current_medications",),
        forbidden_actions=("dose_change", "stop_medication", "start_medication", "drug_switch"),
        max_retrieval_rounds=1,
        patterns=(
            r"(?:阿莫西林|头孢|青霉素|磺胺|布洛芬|阿司匹林|硝酸甘油|缬沙坦|氨氯地平|"
            r"二甲双胍|格列美脲|奥美拉唑|塞来昔布).{0,6}(?:可以吃|能不能吃|能吃|可以用|能用|可以)",
        ),
        route_reason="drug_usage_check",
    ),
    _TaskSpec(
        task=TaskType.MEDICATION_ALLERGY_CHECK,
        sources=(RetrievalSource.STRUCTURED_PATIENT_FACT,),
        required_facts=("current_medications",),
        forbidden_actions=("dose_change", "stop_medication", "start_medication", "drug_switch"),
        max_retrieval_rounds=1,
        patterns=(
            r"阿莫西林|头孢|青霉素|磺胺|布洛芬|阿司匹林|硝酸甘油|缬沙坦|氨氯地平|"
            r"二甲双胍|格列美脲|奥美拉唑|塞来昔布|他汀",
        ),
        route_reason="drug_name_keywords",
    ),
    _TaskSpec(
        task=TaskType.REPORT_COMPREHENSION,
        sources=(RetrievalSource.REPORT_CONTEXT, RetrievalSource.CLINICAL_KNOWLEDGE),
        required_facts=("report_facts",),
        forbidden_actions=("diagnosis_inference", "treatment_recommendation"),
        max_retrieval_rounds=1,
        patterns=(
            r"报告|化验单|检查结果|指标|报告单|影像|b超|彩超|ct|核磁|血常规|尿常规|"
            r"糖化血红蛋白|hba1c|肌酐|转氨酶",
        ),
        route_reason="report_or_lab_keywords",
    ),
    _TaskSpec(
        task=TaskType.LONGITUDINAL_COMPARISON,
        sources=(RetrievalSource.MEDICAL_TIMELINE, RetrievalSource.STRUCTURED_PATIENT_FACT),
        required_facts=("timeline_records",),
        forbidden_actions=("diagnosis_inference",),
        max_retrieval_rounds=1,
        patterns=(
            r"和上次|跟上次|相比|变化|对比|趋势|之前.{0,8}这次|这次.{0,8}之前|下降|升高",
        ),
        route_reason="comparison_or_trend_keywords",
    ),
    _TaskSpec(
        task=TaskType.VISIT_PREPARATION,
        sources=(RetrievalSource.STRUCTURED_PATIENT_FACT, RetrievalSource.MEDICAL_TIMELINE),
        required_facts=("visit_records", "diagnosis", "medications"),
        forbidden_actions=(),
        max_retrieval_rounds=1,
        patterns=(
            r"问医生|问题清单|就医准备|要问什么|就诊准备|整理.{0,6}(问题|事项)",
        ),
        route_reason="visit_preparation_keywords",
    ),
    _TaskSpec(
        task=TaskType.GENERAL_HEALTH_EDUCATION,
        sources=(RetrievalSource.CLINICAL_KNOWLEDGE,),
        required_facts=(),
        forbidden_actions=("individualized_advice",),
        max_retrieval_rounds=1,
        patterns=(
            r"注意什么|日常生活中|日常|饮食|运动|生活方式|一般.{0,4}(注意|建议)|"
            r"科普|是什么病|什么是|应该怎么办|怎么处理",
        ),
        route_reason="general_health_education_keywords",
    ),
    # 病历事实核验按子类型拆分，required_facts 只取本类问题所需字段，
    # 避免"查一个医生还要有手术史"导致的不必要澄清/拒答。
    _TaskSpec(
        task=TaskType.FACT_VERIFICATION,
        sources=(RetrievalSource.STRUCTURED_PATIENT_FACT,),
        required_facts=("emergency_contact",),
        forbidden_actions=("diagnosis_inference",),
        max_retrieval_rounds=0,
        patterns=(r"紧急联系人",),
        route_reason="fact_contact_lookup",
    ),
    _TaskSpec(
        task=TaskType.FACT_VERIFICATION,
        sources=(RetrievalSource.STRUCTURED_PATIENT_FACT,),
        required_facts=("visit_records", "physician"),
        forbidden_actions=("diagnosis_inference",),
        max_retrieval_rounds=0,
        patterns=(
            r"医生是谁|看病的医生|就诊医生|接诊医生|复诊|最近一次|上次(?:去|看|在|是|发热)|"
            r"什么时候(?:看过|去过|检查)",
        ),
        route_reason="fact_visit_lookup",
    ),
    _TaskSpec(
        task=TaskType.FACT_VERIFICATION,
        sources=(RetrievalSource.STRUCTURED_PATIENT_FACT,),
        required_facts=("surgeries",),
        forbidden_actions=("diagnosis_inference",),
        max_retrieval_rounds=0,
        patterns=(r"手术",),
        route_reason="fact_surgery_lookup",
    ),
    _TaskSpec(
        task=TaskType.FACT_VERIFICATION,
        sources=(RetrievalSource.STRUCTURED_PATIENT_FACT,),
        required_facts=("diagnosis",),
        forbidden_actions=("diagnosis_inference",),
        max_retrieval_rounds=0,
        patterns=(
            r"诊断过|确诊过|什么病|疾病|诊断|血糖|血压",
        ),
        route_reason="fact_diagnosis_lookup",
    ),
)

_FALLBACK_SPEC = _TaskSpec(
    task=TaskType.GENERAL_HEALTH_EDUCATION,
    sources=(RetrievalSource.CLINICAL_KNOWLEDGE,),
    required_facts=(),
    forbidden_actions=("individualized_advice",),
    max_retrieval_rounds=1,
    patterns=(),
    route_reason="fallback_non_individualized",
)


def route_question(question: str, *, context: Optional[Mapping[str, object]] = None) -> RetrievalRoute:
    """将用户问题归入任务类型并返回检索路由。

    参数 ``context`` 预留给会话上下文 / 历史任务（如图片上传、对话记忆），
    第一版不参与判定，保持纯确定性。
    """
    text = (question or "").strip().lower()
    for spec in _SPECS:
        if any(re.search(pattern, text) for pattern in spec.patterns):
            return spec.to_route()
    return _FALLBACK_SPEC.to_route()


def route_for_task(task: TaskType) -> RetrievalRoute:
    """按任务类型返回默认路由（供评估用例与测试构造证据计划）。"""
    for spec in _SPECS:
        if spec.task is task:
            return spec.to_route()
    if _FALLBACK_SPEC.task is task:
        return _FALLBACK_SPEC.to_route()
    raise ValueError(f"Unknown task type: {task}")
