"""证据包组装（agentic_retrieval）的确定性测试。"""

from app.schemas.retrieval import RetrievalRoute, RetrievalSource, TaskType
from app.services.agentic_retrieval import (
    build_evidence_pack_from_structured_result,
    required_fact_covered,
    supplement_with_knowledge,
)


def _route():
    return RetrievalRoute(
        task=TaskType.FACT_VERIFICATION,
        sources=[RetrievalSource.STRUCTURED_PATIENT_FACT],
        required_facts=["diagnosis", "visit_records", "surgeries", "physician", "emergency_contact"],
        forbidden_actions=["diagnosis_inference"],
        max_retrieval_rounds=0,
    )


def test_structured_result_builds_evidence_pack():
    tool_result = {
        "success": True,
        "data": {
            "patient": {"id": "p-1", "emergency_contact_name": "陈梅（配偶）"},
            "medical_records": [
                {"id": "mr-1", "record_date": "2025-12-01", "diagnosis": "原发性高血压 2级", "doctor_name": "王志强"},
            ],
            "visit_records": [
                {"id": "vr-1", "visit_date": "2025-12-01", "department": "心内科", "doctor_name": "王志强"},
            ],
        },
    }

    pack = build_evidence_pack_from_structured_result(tool_result, _route())

    assert required_fact_covered(pack, "diagnosis")
    assert required_fact_covered(pack, "visit_records")
    assert required_fact_covered(pack, "physician")
    assert required_fact_covered(pack, "emergency_contact")
    assert not required_fact_covered(pack, "surgeries")
    assert pack.coverage == 0.8
    assert any(item.field == "diagnosis" and item.value == "原发性高血压 2级" for item in pack.items)


def test_surgery_requires_explicit_record():
    tool_result = {
        "data": {
            "medical_records": [
                {"id": "mr-1", "record_date": "2025-10-05", "title": "左膝关节置换术后住院记录"},
            ],
        },
    }
    pack = build_evidence_pack_from_structured_result(tool_result, _route())

    assert required_fact_covered(pack, "surgeries")


def test_knowledge_supplement_keeps_reviewed_only():
    pack = build_evidence_pack_from_structured_result({"data": {}}, _route())
    supplemented = supplement_with_knowledge(
        pack,
        [
            {"source_id": "k-1", "version": "2026.1", "content": "过敏与用药禁忌", "review_status": "reviewed"},
            {"source_id": "k-2", "version": "2025.9", "content": "未审核内容", "review_status": "pending"},
            {"source_id": "k-3", "version": "2025.8", "content": "被拒内容", "review_status": "rejected"},
        ],
    )

    # 设计约束：只有已审核（reviewed/approved）知识可进入默认检索结果
    assert len(supplemented.knowledge_hits) == 1
    assert {hit["source_id"] for hit in supplemented.knowledge_hits} == {"k-1"}
