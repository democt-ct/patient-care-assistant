from __future__ import annotations

import logging
from typing import Any, Optional

from app.agent.graph import AgentGraph, AgentGraphState, AgentNode
from app.config.official_health_knowledge import official_health_context_for
from app.config.rulebook_knowledge import rulebook_context_for
from app.config.trusted_medical_sources import trusted_medical_context_for
from app.mcp.llm_router.output_contract import assemble_output_contract
from app.schemas.retrieval import (
    Claim,
    EvidenceCheck,
    EvidenceConflict,
    EvidenceDecision,
    EvidenceJudgeResult,
    EvidenceJudgeVerdict,
    EvidencePack,
    EvidenceSourceType,
    EvidenceStatus,
    FinalDecision,
    NextAction,
    RetrievalRoute,
    RiskLevel,
    TaskContract,
    TaskType,
)
from app.services.agentic_retrieval import build_evidence_pack_from_structured_result
from app.services.citation_validator import validate_answer
from app.services.claim_extraction import extract_claims
from app.services.claim_validator import validate_claims
from app.services.clarification import (
    QUESTION_FLOW,
    UPGRADE_GUIDANCE,
    apply_answer,
    build_safe_symptom_guidance,
    classify_vague_symptom,
    classify_worsening,
    get_clarification_store,
    new_state,
    symptom_cleared,
)
from app.services.evidence_judge import judge_evidence
from app.services.evidence_policy import evaluate_evidence
from app.services.response_guidance import embed_escalation_guidance, personalize_response
from app.services.retrieval_router import route_question
from app.services.safety_policy import decide_final, enforce_claim_safety, prune_answer
from app.services.task_contract import build_task_contract, contract_summary_text

logger = logging.getLogger(__name__)

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

