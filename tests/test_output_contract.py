"""统一输出装配的确定性测试。"""

from app.mcp.llm_router.output_contract import assemble_output_contract


def test_emergency_safety_action_contract():
    result = assemble_output_contract(
        {"answer": "请立即拨打 120"},
        safety_action="emergency",
    )
    assert result["risk_level"] == "emergency"
    assert result["next_action"] == "emergency_care"
    assert "急救" in result["evidence_summary"]


def test_crisis_safety_action_contract():
    result = assemble_output_contract(
        {"answer": "请拨打全国心理援助热线 12356"},
        safety_action="crisis",
    )
    assert result["risk_level"] == "emergency"
    assert result["next_action"] == "emergency_care"
    assert "危机" in result["evidence_summary"]


def test_clinician_review_safety_action_contract():
    result = assemble_output_contract(
        {"answer": "请向开方医生或药师核实"},
        safety_action="clinician_review",
    )
    assert result["risk_level"] == "urgent"
    assert result["next_action"] == "contact_doctor"


def test_sufficient_evidence_contract():
    result = assemble_output_contract(
        {
            "answer": "你登记的过敏史是青霉素过敏。",
            "tool_result": {"success": True, "data": {"patient": {"allergy_history": "青霉素过敏"}}},
            "evidence_check": {"sufficient": True, "status": "sufficient"},
        }
    )
    assert result["risk_level"] == "routine"
    assert result["next_action"] == "view_records"
    assert "结构化" in result["evidence_summary"]


def test_missing_evidence_contract():
    result = assemble_output_contract(
        {
            "answer": "未检索到相关记录。",
            "evidence_check": {"sufficient": False, "status": "missing"},
        }
    )
    assert result["risk_level"] == "routine"
    assert result["next_action"] == "continue_supplement"
    assert "未检索到足够证据" in result["evidence_summary"]


def test_conflict_evidence_contract():
    result = assemble_output_contract(
        {
            "answer": "两条记录不一致。",
            "evidence_check": {"sufficient": True, "status": "conflict"},
        }
    )
    assert result["next_action"] == "contact_doctor"
    assert "不一致" in result["evidence_summary"]


def test_existing_fields_not_overwritten():
    result = assemble_output_contract(
        {
            "answer": "x",
            "risk_level": "urgent",
            "next_action": "contact_doctor",
            "evidence_summary": "custom",
        },
        safety_action="clinician_review",
    )
    assert result["risk_level"] == "urgent"
    assert result["next_action"] == "contact_doctor"
    assert result["evidence_summary"] == "custom"
