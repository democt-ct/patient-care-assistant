import pytest
from pydantic import ValidationError

from app.schemas.memory_extraction import MemoryKnowledgeChunkCreate
from app.services.clinical_knowledge_governance import (
    ClinicalKnowledgeValidationError,
    validate_clinical_knowledge_payload,
)


def _nmpa_record(**overrides):
    record = {
        "source_id": "nmpa_drug_label",
        "source_type": "drug_label",
        "source_url": "https://www.nmpa.gov.cn/example/label",
        "source_ref": "NMPA-EXAMPLE-001",
        "domain": "medication",
        "title": "Example label excerpt",
        "chunk_text": "Example educational content",
        "review_status": "unreviewed",
    }
    record.update(overrides)
    return record


def test_allow_list_accepts_registered_official_source():
    validated = validate_clinical_knowledge_payload(_nmpa_record())

    assert validated["source_type"] == "drug_label"
    assert validated["review_status"] == "unreviewed"


def test_unknown_or_untrusted_source_is_rejected():
    with pytest.raises(ClinicalKnowledgeValidationError, match="allow-listed"):
        validate_clinical_knowledge_payload(
            _nmpa_record(source_url="https://untrusted.example/label")
        )


def test_importer_cannot_publish_without_explicit_permission_and_review_data():
    approved = _nmpa_record(
        review_status="approved",
        reviewed_by="clinical-reviewer",
        reviewed_at="2026-07-23T10:00:00",
    )
    with pytest.raises(ClinicalKnowledgeValidationError, match="--publish"):
        validate_clinical_knowledge_payload(approved)

    validated = validate_clinical_knowledge_payload(approved, allow_publish=True)
    assert validated["review_status"] == "approved"


def test_api_schema_rejects_an_untrusted_registered_source_url():
    with pytest.raises(ValidationError, match="allow-listed"):
        MemoryKnowledgeChunkCreate(
            **_nmpa_record(source_url="https://untrusted.example/label")
        )