_PATIENT_FACT_LABELS: dict[str, str] = {
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

_SAFETY_REFUSAL_TEXT = (
    "该请求涉及个体化用药或剂量调整，超出我的权限范围，我不能给出具体方案。"
    "请携带药品名称、规格、当前用法和最近的检验结果，向开方医生或药师核实；"
    "如出现严重不适，请立即就医。"
)


def _apply_knowledge_requirement(
    check: EvidenceCheck,
    pack: EvidencePack,
    contract: Optional[TaskContract],
) -> EvidenceCheck:
    """按 Task Contract 的证据要求执行分层回退。

    回退链：REVIEWED_KNOWLEDGE → TRUSTED_MEDICAL_SOURCE → 按任务风险决定
    是否允许 MODEL_KNOWLEDGE。不再把「审核知识为空」一律当作拒答。
    """
    if contract is None:
        return check
    required_kinds = {
        requirement.evidence_type
        for requirement in contract.evidence_requirements
        if requirement.required
    }
    if (
        EvidenceSourceType.REVIEWED_KNOWLEDGE not in required_kinds
        and EvidenceSourceType.TRUSTED_MEDICAL_SOURCE not in required_kinds
    ):
        return check
    if pack.reviewed_knowledge() or pack.trusted_sources():
        return check
    if contract.fallback_strategy == "model_knowledge_limited":
        # 低风险通识允许有限 Model Knowledge 兜底（Claim 层会标记来源）
        return check
    if not pack.patient_evidence():
        check.status = EvidenceStatus.HIGH_RISK
        check.decision = EvidenceDecision.REFUSE
        return check
    check.status = EvidenceStatus.MISSING
    check.decision = EvidenceDecision.CLARIFY
    if "trusted_medical_source" not in check.missing_facts:
        check.missing_facts = [*check.missing_facts, "trusted_medical_source"]
    return check


def _build_patient_evidence_summary(pack: Optional[EvidencePack]) -> str:
    """生成患者证据摘要（只列字段标签，不含病历原文）。"""
    if pack is None:
        return ""
    patient_items = pack.patient_evidence()
    if not patient_items:
        return "未使用患者病历数据。"
    labels = []
    for item in patient_items:
        label = _PATIENT_FACT_LABELS.get(item.field)
        if label and label not in labels:
            labels.append(label)
    return "依据患者记录字段：" + "、".join(labels) + "。"


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
        state.context["contract"] = build_task_contract(route)
        state.note(f"task:{route.task.value}:{route.route_reason}")
        # V2 澄清闭环：模糊主诉或存在进行中的追问状态时进入澄清节点
        session_id = state.context.get("session_id")
        has_active_clarification = bool(session_id) and get_clarification_store().get(session_id) is not None
        if classify_vague_symptom(state.context.get("question", "")) or has_active_clarification:
            return "clarify"
        return "task_contract"

    def task_contract_node(state: AgentGraphState) -> Optional[str]:
        contract = state.context.get("contract")
        if contract is not None:
            state.note(f"contract:{contract.task_type.value}")
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
                "question": state.context.get("question", ""),
                "answer": answer,
                "intent": "clarification",
                "chosen_tool": "clarification_flow",
                "tool_arguments": {},
                "tool_result": {
                    "tool_name": "clarification_flow",
                    "success": True,
                    "data": {},
                    "message": "症状最小信息澄清",
                },
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
                QUESTION_FLOW[0][1],
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

        # 把患者补充作为上一轮追问的答案；信息满足后转入症状评估节点，
        # 而不是继续执行一组固定问题。
        if not record.completed_questionnaire():
            apply_answer(record, question)
        state.context["clarification_record"] = record
        state.note("clarify:minimum_facts_collected")
        return "symptom_assessment"

    def symptom_assessment_node(state: AgentGraphState) -> Optional[str]:
        """Close the clarification loop with safe, actionable patient guidance."""
        record = state.context.get("clarification_record")
        if record is None:
            return "retrieval"
        session_id = state.context.get("session_id")
        if session_id:
            get_clarification_store().clear(session_id)
        result = state.context.setdefault("candidate_result", {})
        result.update(
            {
                "question": state.context.get("question", ""),
                "answer": build_safe_symptom_guidance(record),
                "intent": "symptom_consultation",
                "chosen_tool": "symptom_assessment",
                "tool_arguments": {"clarification_step": record.step_index},
                "tool_result": {
                    "tool_name": "symptom_assessment",
                    "success": True,
                    "data": {"clarification_step": record.step_index},
                    "message": "已完成症状最小信息评估",
                },
                "clarification_required": True,
                "clarification_completed": True,
                "clarification_upgraded": False,
                "clarification_step": record.step_index,
                "planning": {
                    "selected_action": "provide_safe_symptom_guidance",
                    "reason": "已收集改变分流结果的最小症状信息，转为行动建议而非继续固定追问。",
                },
            }
        )
        assemble_output_contract(result)
        result["risk_level"] = RiskLevel.ROUTINE.value
        result["next_action"] = NextAction.MONITOR_SYMPTOMS.value
        result["evidence_summary"] = "依据：患者当轮症状描述；未使用病历数据，未生成个体化诊断或用药方案。"
        state.result = result
        state.note("symptom_assessment:guidance_ready")
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
            if result.get("structured_fact_missing"):
                route = state.context.get("route")
                state.context["evidence_check"] = EvidenceCheck(
                    status=EvidenceStatus.MISSING,
                    coverage=0.0,
                    missing_facts=list(route.required_facts) if route else [],
                    decision=EvidenceDecision.CLARIFY,
                    attempt=1,
                    max_attempts=1,
                ).model_dump(mode="json")
                state.note("direct:missing_record_field")
                return "output_assemble"
            # The answer is a deterministic rendering of structured records.
            # Running an LLM judge here adds latency and a network dependency
            # without contributing new evidence.
            state.context["deterministic_direct"] = True
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
        official_hits = official_health_context_for(context["question"], context.get("route"))
        trusted_hits = trusted_medical_context_for(context["question"], context.get("route"))
        if official_hits:
            official_block = "\n".join(
                f"[{item['source_name']}｜{item['title']}｜{item['version']}] {item['content']}"
                for item in official_hits
            )
            rulebook = (rulebook + "\n\n" if rulebook else "") + (
                "以下为来源已核验的公共卫生健康教育内容，仅可用于一般健康教育和就医提示，"
                "不得扩展为诊断、处方、剂量或停换药建议：\n" + official_block
            )
            context["evidence_pack"] = EvidencePack(
                knowledge_hits=[
                    {**item, "evidence_kind": EvidenceSourceType.REVIEWED_KNOWLEDGE.value}
                    for item in official_hits
                ]
            )
        if trusted_hits:
            trusted_block = "\n".join(
                f"[{item['source_name']}｜{item['title']}｜{item['version']}] {item['content']}"
                for item in trusted_hits
            )
            rulebook = (rulebook + "\n\n" if rulebook else "") + (
                "以下为来源可信的药品/指南通用信息，可用于一般解释，"
                "不得据此给出个体化剂量或治疗结论：\n" + trusted_block
            )
            pack = context.get("evidence_pack") or EvidencePack()
            pack.knowledge_hits.extend(
                {**item, "evidence_kind": EvidenceSourceType.TRUSTED_MEDICAL_SOURCE.value}
                for item in trusted_hits
            )
            context["evidence_pack"] = pack
        contract = context.get("contract")
        if contract is not None:
            contract_block = contract_summary_text(contract)
            if contract_block:
                rulebook = (rulebook + "\n\n" if rulebook else "") + contract_block
        if rulebook:
            patient_block = context.get("conversation_context")
            merged = rulebook
            if patient_block:
                merged += "\n\n以下是从患者档案检索到的患者事实，仅用于核验，不得编造：\n" + patient_block
            context["conversation_context"] = merged

        try:
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
                task_contract=contract,
            )
        except RuntimeError as exc:
            logger.warning("LLM executor unavailable; using deterministic medical fallback: %s", exc)
            context["llm_unavailable"] = True
            if official_hits:
                source_guidance = "\n".join(f"- {item['content']}" for item in official_hits)
                answer = (
                    f"根据已核验的权威健康资料，可先参考以下通用建议：\n{source_guidance}\n\n"
                    "以上属于一般健康教育，不能替代医生结合个人病史作出的诊断或治疗方案。"
                )
                chosen_tool = "official_health_knowledge_fallback"
                intent = "general_health_education"
            else:
                answer = (
                    "当前模型服务暂时无法连接，我不能在缺少可核验依据时继续生成医疗建议。"
                    "你可以稍后重试；若症状持续、加重，或出现胸痛、呼吸困难、意识异常等情况，请及时线下就医。"
                )
                chosen_tool = "model_unavailable_fallback"
                intent = "service_unavailable"
            context["candidate_result"] = {
                "question": context["question"],
                "answer": answer,
                "speech_text": answer,
                "intent": intent,
                "intent_confidence": 1.0 if official_hits else 0.0,
                "chosen_tool": chosen_tool,
                "chosen_tools": [chosen_tool],
                "tool_arguments": {},
                "tool_result": {
                    "success": bool(official_hits),
                    "data": {"source_count": len(official_hits)},
                    "message": "大模型不可用，已执行确定性安全降级",
                },
                "planning": {
                    "selected_action": chosen_tool,
                    "reason": "大模型调用失败；仅使用已核验知识，或在无依据时停止生成",
                },
            }
            state.note(f"fallback:{chosen_tool}")
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

        # Bounded Safety：知识证据分层回退（REVIEWED → TRUSTED → 任务风险决定 MODEL）
        check = _apply_knowledge_requirement(check, pack, state.context.get("contract"))
        state.context["evidence_check"] = check.model_dump(mode="json")

        # ── V2 双轨：LLM 证据法官为主、确定性兜底（缺失重试路径不调用）──
        candidate = state.context.get("candidate_result") or {}
        # A judge cannot validate an empty EvidencePack.  Calling it here adds
        # an avoidable remote-model round without increasing safety.
        judge_result = None
        if (
            (pack.items or pack.knowledge_hits)
            and not state.context.get("llm_unavailable")
            and not state.context.get("deterministic_direct")
        ):
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
        # 引用校验只负责实体级核对与 trace；整段覆盖已由 Claim 级验证替代。
        state.note("citation_checked")
        return "claim_extract"

    def claim_extract_node(state: AgentGraphState) -> Optional[str]:
        result = state.context["candidate_result"]
        answer = result.get("answer", "")
        llm_used = (
            not state.context.get("llm_unavailable")
            and not state.context.get("deterministic_direct")
        )
        claims = extract_claims(
            state.context.get("question", ""),
            answer,
            state.context.get("contract"),
            llm=state.context.get("judge_llm") if llm_used else None,
        )
        state.context["claims"] = claims
        state.note(f"claims:{len(claims)}")
        return "claim_validate"

    def claim_validate_node(state: AgentGraphState) -> Optional[str]:
        claims: list[Claim] = state.context.get("claims") or []
        pack = state.context.get("evidence_pack") or EvidencePack()
        judge = None
        evidence_check = None
        raw_check = state.context.get("evidence_check")
        if raw_check:
            try:
                evidence_check = EvidenceCheck.model_validate(raw_check)
            except Exception:
                evidence_check = None
            if evidence_check is not None and evidence_check.judge is not None:
                judge = evidence_check.judge
        claims = validate_claims(
            claims,
            pack,
            state.context.get("contract"),
            evidence_check=evidence_check,
            judge=judge,
            question=state.context.get("question"),
        )
        state.context["claims"] = claims
        state.context["evidence_check_model"] = evidence_check
        state.note(f"claims_validated:{sum(1 for c in claims if c.support_status.value == 'supported')}")
        return "safety_enforce"

    def safety_enforce_node(state: AgentGraphState) -> Optional[str]:
        claims: list[Claim] = state.context.get("claims") or []
        contract = state.context.get("contract")
        result = state.context["candidate_result"]
        claims = enforce_claim_safety(claims, contract)
        state.context["claims"] = claims
        evidence_check = state.context.get("evidence_check_model")
        decision, reasons = decide_final(
            claims,
            evidence_check=evidence_check,
            contract=contract,
            question=state.context.get("question", ""),
            deterministic_direct=bool(state.context.get("deterministic_direct")),
        )
        if (
            decision is FinalDecision.REFUSE
            and any("prohibited" in reason for reason in reasons)
        ):
            result["answer"] = _SAFETY_REFUSAL_TEXT
            state.note("refused:prohibited_action")
        elif decision is FinalDecision.PARTIAL and not state.context.get("deterministic_direct"):
            pruned_answer, prune_notes = prune_answer(
                result.get("answer", ""),
                claims,
                decision,
                reasons,
            )
            result["answer"] = pruned_answer
            reasons = [*reasons, *prune_notes]
        result["decision"] = decision.value
        result["decision_reasons"] = reasons
        state.context["final_decision"] = decision
        state.note(f"decision:{decision.value}")
        return "final_decision"

    def final_decision_node(state: AgentGraphState) -> Optional[str]:
        decision = state.context.get("final_decision")
        result = state.context["candidate_result"]
        if decision is FinalDecision.ESCALATE:
            result["risk_level"] = RiskLevel.URGENT.value
            result["next_action"] = NextAction.CONTACT_DOCTOR.value
        elif decision is FinalDecision.CLARIFY:
            if result.get("next_action") not in (NextAction.CONTACT_DOCTOR.value,):
                result["next_action"] = NextAction.CONTINUE_SUPPLEMENT.value
        elif decision is FinalDecision.REFUSE:
            result["risk_level"] = RiskLevel.URGENT.value
            result["next_action"] = NextAction.CONTACT_DOCTOR.value
        state.note("decision_applied")
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
        claims = state.context.get("claims")
        if claims:
            result["claim_bindings"] = [claim.model_dump(mode="json") for claim in claims]
        result.setdefault("planning", {})
        result["planning"].setdefault("graph", graph.describe())
        route = state.context.get("route")
        if route is not None:
            result["task_route"] = route.model_dump(mode="json")
        pack = state.context.get("evidence_pack")
        if pack is not None:
            evidence_check = state.context.get("evidence_check") or {}
            result["evidence_coverage"] = evidence_check.get("coverage", pack.coverage)
            result["patient_evidence_summary"] = _build_patient_evidence_summary(pack)
            knowledge_sources = [
                {
                    key: hit.get(key)
                    for key in ("source_id", "source_name", "source_url", "version", "title")
                    if hit.get(key)
                }
                for hit in pack.knowledge_hits
                if isinstance(hit, dict)
            ]
            if knowledge_sources:
                result["knowledge_sources"] = knowledge_sources
                source_labels = [
                    f"{source.get('source_name', '权威机构')}《{source.get('title', '健康科普')}》"
                    for source in knowledge_sources
                ]
                result.setdefault("evidence_summary", f"回答依据：{'；'.join(source_labels)}。")
        assemble_output_contract(result)
        if result.get("structured_fact_missing"):
            # Preserve the deterministic absence response rather than letting
            # generic contract defaults turn it into an open-ended follow-up.
            result["next_action"] = NextAction.CONTACT_DOCTOR.value
            result["risk_level"] = RiskLevel.ROUTINE.value
            result.setdefault("decision", FinalDecision.CLARIFY.value)
            result.setdefault("decision_reasons", ["structured_fact_missing"])
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

    graph = AgentGraph(entrypoint="safety", max_steps=16)
    graph.add_node(AgentNode("safety", "safety", "正在执行医疗安全检查...", safety_node))
    graph.add_node(AgentNode("task_route", "classify", "正在识别任务类型与检索来源...", task_route_node))
    graph.add_node(AgentNode("task_contract", "classify", "正在构建任务契约...", task_contract_node))
    graph.add_node(AgentNode("clarify", "clarify", "正在追问症状细节...", clarify_node))
    graph.add_node(AgentNode("symptom_assessment", "agent", "正在评估症状并整理下一步...", symptom_assessment_node))
    graph.add_node(AgentNode("retrieval", "context", "正在检查结构化病历事实...", retrieval_node))
    graph.add_node(AgentNode("generate", "agent", "正在执行受控 Agent 流程...", generate_node))
    graph.add_node(AgentNode("evidence_check", "evidence", "正在检查证据充分性...", evidence_check_node))
    graph.add_node(AgentNode("citation_validate", "evidence", "正在校验引用与依据...", citation_validate_node))
    graph.add_node(AgentNode("claim_extract", "evidence", "正在提取回答论断...", claim_extract_node))
    graph.add_node(AgentNode("claim_validate", "evidence", "正在逐条验证论断...", claim_validate_node))
    graph.add_node(AgentNode("safety_enforce", "evidence", "正在执行安全策略...", safety_enforce_node))
    graph.add_node(AgentNode("final_decision", "evidence", "正在形成最终决策...", final_decision_node))
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
