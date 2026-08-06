"""Extended evidence builders for the Agentic RAG pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

_legacy_path = Path(__file__).resolve().parent.parent / "agentic_retrieval.py"
exec(compile(_legacy_path.read_bytes(), str(_legacy_path), "exec"), globals(), globals())


def build_evidence_pack_from_agent_result(result: Mapping[str, Any], route: RetrievalRoute) -> EvidencePack:
    tool_result = result.get("tool_result") or {}
    pack = build_evidence_pack_from_structured_result(
        tool_result if isinstance(tool_result, Mapping) else {}, route,
    )
    data = tool_result.get("data") if isinstance(tool_result, Mapping) else None
    data = data if isinstance(data, Mapping) else {}

    image_analysis = _text(result.get("image_analysis") or data.get("image_analysis"))
    if image_analysis:
        item = _item(
            evidence_id="ev-report-analysis", source_type="report_context",
            source_id=_text(result.get("image_filename")) or "uploaded-report",
            record_date=None, field="report_facts", value=image_analysis,
        )
        if item:
            pack.items.append(item)
            pack.sources.append(EvidenceSource(
                source_id=item.source_id, record_type="report_context", version="current",
            ))

    for index, plan in enumerate(_as_records(data.get("care_plans"))):
        plan_id = _text(plan.get("id")) or f"care-plan-{index + 1}"
        for field in ("title", "status", "pending_count", "overdue_count"):
            item = _item(
                evidence_id=f"ev-care-{plan_id}-{field}", source_type="care_plan",
                source_id=plan_id, record_date=None, field=field, value=plan.get(field),
            )
            if item:
                pack.items.append(item)
        pack.sources.append(EvidenceSource(
            source_id=plan_id, record_type="care_plan", version="current",
        ))
    pack.sources = _dedupe_sources(pack.sources)
    return _with_coverage(pack, route)


def merge_evidence_packs(base: EvidencePack, extra: EvidencePack, route: RetrievalRoute) -> EvidencePack:
    seen_items = {item.evidence_id for item in base.items}
    for item in extra.items:
        if item.evidence_id not in seen_items:
            base.items.append(item)
            seen_items.add(item.evidence_id)
    seen_knowledge = {
        (str(hit.get("source_id")), str(hit.get("version")), str(hit.get("content")))
        for hit in base.knowledge_hits
    }
    for hit in extra.knowledge_hits:
        key = (str(hit.get("source_id")), str(hit.get("version")), str(hit.get("content")))
        if key not in seen_knowledge:
            base.knowledge_hits.append(hit)
            seen_knowledge.add(key)
    base.sources = _dedupe_sources([*base.sources, *extra.sources])
    return _with_coverage(base, route)


def supplement_with_knowledge(pack: EvidencePack, knowledge_hits: Sequence[Mapping[str, Any]]) -> EvidencePack:
    reviewed = [
        {
            "source_id": _text(hit.get("source_id")) or f"knowledge-{index + 1}",
            "version": _text(hit.get("version")) or "current",
            "content": _text(hit.get("content") or hit.get("text"))[:500],
        }
        for index, hit in enumerate(knowledge_hits)
        if str(hit.get("review_status", "")).strip().lower() in {"approved", "reviewed"}
        and _text(hit.get("content") or hit.get("text"))
    ]
    pack.knowledge_hits.extend(reviewed)
    pack.sources.extend(EvidenceSource(
        source_id=hit["source_id"], record_type="knowledge_chunk", version=hit["version"],
    ) for hit in reviewed)
    pack.sources = _dedupe_sources(pack.sources)
    return pack

