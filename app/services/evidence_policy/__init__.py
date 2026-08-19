"""Source-aware evidence policy extensions."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

_legacy_path = Path(__file__).resolve().parent.parent / "evidence_policy.py"
exec(compile(_legacy_path.read_bytes(), str(_legacy_path), "exec"), globals(), globals())

_legacy_evaluate_evidence = evaluate_evidence


def evaluate_evidence(
    pack: EvidencePack, route: RetrievalRoute, *, attempt: int = 1,
    max_attempts: Optional[int] = None, question: Optional[str] = None,
) -> EvidenceCheck:
    check = _legacy_evaluate_evidence(
        pack, route, attempt=attempt, max_attempts=max_attempts, question=question,
    )
    max_attempts = min(max_attempts or 2, 2)
    strict_current_routes = {
        "current_medications_lookup", "individualized_medication_decision",
        "drug_usage_check", "patient_specific_medication_context",
    }
    if (
        "current_medications" in route.required_facts
        and route.route_reason in strict_current_routes
        and not any(item.field == "current_medications" for item in pack.items)
    ):
        missing = list(dict.fromkeys([*check.missing_facts, "current_medications"]))
        return EvidenceCheck(
            status=EvidenceStatus.MISSING, coverage=min(check.coverage, 0.5),
            missing_facts=missing, conflicts=check.conflicts,
            decision=EvidenceDecision.RETRIEVE_AGAIN if attempt < max_attempts else EvidenceDecision.CLARIFY,
            attempt=attempt, max_attempts=max_attempts,
        )
    return check
