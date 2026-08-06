"""Execute the finite retrieval sources declared by RetrievalRoute."""

from __future__ import annotations

from typing import Any, Callable, Mapping, Optional

from app.core.database import SessionLocal
from app.schemas.retrieval import EvidencePack, RetrievalRoute, RetrievalSource
from app.services.agentic_retrieval import (
    build_evidence_pack_from_agent_result,
    build_evidence_pack_from_structured_result,
    merge_evidence_packs,
    supplement_with_knowledge,
)
from app.services.memory_extraction_service import search_knowledge_chunk_hits


ToolCaller = Callable[[str, dict[str, Any]], Mapping[str, Any]]


def _identity_arguments(context: Mapping[str, Any]) -> dict[str, Any]:
    arguments: dict[str, Any] = {}
    for key in ("patient_id", "hospital_id", "auth_token"):
        if context.get(key):
            arguments[key] = context[key]
    return arguments


def _knowledge_rows(question: str, hospital_id: Optional[str]) -> list[dict[str, Any]]:
    db = SessionLocal()
    try:
        hits = search_knowledge_chunk_hits(
            db,
            query_text=question,
            hospital_id=hospital_id,
            approved_only=True,
            limit=5,
        )
        return [
            {
                "source_id": hit.chunk.source_id or hit.chunk.id,
                "version": hit.chunk.version or "current",
                "content": hit.chunk.chunk_text,
                "review_status": hit.chunk.review_status,
                "score": hit.final_score,
            }
            for hit in hits
        ]
    finally:
        db.close()


def retrieve_route_evidence(
    route: RetrievalRoute,
    context: Mapping[str, Any],
    *,
    call_tool: ToolCaller,
    attempt: int,
) -> EvidencePack:
    """Retrieve a bounded set of sources; attempt two only supplements gaps."""
    pack = EvidencePack()
    identity = _identity_arguments(context)
    has_identity = bool(identity.get("patient_id") or identity.get("auth_token"))

    structured_sources = {
        RetrievalSource.STRUCTURED_PATIENT_FACT,
        RetrievalSource.MEDICAL_TIMELINE,
    }
    if has_identity and structured_sources.intersection(route.sources):
        arguments = {**identity, "medical_record_limit": 20, "visit_limit": 20}
        result = call_tool("get_patient_profile", arguments)
        pack = merge_evidence_packs(
            pack,
            build_evidence_pack_from_structured_result(result, route),
            route,
        )

    if has_identity and RetrievalSource.CARE_PLAN_CONTEXT in route.sources:
        result = call_tool("get_my_care_plans", identity)
        pack = merge_evidence_packs(
            pack,
            build_evidence_pack_from_agent_result({"tool_result": result}, route),
            route,
        )

    if RetrievalSource.REPORT_CONTEXT in route.sources:
        pack = merge_evidence_packs(
            pack,
            build_evidence_pack_from_agent_result(
                {
                    "image_analysis": context.get("image_analysis"),
                    "image_filename": context.get("image_filename"),
                    "tool_result": {"data": context.get("report_data") or {}},
                },
                route,
            ),
            route,
        )

    # Clinical knowledge is deliberately deferred to the supplemental round
    # when patient facts are also required. Pure education retrieves it first.
    should_fetch_knowledge = (
        RetrievalSource.CLINICAL_KNOWLEDGE in route.sources
        and (attempt > 1 or not route.required_facts)
    )
    if should_fetch_knowledge:
        pack = supplement_with_knowledge(
            pack,
            _knowledge_rows(str(context.get("question") or ""), context.get("hospital_id")),
        )

    return pack
