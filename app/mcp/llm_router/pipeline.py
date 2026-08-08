from __future__ import annotations

from typing import Any, Optional

from app.agent.graph import AgentGraph, AgentGraphState, AgentNode
from app.config.rulebook_knowledge import rulebook_context_for
from app.mcp.llm_router.output_contract import assemble_output_contract
from app.schemas.retrieval import (
    EvidenceCheck,
    EvidenceConflict,
    EvidenceDecision,
    EvidenceJudgeResult,
    EvidenceJudgeVerdict,
    EvidencePack,
    EvidenceStatus,
    NextAction,
    RetrievalRoute,
    RiskLevel,
    TaskType,
)
from app.services.agentic_retrieval import build_evidence_pack_from_structured_result
from app.services.citation_validator import validate_answer
from app.services.clarification import (
    MID_RELIEF,
    MID_RELIEF_QUESTION,
    QUESTION_ADVICE,
    QUESTION_FLOW,
    RELIEF_QUESTION,
    UPGRADE_GUIDANCE,
    apply_answer,
    classify_relief,
    classify_vague_symptom,
    classify_worsening,
    get_clarification_store,
    new_state,
    next_prompt,
    symptom_cleared,
)
from app.services.evidence_judge import judge_evidence
from app.services.evidence_policy import evaluate_evidence
from app.services.response_guidance import embed_escalation_guidance, personalize_response
from app.services.retrieval_router import route_question

_FACT_LABELS: dict[str, str] = {
    "allergy_history": "过敏史",
    "current_medications": "当前用药",
    "diagnosis": "诊断",
    "visit_records": "就诊记录",
    "surgeries": "手术史",
    "physician": "接诊医生",
    "emergency_contact": "紧急联系人",
    "timeline_records": "时间线记录",
    "report_facts": "报告指标",
}


def _merge_judge_verdict(
    check: EvidenceCheck,
    judge_result: Optional[EvidenceJudgeResult],
    route: Optional[RetrievalRoute],
) -> EvidenceCheck:
    """V2 双轨合并：LLM 证据法官可用时以智能判定为主，确定性为兜底。

    只允许智能层升级风险（conflict / insufficient / unsupported→拒答），
    不允许把确定性的高危/冲突结论降级为放行。
    """
    if judge_result is None:
        return check
    check.judge = judge_result
    check.verdict_source = "llm"
    verdict = judge_result.verdict
    if verdict is EvidenceJudgeVerdict.CONFLICT:
        check.status = EvidenceStatus.CONFLICT
        check.decision = EvidenceDecision.CLARIFY
        if not check.conflicts:
            check.conflicts = [
                EvidenceConflict(
                    field="llm_judge",
                    values=[],
                    note=judge_result.reason or "LLM 证据法官检测到未被规则捕获的语义冲突",
                )
            ]
    elif verdict is EvidenceJudgeVerdict.INSUFFICIENT:
        if check.status not in (EvidenceStatus.HIGH_RISK, EvidenceStatus.CONFLICT):
            check.status = EvidenceStatus.MISSING
            check.decision = EvidenceDecision.CLARIFY
    elif verdict is EvidenceJudgeVerdict.UNSUPPORTED:
        if route is not None and route.forbidden_actions:
            check.status = EvidenceStatus.HIGH_RISK
            check.decision = EvidenceDecision.REFUSE
    return check


