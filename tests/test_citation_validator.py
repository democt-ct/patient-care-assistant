"""确定性引用校验测试。"""

from app.schemas.retrieval import EvidenceItem, EvidencePack
from app.services.citation_validator import validate_answer


def _pack(*items):
    return EvidencePack(items=list(items))


def _item(field, value, source_id="record-1", record_date="2025-12-01"):
    return EvidenceItem(
        evidence_id=f"ev-{source_id}",
        source_type="visit_record",
        source_id=source_id,
        record_date=record_date,
        field=field,
        value=value,
    )


def test_supported_drug_and_date_pass():
    pack = _pack(_item("allergy_history", "青霉素过敏（皮疹）", source_id="profile-1", record_date=None))
    report = validate_answer("你登记的过敏史是：青霉素过敏（皮疹）。", pack)

    assert report.checked is True
    assert report.valid is True
    assert "青霉素" in report.supported_claims


def test_unsupported_drug_fails():
    pack = _pack(_item("diagnosis", "原发性高血压 2级"))
    report = validate_answer("建议你加用阿司匹林 100mg 每日一次。", pack)

    assert report.valid is False
    assert "阿司匹林" in report.unsupported_claims
    assert "100mg" in report.unsupported_claims


def test_unsupported_date_fails():
    pack = _pack(_item("diagnosis", "原发性高血压 2级", record_date="2025-12-01"))
    report = validate_answer("2024-06-01 体检发现血脂偏高。", pack)

    assert report.valid is False
    assert any("2024" in claim for claim in report.unsupported_claims)


def test_supported_dose_passes():
    pack = _pack(_item("medications", "缬沙坦 160mg qd；氨氯地平 5mg qd"))
    report = validate_answer("你目前使用缬沙坦 160mg 和氨氯地平 5mg。", pack)

    assert report.valid is True


def test_empty_answer_is_valid():
    assert validate_answer("", _pack()).valid is True


def test_education_task_allows_drug_outside_patient_records():
    """教育性任务允许引用证据包之外的药物通用知识，避免过度拒答。"""
    pack = _pack(_item("diagnosis", "原发性高血压 2级"))
    report = validate_answer(
        "阿莫西林是一种青霉素类抗生素，主要用于细菌感染。",
        pack,
        task="general_health_education",
    )
    assert report.checked is True
    assert report.valid is True
    assert report.unsupported_claims == []


def test_medication_task_still_flags_unsupported_drug():
    pack = _pack(_item("diagnosis", "原发性高血压 2级"))
    report = validate_answer(
        "建议你加用阿司匹林 100mg 每日一次。",
        pack,
        task="medication_allergy_check",
    )
    assert report.valid is False

# ── V2：显式 claim → evidence_id 绑定校验 ──

def test_claim_binding_with_valid_ids_passes():
    pack = _pack(_item("allergy_history", "青霉素过敏", source_id="profile-1", record_date=None))
    report = validate_answer(
        "你青霉素过敏。",
        pack,
        task="medication_allergy_check",
        claim_bindings=[
            {"claim": "青霉素过敏", "evidence_ids": ["ev-profile-1"], "verdict": "supported"},
        ],
    )
    assert report.valid is True
    assert "青霉素过敏" in report.supported_claims


def test_claim_binding_with_missing_evidence_id_fails():
    pack = _pack(_item("allergy_history", "青霉素过敏", source_id="profile-1", record_date=None))
    report = validate_answer(
        "你青霉素过敏。",
        pack,
        task="medication_allergy_check",
        claim_bindings=[
            {"claim": "青霉素过敏", "evidence_ids": ["ev-nonexistent"], "verdict": "supported"},
        ],
    )
    assert report.valid is False
    assert any("绑定证据缺失" in claim for claim in report.unsupported_claims)


def test_claim_binding_unsupported_fails():
    pack = _pack(_item("allergy_history", "青霉素过敏", source_id="profile-1", record_date=None))
    report = validate_answer(
        "建议加用阿司匹林。",
        pack,
        task="medication_allergy_check",
        claim_bindings=[
            {"claim": "加用阿司匹林", "evidence_ids": [], "verdict": "unsupported"},
        ],
    )
    assert report.valid is False
    assert "加用阿司匹林" in report.unsupported_claims
