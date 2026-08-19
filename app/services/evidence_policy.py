"""证据充分性、冲突与高风险判定（确定性优先）。

设计依据：``docs/执行计划.md`` 阶段 C。决策优先级固定为：
``emergency → high_risk → conflict → missing → sufficient``。
紧急分流由安全门禁负责；本模块负责门禁放行后的证据策略。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Optional

from app.schemas.retrieval import (
    EvidenceCheck,
    EvidenceConflict,
    EvidenceDecision,
    EvidencePack,
    EvidenceStatus,
    RetrievalRoute,
    TaskType,
)
from app.services.agentic_retrieval import required_fact_covered
from app.services.task_contract import canonical_task

_CLINICAL_REFUSE_TASKS = {
    TaskType.MEDICATION_DOSING,
    TaskType.MEDICATION_RECONCILIATION,
    TaskType.CLINICAL_DECISION,
    TaskType.MEDICATION_ALLERGY_CHECK,
    TaskType.RISK_TRIAGE,
}

# 只有这些字段在同一值域出现不同值时才判定为“来源冲突”；
# 用药剂量随日期调整属于纵向变化，不自动判为冲突。
_CONFLICT_SENSITIVE_FIELDS = ("allergy_history", "emergency_contact_name", "diagnosis")


def detect_conflicts(pack: EvidencePack) -> list[EvidenceConflict]:
    """检测同字段、同日期不同来源的不一致记录。

    跨日期的诊断/用药变化属于纵向变化（病情进展、剂量调整），不自动判为冲突，
    避免把多就诊记录的正常差异误报成冲突。
    """
    dated: dict[tuple[str, str], list] = defaultdict(list)
    undated: dict[str, list] = defaultdict(list)
    for item in pack.items:
        if item.field not in _CONFLICT_SENSITIVE_FIELDS:
            continue
        if item.record_date:
            dated[(item.field, item.record_date)].append(item)
        else:
            undated[item.field].append(item)

    conflicts: list[EvidenceConflict] = []
    for (field, _date), items in sorted(dated.items()):
        _append_conflict(conflicts, field, items, note=f"{field} 在同一日期的不同来源记录中不一致")
    for field, items in sorted(undated.items()):
        _append_conflict(conflicts, field, items, note=f"{field} 在患者主档/无日期来源中不一致")
    return conflicts


def _append_conflict(
    conflicts: list[EvidenceConflict],
    field: str,
    items: list,
    *,
    note: str,
) -> None:
    distinct: dict[str, object] = {}
    for item in items:
        key = item.value.strip()
        if key not in distinct:
            distinct[key] = item
    if len(distinct) > 1:
        conflicts.append(
            EvidenceConflict(
                field=field,
                values=[
                    {
                        "value": item.value,
                        "source_id": item.source_id,
                        "record_date": item.record_date,
                    }
                    for item in distinct.values()
                ],
                note=note,
            )
        )


def _detect_allergy_ambiguity(pack: EvidencePack, question: Optional[str] = None) -> list[EvidenceConflict]:
    """主档同时出现“过敏”与“慎用”时视为边界冲突（如青霉素过敏 + 头孢慎用）。

    仅在问题与过敏/用药相关时触发，避免把无关查询（如问医生是谁）误判为冲突。
    """
    conflicts: list[EvidenceConflict] = []
    if question is not None and not any(
        keyword in question for keyword in ("过敏", "头孢", "慎用")
    ):
        return conflicts
    for item in pack.items:
        if item.field == "allergy_history" and "慎用" in item.value:
            conflicts.append(
                EvidenceConflict(
                    field="allergy_history",
                    values=[
                        {
                            "value": item.value,
                            "source_id": item.source_id,
                            "record_date": item.record_date,
                        }
                    ],
                    note="主档同时记录过敏与慎用，属于需要医生确认的边界情况",
                )
            )
    return conflicts


def evaluate_evidence(
    pack: EvidencePack,
    route: RetrievalRoute,
    *,
    attempt: int = 1,
    max_attempts: Optional[int] = None,
    question: Optional[str] = None,
) -> EvidenceCheck:
    """判定证据状态并给出下一步决策。

    - 危险任务（含 forbidden_actions）且零证据 → ``high_risk`` / 拒答。
    - 存在来源冲突 → ``conflict`` / 澄清（列双方来源与日期）。
    - 缺失必需事实且还有补检索额度 → ``missing`` / 补检索一次。
    - 缺失但已到上限 → ``missing`` / 澄清。
    - 其余 → ``sufficient`` / 生成。
    """
    required = route.required_facts
    missing = [fact for fact in required if not required_fact_covered(pack, fact)]
    conflicts = [*detect_conflicts(pack), *_detect_allergy_ambiguity(pack, question)]
    coverage = (
        round(1.0 - len(missing) / len(required), 3)
        if required
        else (1.0 if (pack.items or pack.knowledge_hits) else 0.0)
    )
    max_attempts = min(max_attempts or (2 if route.max_retrieval_rounds > 0 else 1), 2)
    has_evidence = bool(pack.items or pack.knowledge_hits)

    if (
        route.forbidden_actions
        and required
        and not has_evidence
        and canonical_task(route.task) in _CLINICAL_REFUSE_TASKS
    ):
        status, decision = EvidenceStatus.HIGH_RISK, EvidenceDecision.REFUSE
    elif conflicts:
        status, decision = EvidenceStatus.CONFLICT, EvidenceDecision.CLARIFY
    elif missing and attempt < max_attempts:
        status, decision = EvidenceStatus.MISSING, EvidenceDecision.RETRIEVE_AGAIN
    elif missing:
        status, decision = EvidenceStatus.MISSING, EvidenceDecision.CLARIFY
    else:
        status, decision = EvidenceStatus.SUFFICIENT, EvidenceDecision.GENERATE

    return EvidenceCheck(
        status=status,
        coverage=coverage,
        missing_facts=missing,
        conflicts=conflicts,
        decision=decision,
        attempt=attempt,
        max_attempts=max_attempts,
    )
