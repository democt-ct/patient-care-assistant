"""按路由检索并组装 EvidencePack（有限 Agentic RAG 第一版）。

设计依据：``docs/执行计划.md`` 阶段 C。本模块把结构化患者事实、就诊时间线和
审核临床知识统一转换成 ``EvidencePack``，回答生成只允许引用包内内容。

补检索语义：只针对明确的 ``missing_facts`` 或低覆盖字段，最多一次；
不允许因为模型“不满意答案”无限循环。
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Optional, Sequence

from app.schemas.retrieval import (
    EvidenceItem,
    EvidencePack,
    EvidenceSource,
    EvidenceSourceType,
    RetrievalRoute,
    TrustLevel,
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _item(
    *,
    evidence_id: str,
    source_type: str,
    source_id: str,
    record_date: Optional[str],
    field: str,
    value: Any,
) -> Optional[EvidenceItem]:
    text = _text(value)
    if not text:
        return None
    return EvidenceItem(
        evidence_id=evidence_id,
        source_type=source_type,
        source_id=source_id,
        record_date=record_date,
        field=field,
        value=text[:500],
        evidence_kind=EvidenceSourceType.PATIENT_RECORD,
        trust_level=TrustLevel.HIGH,
        patient_specific=True,
    )


def build_evidence_pack_from_structured_result(
    tool_result: Mapping[str, Any],
    route: RetrievalRoute,
) -> EvidencePack:
    """把结构化工具结果（患者主档 / 病历 / 就诊）转换成 EvidencePack。"""
    data = tool_result.get("data") or {}
    if not isinstance(data, Mapping):
        return EvidencePack()

    items: list[EvidenceItem] = []
    sources: list[EvidenceSource] = []

    patient = data.get("patient") or {}
    if isinstance(patient, Mapping):
        for field in ("allergy_history", "emergency_contact_name", "family_history", "blood_type"):
            item = _item(
                evidence_id=f"ev-patient-{field}",
                source_type="patient_profile",
                source_id=_text(patient.get("id")) or f"patient-{field}",
                record_date=None,
                field=field,
                value=patient.get(field),
            )
            if item:
                items.append(item)
                sources.append(EvidenceSource(
                    source_id=item.source_id,
                    record_type="patient_profile",
                    record_date=None,
                    version="current",
                ))

    for index, record in enumerate(_as_records(data.get("medical_records"))):
        record_id = _text(record.get("id")) or f"medical-record-{index + 1}"
        record_date = _text(record.get("record_date"))
        for field in ("title", "diagnosis", "medications", "treatment_plan", "department", "doctor_name"):
            item = _item(
                evidence_id=f"ev-med-{record_id}-{field}",
                source_type="medical_record",
                source_id=record_id,
                record_date=record_date or None,
                field=field,
                value=record.get(field),
            )
            if item:
                items.append(item)
        sources.append(EvidenceSource(
            source_id=record_id,
            record_type="medical_record",
            record_date=record_date or None,
            version="current",
        ))

    for index, record in enumerate(_as_records(data.get("visit_records"))):
        record_id = _text(record.get("id")) or f"visit-record-{index + 1}"
        record_date = _text(record.get("visit_date")) or _text(record.get("record_date"))
        for field in ("visit_type", "department", "doctor_name", "chief_complaint", "visit_summary", "follow_up_plan"):
            item = _item(
                evidence_id=f"ev-visit-{record_id}-{field}",
                source_type="visit_record",
                source_id=record_id,
                record_date=record_date or None,
                field=field,
                value=record.get(field),
            )
            if item:
                items.append(item)
        sources.append(EvidenceSource(
            source_id=record_id,
            record_type="visit_record",
            record_date=record_date or None,
            version="current",
        ))

    pack = EvidencePack(items=items, sources=_dedupe_sources(sources))
    return _with_coverage(pack, route)


def supplement_with_knowledge(pack: EvidencePack, knowledge_hits: Sequence[Mapping[str, Any]]) -> EvidencePack:
    """把已审核临床知识命中合并进证据包（仅 REVIEWED 状态，PENDING/REJECTED 丢弃）。"""
    reviewed = [
        {
            "source_id": _text(hit.get("source_id")) or f"knowledge-{index + 1}",
            "version": _text(hit.get("version")) or "current",
            "content": _text(hit.get("content") or hit.get("text"))[:500],
            "evidence_kind": EvidenceSourceType.REVIEWED_KNOWLEDGE.value,
        }
        for index, hit in enumerate(knowledge_hits)
        if str(hit.get("review_status", "reviewed")).lower() != "rejected"
    ]
    pack.knowledge_hits.extend(reviewed)
    pack.sources.extend(
        EvidenceSource(
            source_id=hit["source_id"],
            record_type="knowledge_chunk",
            record_date=None,
            version=hit["version"],
        )
        for hit in reviewed
    )
    pack.sources = _dedupe_sources(pack.sources)
    if not pack.items:
        pack.coverage = 1.0 if pack.knowledge_hits else 0.0
    return pack


def summarize_sources(pack: EvidencePack) -> str:
    """生成患者可读的来源摘要（类型 + 日期），不含病历原文。"""
    if not pack.sources:
        return "未检索到可引用来源。"
    parts = []
    for source in pack.sources[:3]:
        date = f"（{source.record_date}）" if source.record_date else ""
        parts.append(f"{source.record_type}{date}")
    suffix = " 等" if len(pack.sources) > 3 else ""
    return "依据来源：" + "、".join(parts) + suffix + "。"


def required_fact_covered(pack: EvidencePack, fact: str) -> bool:
    """按证据包内容判断某个必需事实是否被覆盖。"""
    items = pack.items
    if fact == "allergy_history":
        return any(item.field == "allergy_history" for item in items)
    if fact == "current_medications":
        return any(item.field == "medications" for item in items)
    if fact == "diagnosis":
        return any(item.field == "diagnosis" for item in items)
    if fact == "visit_records":
        return any(item.source_type == "visit_record" for item in items)
    if fact == "surgeries":
        return any(
            item.field in ("diagnosis", "title") and re.search(r"手术|置换|切除术|术后", item.value)
            for item in items
        )
    if fact == "physician":
        return any(item.field == "doctor_name" for item in items)
    if fact == "emergency_contact":
        return any(item.field == "emergency_contact_name" for item in items)
    if fact == "timeline_records":
        return any(bool(item.record_date) for item in items)
    if fact == "report_facts":
        return False
    return any(item.field == fact for item in items)


def _as_records(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _dedupe_sources(sources: Sequence[EvidenceSource]) -> list[EvidenceSource]:
    seen: set[tuple[str, str, Optional[str]]] = set()
    result: list[EvidenceSource] = []
    for source in sources:
        key = (source.source_id, source.record_type, source.record_date)
        if key in seen:
            continue
        seen.add(key)
        result.append(source)
    return result


def _with_coverage(pack: EvidencePack, route: RetrievalRoute) -> EvidencePack:
    required = route.required_facts
    if not required:
        pack.coverage = 1.0 if (pack.items or pack.knowledge_hits) else 0.0
        return pack

    covered = sum(1 for fact in required if required_fact_covered(pack, fact))
    pack.coverage = round(covered / len(required), 3)
    return pack
