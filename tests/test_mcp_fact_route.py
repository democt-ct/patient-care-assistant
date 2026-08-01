from app.api.mcp_routes import _is_explicit_structured_fact_question


def test_explicit_patient_fact_questions_skip_rag_context_loading():
    assert _is_explicit_structured_fact_question("我的糖尿病诊断是什么？")
    assert _is_explicit_structured_fact_question("我可以用磺胺类抗生素吗？")
    assert _is_explicit_structured_fact_question("我下次什么时候复诊？")
    assert not _is_explicit_structured_fact_question("糖尿病患者日常饮食需要注意什么？")
