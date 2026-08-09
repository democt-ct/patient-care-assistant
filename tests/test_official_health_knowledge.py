from app.config.official_health_knowledge import official_health_context_for
from app.services.retrieval_router import route_question


def test_hypertension_education_uses_nhc_source_with_provenance():
    hits = official_health_context_for("高血压患者饮食和运动要注意什么？", route_question("高血压患者饮食和运动要注意什么？"))
    assert hits and hits[0]["source_id"] == "nhc_hypertension_2024"
    assert hits[0]["source_url"].startswith("https://www.nhc.gov.cn/")


def test_official_health_pack_does_not_apply_to_patient_record_queries():
    assert official_health_context_for("我的低密度脂蛋白是多少？", route_question("我的低密度脂蛋白是多少？")) == []