def install_graph_pipeline(namespace: dict[str, Any]) -> None:
    """Install explicit graph entrypoints into a loaded legacy router namespace."""

    legacy_run = namespace["run_agent_tool_query"]
    executor_run = namespace["run_agent_execution"]
    evaluate_safety = namespace["evaluate_medical_safety"]
    build_safety_result = namespace["_build_safety_gate_result"]
    try_structured_fact = namespace["_try_structured_fact_query"]

    def safety_node(state: AgentGraphState) -> Optional[str]:
        decision = evaluate_safety(state.context["question"])
        if decision.blocked:
            state.note(f"blocked:{decision.action.value}")
            state.result = build_safety_result(state.context["question"], decision)
            assemble_output_contract(state.result, safety_action=decision.action.value)
            return None
        state.note("allowed")
        return "task_route"

    def task_route_node(state: AgentGraphState) -> Optional[str]:
        route = route_question(state.context["question"])
        state.context["route"] = route
        state.note(f"task:{route.task.value}:{route.route_reason}")
        # V2 澄清闭环：模糊主诉或存在进行中的追问状态时进入澄清节点
        session_id = state.context.get("session_id")
        has_active_clarification = bool(session_id) and get_clarification_store().get(session_id) is not None
        if classify_vague_symptom(state.context.get("question", "")) or has_active_clarification:
            return "clarify"
        return "retrieval"

    def _set_clarify_result(
        state: AgentGraphState,
        answer: str,
        *,
        step: int,
        completed: bool,
        upgraded: bool = False,
    ) -> None:
        result = state.context.setdefault("candidate_result", {})
        result.update(
            {
                "answer": answer,
                "intent": "clarification",
                "chosen_tool": "clarification_flow",
                "clarification_required": True,
                "clarification_completed": completed,
                "clarification_upgraded": upgraded,
                "clarification_step": step,
            }
        )
        assemble_output_contract(result)
        result["evidence_summary"] = "该回答为症状澄清追问，未使用病历数据。"
        if not upgraded:
            result["next_action"] = NextAction.CONTINUE_SUPPLEMENT.value
            result["risk_level"] = RiskLevel.ROUTINE.value
        state.result = result

    def _question_with_advice(record) -> str:
        prompt = QUESTION_FLOW[record.step_index][1]
        advice = QUESTION_ADVICE.get(QUESTION_FLOW[record.step_index][0], "")
        if advice:
            return f"明白了，先帮你记下来。{advice} {prompt}"
        return prompt

    def clarify_node(state: AgentGraphState) -> Optional[str]:
        question = state.context.get("question", "")
        session_id = state.context.get("session_id")
        store = get_clarification_store()
        record = store.get(session_id) if session_id else None

        # 首次进入：确认为模糊主诉后创建问卷并抛出第一个问题
        if record is None:
            if not classify_vague_symptom(question):
                return "retrieval"
            # 匿名会话（无 session_id）只询问第一问，不持久化状态，避免跨调用污染
            record = new_state(session_id or "__anon__", question)
            if session_id:
                store.set(record)
            _set_clarify_result(
                state,
                next_prompt(record) or RELIEF_QUESTION,
                step=record.step_index,
                completed=False,
            )
            state.note("clarify:started")
            return None

        # 任意一步：症状消失 → 清除问卷并收尾（更新语义：缓解触发整体清除）
        if symptom_cleared(question):
            store.clear(session_id)
            _set_clarify_result(
                state,
                "好的，症状已经缓解。如果后续反复或加重，请及时就医或再次联系。",
                step=record.step_index,
                completed=True,
            )
            state.note("clarify:cleared")
            return None

        # 任意一步：恶化信号 → 立即升级就医指引（按步风险评估）
        if classify_worsening(question):
            store.clear(session_id)
            _set_clarify_result(
                state,
                UPGRADE_GUIDANCE,
                step=record.step_index,
                completed=True,
                upgraded=True,
            )
            state.result["risk_level"] = RiskLevel.URGENT.value
            state.result["next_action"] = NextAction.CONTACT_DOCTOR.value
            state.note("clarify:escalated")
            return None

        # 等待中途缓解确认的回答：未缓解/无法判断都继续问卷，不在此升级
        if record.waiting_mid_relief:
            record.waiting_mid_relief = False
            store.set(record)
            _set_clarify_result(state, _question_with_advice(record), step=record.step_index, completed=False)
            state.note("clarify:continue_after_mid_relief")
            return None

        # 问卷进行中：把当前消息当作上一题的答案并推进（关键字段覆盖+变更记录）
        if not record.completed_questionnaire():
            result_prompt = apply_answer(record, question)
            if result_prompt == MID_RELIEF:
                record.waiting_mid_relief = True
                store.set(record)
                _set_clarify_result(state, MID_RELIEF_QUESTION, step=record.step_index, completed=False)
                state.note("clarify:mid_relief")
                return None
            if result_prompt is None:
                record.relief_asked = True
                store.set(record)
                _set_clarify_result(state, RELIEF_QUESTION, step=record.step_index, completed=False)
            else:
                store.set(record)
                _set_clarify_result(state, _question_with_advice(record), step=record.step_index, completed=False)
            state.note(f"clarify:step{record.step_index}")
            return None

        # 问卷完成：等待「是否缓解」最终确认
        relief = classify_relief(question)
        store.clear(session_id)
        if relief is False:
            _set_clarify_result(
                state,
                UPGRADE_GUIDANCE,
                step=len(QUESTION_FLOW),
                completed=True,
                upgraded=True,
            )
            state.result["risk_level"] = RiskLevel.URGENT.value
            state.result["next_action"] = NextAction.CONTACT_DOCTOR.value
            state.note("clarify:upgraded")
            return None
        if relief is True:
            _set_clarify_result(
                state,
                "好的，如果症状反复或加重，请及时就医或再次联系。",
                step=len(QUESTION_FLOW),
                completed=True,
            )
            state.note("clarify:relieved")
            return None
        # 无法判断是否缓解：保守升级为就医指引
        _set_clarify_result(
            state,
            UPGRADE_GUIDANCE,
            step=len(QUESTION_FLOW),
            completed=True,
            upgraded=True,
        )
        state.result["risk_level"] = RiskLevel.URGENT.value
        state.result["next_action"] = NextAction.CONTACT_DOCTOR.value
        state.note("clarify:unclear_upgraded")
        return None

    def retrieval_node(state: AgentGraphState) -> Optional[str]:
        context = state.context
        result = try_structured_fact(
            question=context["question"],
            auth_token=context["auth_token"],
            patient_id=context["patient_id"],
            hospital_id=context["hospital_id"],
        )
        if result is not None:
            state.note(f"direct:{result.get('chosen_tool', 'structured_record')}")
            state.context["candidate_result"] = result
            state.context["evidence_pack"] = build_evidence_pack_from_structured_result(
                result.get("tool_result") or {},
                state.context.get("route"),
            )
            return "evidence_check"
        state.note("no_exact_record_route")
        return "generate"

    def generate_node(state: AgentGraphState) -> Optional[str]:
        context = state.context
        if context.get("candidate_result") is not None:
            state.note("skipped:direct_evidence")
            return "evidence_check"
        # V2 规则手册知识注入：已审核处理规范优先，患者事实块随后
        rulebook = rulebook_context_for(context.get("route"))
        if rulebook:
            patient_block = context.get("conversation_context")
            merged = rulebook
            if patient_block:
                merged += "\n\n以下是从患者档案检索到的患者事实，仅用于核验，不得编造：\n" + patient_block
            context["conversation_context"] = merged

        context["candidate_result"] = executor_run(
            context["question"],
            auth_token=context["auth_token"],
            patient_id=context["patient_id"],
            hospital_id=context["hospital_id"],
            chat_mode=context["chat_mode"],
            claimed_name=context["claimed_name"],
            claimed_phone=context["claimed_phone"],
            claimed_birth_year=context["claimed_birth_year"],
            confirmed_patient_name=context["confirmed_patient_name"],
            image_bytes=context["image_bytes"],
            image_content_type=context["image_content_type"],
            image_filename=context["image_filename"],
            conversation_context=context["conversation_context"],
            allergy_drugs=context["allergy_drugs"],
            allergy_history_unknown=context["allergy_history_unknown"],
            risk_signals=context["risk_signals"],
        )
        state.note(f"route:{context['candidate_result'].get('chosen_tool', 'unknown')}")
        context.setdefault("evidence_pack", EvidencePack())
        return "evidence_check"

    def evidence_check_node(state: AgentGraphState) -> Optional[str]:
        route = state.context.get("route")
        pack = state.context.get("evidence_pack") or EvidencePack()
        attempt = int(state.context.get("attempt", 1))
        max_attempts = 2 if (route and route.max_retrieval_rounds > 0) else 1
        check = evaluate_evidence(
            pack,
            route,
            attempt=attempt,
            max_attempts=max_attempts,
            question=state.context.get("question"),
        )
        state.context["evidence_check"] = check.model_dump(mode="json")

        if check.decision is EvidenceDecision.RETRIEVE_AGAIN:
            state.context["attempt"] = attempt + 1
            state.note(f"missing_retry:{attempt}")
            return "retrieval"

        # ── V2 双轨：LLM 证据法官为主、确定性兜底（缺失重试路径不调用）──
        candidate = state.context.get("candidate_result") or {}
        try:
            judge_result = judge_evidence(
                state.context.get("question", ""),
                candidate.get("answer", ""),
                pack,
                route,
                llm=state.context.get("judge_llm"),
            )
        except Exception:
            judge_result = None
        check = _merge_judge_verdict(check, judge_result, route)
        state.context["evidence_check"] = check.model_dump(mode="json")
        if check.judge is not None:
            candidate["claim_bindings"] = [
                binding.model_dump(mode="json") for binding in check.judge.claim_bindings
            ]

        result = state.context["candidate_result"]
        if check.decision is EvidenceDecision.REFUSE:
            result["answer"] = (
                "当前记录不足以支持该问题的个体化结论，为避免误导，我不能据此回答。"
                "请核对原始病历，或向医生、药师确认。"
            )
            result["next_action"] = "contact_doctor"
            state.note("refused:high_risk")
        elif check.decision is EvidenceDecision.CLARIFY and check.missing_facts:
            missing = "、".join(_FACT_LABELS.get(fact, fact) for fact in check.missing_facts[:3])
            result["answer"] = f"{result.get('answer', '')}\n\n提示：{missing} 未能从记录中确认，请以原始记录或医生意见为准。"
            state.note("clarified:missing_evidence")
        else:
            state.note(f"evidence:{check.status.value}")
        return "citation_validate"

    def citation_validate_node(state: AgentGraphState) -> Optional[str]:
        route = state.context.get("route")
        pack = state.context.get("evidence_pack") or EvidencePack()
        result = state.context["candidate_result"]
        report = validate_answer(
            result.get("answer", ""),
            pack,
            task=route.task.value if route else None,
            claim_bindings=result.get("claim_bindings"),
        )
        state.context["citation_report"] = {
            "checked": report.checked,
            "valid": report.valid,
            "supported_count": len(report.supported_claims),
            "unsupported_count": len(report.unsupported_claims),
        }
        if route and route.task in (TaskType.MEDICATION_ALLERGY_CHECK, TaskType.RISK_TRIAGE) and not report.valid:
            result["answer"] = (
                "当前记录无法支持回答中的具体结论（存在无法核验的药物/剂量/日期表述）。"
                "请以医生或药师的确认意见为准，不要据此自行用药。"
            )
            result["next_action"] = "contact_doctor"
            state.note("citation_failed:overridden")
        else:
            state.note("citation_checked")
        return "output_assemble"

    def output_assemble_node(state: AgentGraphState) -> Optional[str]:
        result = state.context["candidate_result"]
        result["evidence_check"] = state.context["evidence_check"]
        result["citation_report"] = state.context.get("citation_report") or {
            "checked": False,
            "valid": True,
            "supported_count": 0,
            "unsupported_count": 0,
        }
        result.setdefault("claim_bindings", [])
        result.setdefault("planning", {})
        result["planning"].setdefault("graph", graph.describe())
        route = state.context.get("route")
        if route is not None:
            result["task_route"] = route.model_dump(mode="json")
        pack = state.context.get("evidence_pack")
        if pack is not None:
            result["evidence_coverage"] = pack.coverage
        assemble_output_contract(result)
        # V2 阶段 4：普通风险症状在正常回答中内嵌升级指引（不强信号不拦截）
        if result.get("risk_level") == RiskLevel.ROUTINE.value:
            guided, escalated = embed_escalation_guidance(
                result.get("answer", ""),
                state.context.get("question", ""),
            )
            if escalated == RiskLevel.URGENT.value:
                result["answer"] = guided
                result["risk_level"] = RiskLevel.URGENT.value
        # V2 阶段 6：患者偏好个性化（回答长度/术语/风险提醒强度）
        prefs = state.context.get("personalization") or {}
        if prefs:
            text, applied = personalize_response(
                result.get("answer", ""),
                risk_level=result.get("risk_level", RiskLevel.ROUTINE.value),
                preferences=prefs,
            )
            if applied.get("personalized"):
                result["answer"] = text
                result["personalization_applied"] = applied
        # 回答明确要求“医生/药师确认”时，下一步应为联系医生，而非查看记录
        if (
            route is not None
            and route.task is TaskType.MEDICATION_ALLERGY_CHECK
            and result.get("next_action") == "view_records"
            and ("医生或药师" in result.get("answer", "") or "医生确认" in result.get("answer", ""))
        ):
            result["next_action"] = "contact_doctor"
        state.result = result
        state.note("response_ready")
        return None

    graph = AgentGraph(entrypoint="safety", max_steps=10)
    graph.add_node(AgentNode("safety", "safety", "正在执行医疗安全检查...", safety_node))
    graph.add_node(AgentNode("task_route", "classify", "正在识别任务类型与检索来源...", task_route_node))
    graph.add_node(AgentNode("clarify", "clarify", "正在追问症状细节...", clarify_node))
    graph.add_node(AgentNode("retrieval", "context", "正在检查结构化病历事实...", retrieval_node))
    graph.add_node(AgentNode("generate", "agent", "正在执行受控 Agent 流程...", generate_node))
    graph.add_node(AgentNode("evidence_check", "evidence", "正在检查证据充分性...", evidence_check_node))
    graph.add_node(AgentNode("citation_validate", "evidence", "正在校验引用与依据...", citation_validate_node))
    graph.add_node(AgentNode("output_assemble", "agent", "正在整理回答...", output_assemble_node))

    def graph_context(question: str, *, on_phase=None, **kwargs: Any) -> dict[str, Any]:
        return {
            "question": question,
            "on_phase": on_phase,
            "auth_token": kwargs.get("auth_token"),
            "patient_id": kwargs.get("patient_id"),
            "hospital_id": kwargs.get("hospital_id"),
            "chat_mode": kwargs.get("chat_mode"),
            "claimed_name": kwargs.get("claimed_name"),
            "claimed_phone": kwargs.get("claimed_phone"),
            "claimed_birth_year": kwargs.get("claimed_birth_year"),
            "confirmed_patient_name": kwargs.get("confirmed_patient_name"),
            "image_bytes": kwargs.get("image_bytes"),
            "image_content_type": kwargs.get("image_content_type"),
            "image_filename": kwargs.get("image_filename"),
            "conversation_context": kwargs.get("conversation_context"),
            "allergy_drugs": kwargs.get("allergy_drugs"),
            "allergy_history_unknown": kwargs.get("allergy_history_unknown", False),
            "risk_signals": kwargs.get("risk_signals"),
            "judge_llm": kwargs.get("judge_llm"),
            "session_id": kwargs.get("session_id"),
            "personalization": kwargs.get("personalization"),
        }

    def run_graph(question: str, *, on_phase=None, **kwargs: Any) -> dict[str, Any]:
        context = graph_context(question, on_phase=on_phase, **kwargs)
        return graph.run(AgentGraphState(context=context, on_phase=on_phase))

    def run_agent_tool_query(question: str, **kwargs: Any) -> dict[str, Any]:
        return run_graph(question, **kwargs)

    def run_agent_tool_query_stream(question: str, *, on_phase=None, **kwargs: Any) -> dict[str, Any]:
        events: list[tuple[str, str]] = []

        def emit(phase: str, message: str) -> None:
            events.append((phase, message))
            if on_phase:
                on_phase(phase, message)

        result = run_graph(question, on_phase=emit, **kwargs)
        result["stream_phases"] = [
            {"phase": phase, "message": message}
            for phase, message in events
        ]
        return result

    namespace["_legacy_run_agent_tool_query"] = legacy_run
    namespace["PATIENT_CARE_AGENT_GRAPH"] = graph
    namespace["run_agent_tool_query"] = run_agent_tool_query
    namespace["run_agent_tool_query_stream"] = run_agent_tool_query_stream
