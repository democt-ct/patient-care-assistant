"""Basic tests for knowledge retrieval.

These tests verify the knowledge retriever can initialize
and handle basic operations.
"""

import pytest
from datetime import datetime
from pydantic import ValidationError

from app.models.memory_knowledge_chunk import MemoryKnowledgeChunk
from app.services.memory_extraction_service import list_knowledge_chunks
from app.schemas.memory_extraction import MemoryKnowledgeChunkCreate


class TestKnowledgeRetrieverInit:
    """Test that the knowledge retriever singleton and warmup work."""

    def test_get_retriever(self):
        """Verify the singleton getter returns a valid instance."""
        from app.services.knowledge_retrieval import get_knowledge_retriever

        retriever = get_knowledge_retriever()
        assert retriever is not None
        assert hasattr(retriever, "build_context")
        assert hasattr(retriever, "search")

    def test_warmup(self):
        """Warmup should not raise (handles missing ChromaDB gracefully)."""
        from app.services.knowledge_retrieval import get_knowledge_retriever

        retriever = get_knowledge_retriever()
        retriever.warmup()  # Should succeed silently even without ChromaDB

    def test_search_with_empty_store(self, db_session):
        """Search with no knowledge chunks should return empty results."""
        from app.services.knowledge_retrieval import get_knowledge_retriever

        retriever = get_knowledge_retriever()
        results = retriever.search(
            db=db_session,
            query_text="测试查询",
            hospital_id="hosp-a",
            limit=5,
        )
        assert isinstance(results, list)


def test_approved_only_listing_excludes_unreviewed_chunks(db_session):
    db_session.add_all(
        [
            MemoryKnowledgeChunk(
                domain="medication",
                title="Unreviewed draft",
                chunk_text="Draft content",
                source_type="guideline",
            ),
            MemoryKnowledgeChunk(
                domain="medication",
                title="Reviewed source",
                chunk_text="Reviewed content",
                source_type="drug_label",
                source_id="nmpa_drug_label",
                source_ref="NMPA-EXAMPLE-001",
                source_url="https://www.nmpa.gov.cn/example/label",
                review_status="approved",
                reviewed_by="clinical-reviewer",
                reviewed_at=datetime(2026, 7, 23),
            ),
        ]
    )
    db_session.commit()

    chunks = list_knowledge_chunks(db_session, approved_only=True)

    assert len(chunks) == 1
    assert chunks[0].source_ref == "NMPA-EXAMPLE-001"


def test_approved_knowledge_requires_review_provenance():
    with pytest.raises(ValidationError):
        MemoryKnowledgeChunkCreate(
            domain="medication",
            title="Untraceable approved knowledge",
            chunk_text="Content",
            source_type="guideline",
            review_status="approved",
        )
def test_knowledge_listing_defaults_to_approved_and_production_enforces_it(db_session, monkeypatch):
    db_session.add(MemoryKnowledgeChunk(domain="medication", title="Draft", chunk_text="Draft", source_type="guideline"))
    db_session.add(MemoryKnowledgeChunk(domain="medication", title="Approved", chunk_text="Approved", source_type="guideline", source_id="nmpa_drug_label", source_ref="NMPA-EXAMPLE-002", source_url="https://www.nmpa.gov.cn/example/label-2", review_status="approved", reviewed_by="clinical-reviewer", reviewed_at=datetime(2026, 7, 23)))
    db_session.commit()
    assert [chunk.title for chunk in list_knowledge_chunks(db_session)] == ["Approved"]
    monkeypatch.setenv("PATIENT_AGENT_ENV", "production"); assert [chunk.title for chunk in list_knowledge_chunks(db_session, approved_only=False)] == ["Approved"]
