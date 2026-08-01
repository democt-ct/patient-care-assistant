"""Validation shared by clinical-knowledge import and approval workflows."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from app.config.medical_source_registry import MedicalSource, get_medical_source


class ClinicalKnowledgeValidationError(ValueError):
    """Raised when a source record cannot enter the clinical knowledge pipeline."""


def validate_source_url(source: MedicalSource, source_url: str) -> None:
    parsed = urlparse((source_url or "").strip())
    if source.allows_internal_uri and parsed.scheme == "internal":
        return
    if parsed.scheme != "https" or not parsed.hostname:
        raise ClinicalKnowledgeValidationError("source_url must be an HTTPS URL or an allowed internal URI")
    host = parsed.hostname.lower()
    if not any(host == allowed or host.endswith(f".{allowed}") for allowed in source.allowed_hosts):
        raise ClinicalKnowledgeValidationError(
            f"source_url host {host!r} is not allow-listed for source_id {source.source_id!r}"
        )


def validate_clinical_knowledge_payload(payload: dict[str, Any], *, allow_publish: bool = False) -> dict[str, Any]:
    """Validate a manifest item without silently upgrading its review status."""
    normalized = dict(payload)
    source = get_medical_source(normalized.get("source_id"))
    if source is None:
        raise ClinicalKnowledgeValidationError("source_id must exist in the medical source registry")
    if normalized.get("source_type") and normalized["source_type"] != source.source_type:
        raise ClinicalKnowledgeValidationError("source_type does not match the registered source")
    normalized["source_type"] = source.source_type
    validate_source_url(source, str(normalized.get("source_url") or ""))

    review_status = (normalized.get("review_status") or "unreviewed").strip().lower()
    if review_status not in {"unreviewed", "approved", "retired"}:
        raise ClinicalKnowledgeValidationError("review_status must be unreviewed, approved, or retired")
    if review_status == "approved":
        if not allow_publish:
            raise ClinicalKnowledgeValidationError("the importer cannot publish content without --publish")
        for field in ("source_ref", "reviewed_by", "reviewed_at"):
            if not normalized.get(field):
                raise ClinicalKnowledgeValidationError(f"approved knowledge requires {field}")
    normalized["review_status"] = review_status
    return normalized
