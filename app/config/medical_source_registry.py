"""Allow-listed knowledge sources for patient-facing medical content.

The registry is intentionally small.  Adding a source is a clinical-governance
decision: record its owner, permitted hostnames, licence, and review cadence
before importing any content from it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class MedicalSource:
    source_id: str
    display_name: str
    source_type: str
    allowed_hosts: tuple[str, ...] = ()
    allows_internal_uri: bool = False
    review_interval_days: int = 365


MEDICAL_SOURCE_REGISTRY: dict[str, MedicalSource] = {
    "nmpa_drug_label": MedicalSource(
        source_id="nmpa_drug_label",
        display_name="国家药品监督管理局药品说明书/批准信息",
        source_type="drug_label",
        allowed_hosts=("nmpa.gov.cn", "www.nmpa.gov.cn"),
        review_interval_days=180,
    ),
    "nhc_guideline": MedicalSource(
        source_id="nhc_guideline",
        display_name="国家卫生健康委员会及中国政府网发布的规范文件",
        source_type="guideline",
        allowed_hosts=("nhc.gov.cn", "www.nhc.gov.cn", "gov.cn", "www.gov.cn"),
        review_interval_days=365,
    ),
    "who_guidance": MedicalSource(
        source_id="who_guidance",
        display_name="世界卫生组织公开指导材料",
        source_type="guideline",
        allowed_hosts=("who.int", "www.who.int"),
        review_interval_days=365,
    ),
    "hospital_approved_content": MedicalSource(
        source_id="hospital_approved_content",
        display_name="医院审核后的路径、宣教和服务规则",
        source_type="hospital_protocol",
        allows_internal_uri=True,
        review_interval_days=180,
    ),
}


def get_medical_source(source_id: Optional[str]) -> Optional[MedicalSource]:
    return MEDICAL_SOURCE_REGISTRY.get((source_id or "").strip())
