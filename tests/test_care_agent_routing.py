from app.mcp.llm_router import _fallback_intent, _generate_answer_text
from app.mcp.server import mcp_server


def test_care_plan_question_routes_to_read_only_care_tool():
    intent = _fallback_intent("我的照护计划里还有什么待办？")

    assert intent["intent"] == "care_plan_query"
    assert "get_my_care_plans" in {tool.name for tool in mcp_server.list_tools()}


def test_profile_query_has_a_record_based_fallback_when_llm_fails():
    class FailingLLM:
        def invoke(self, _prompt):
            raise RuntimeError("provider unavailable")

    answer = _generate_answer_text(
        FailingLLM(),
        question="帮我总结一下病历和就诊情况",
        intent_state={"intent": "patient_profile_summary"},
        chosen_plan={},
        execution_trace=[],
        latest_tool_name="get_patient_profile",
        latest_tool_result={
            "data": {
                "patient": {"full_name": "测试患者", "allergy_history": "青霉素过敏"},
                "medical_records": [
                    {"record_date": "2026-08-01", "record_type": "出院记录", "diagnosis": "高血压"},
                ],
                "visit_records": [
                    {"visit_date": "2026-08-02", "department": "心内科", "follow_up_plan": "两周后复诊"},
                ],
            }
        },
        image_analysis=None,
        conversation_context=None,
    )

    assert "模型服务暂不可用" in answer
    assert "高血压" in answer
    assert "两周后复诊" in answer


def test_care_plan_tool_is_patient_bound():
    from app.mcp.llm_router import PATIENT_BOUND_TOOLS

    assert "get_my_care_plans" in PATIENT_BOUND_TOOLS
