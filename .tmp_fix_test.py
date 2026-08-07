"""Fix corrupted Chinese in appended personalization tests."""
from __future__ import annotations
from pathlib import Path

p = Path(r"D:\zhuomian\agent\patient-care-assistant\tests\test_response_guidance.py")
content = p.read_text(encoding="utf-8")
marker = "# ── V2 阶段 6：记忆个性化 ──"
idx = content.find(marker)
if idx == -1:
    raise SystemExit("marker not found")
content = content[:idx]

addition = '''# ── V2 阶段 6：记忆个性化 ──

def test_personalize_high_risk_alert_strengthens_reminder():
    from app.services.response_guidance import personalize_response

    answer, applied = personalize_response(
        "注意休息。",
        risk_level="urgent",
        preferences={"risk_alert_level": "high"},
    )
    assert applied["personalized"] is True
    assert applied["risk_reminder_strengthened"] is True
    assert "请务必重视" in answer


def test_personalize_plain_language_note_appended():
    from app.services.response_guidance import personalize_response

    answer, applied = personalize_response(
        "注意休息。",
        risk_level="routine",
        preferences={"medical_term_level": "plain"},
    )
    assert applied["plain_language_note"] is True
    assert "通俗语言" in answer


def test_personalize_no_preferences_is_noop():
    from app.services.response_guidance import personalize_response

    answer, applied = personalize_response("注意休息。", risk_level="routine", preferences={})
    assert applied["personalized"] is False
    assert answer == "注意休息。"


def test_pipeline_applies_personalization_and_escalation():
    import app.mcp.llm_router.pipeline as pipeline

    namespace = _namespace()
    pipeline.install_graph_pipeline(namespace)
    result = namespace["run_agent_tool_query"](
        "疼痛一般如何缓解？",
        personalization={"risk_alert_level": "high", "medical_term_level": "plain"},
    )
    assert result["risk_level"] == "urgent"
    assert "120" in result["answer"]
    assert "请务必重视" in result["answer"]
    assert result["personalization_applied"]["risk_reminder_strengthened"] is True
'''
p.write_text(content + addition, encoding="utf-8")
print("fixed")
