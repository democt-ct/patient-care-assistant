"""V2 阶段 3：规则手册知识化（治理准入 + 提示词注入）与 LLM 分类器兜底测试。"""

from __future__ import annotations

from app.config.rulebook_knowledge import RULEBOOK_ENTRIES, rulebook_context_for
from app.schemas.retrieval import RetrievalRoute, RetrievalSource, TaskType
from app.services.clinical_knowledge_governance import validate_clinical_knowledge_payload
from app.services.retrieval_router import LLM_CLASSIFIER_ENABLED, route_for_task, route_question


class _FakeLLM:
    def __init__(self, text: str = "", error: Exception | None = None):
        self._text = text
        self._error = error

    def invoke(self, prompt: str):
        if self._error is not None:
            raise self._error
        return type("R", (), {"content": self._text})()


def test_rulebook_entries_pass_governance_approval():
    assert len(RULEBOOK_ENTRIES) >= 7
    for entry in RULEBOOK_ENTRIES:
        normalized = validate_clinical_knowledge_payload(entry, allow_publish=True)
        assert normalized["review_status"] == "approved"
        assert normalized["source_id"] == "hospital_approved_content"
        assert normalized["reviewed_by"]
        assert normalized["reviewed_at"]


def test_rulebook_context_for_route_injects_handling_and_forbidden_actions():
    route = RetrievalRoute(
        task=TaskType.MEDICATION_ALLERGY_CHECK,
        sources=[RetrievalSource.STRUCTURED_PATIENT_FACT],
        required_facts=["allergy_history"],
        forbidden_actions=["dose_change", "stop_medication"],
        max_retrieval_rounds=1,
    )
    block = rulebook_context_for(route)
    assert "规则手册" in block
    assert "用药与过敏核对" in block
    assert "禁止动作" in block
    assert "dose_change" in block


def test_rulebook_context_for_none_route_is_empty():
    assert rulebook_context_for(None) == ""


def test_rulebook_context_covered_for_all_task_types():
    for task in TaskType:
        route = route_for_task(task)
        block = rulebook_context_for(route)
        assert block, f"task {task.value} 缺少规则手册知识块"


def test_llm_classifier_fallback_when_rules_miss(monkeypatch):
    import app.services.retrieval_router as router

    monkeypatch.setattr(router, "LLM_CLASSIFIER_ENABLED", True)
    llm = _FakeLLM(text='{"task": "visit_preparation"}')
    route = route_question("帮我整理一下复诊要问医生的问题", llm=llm)
    assert route.task is TaskType.VISIT_PREPARATION


def test_llm_classifier_error_falls_back_to_default_route(monkeypatch):
    import app.services.retrieval_router as router

    monkeypatch.setattr(router, "LLM_CLASSIFIER_ENABLED", True)
    llm = _FakeLLM(error=RuntimeError("unavailable"))
    route = route_question("随便聊聊今天天气", llm=llm)
    assert route.task is TaskType.GENERAL_HEALTH_EDUCATION
    assert route.route_reason == "fallback_non_individualized"


def test_llm_classifier_disabled_keeps_deterministic_rules(monkeypatch):
    import app.services.retrieval_router as router

    monkeypatch.setattr(router, "LLM_CLASSIFIER_ENABLED", False)
    route = route_question("我青霉素过敏，能用头孢吗？", llm=_FakeLLM(text='{"task": "visit_preparation"}'))
    assert route.task is TaskType.MEDICATION_ALLERGY_CHECK


def test_deterministic_rules_still_win_before_llm_classifier(monkeypatch):
    import app.services.retrieval_router as router

    monkeypatch.setattr(router, "LLM_CLASSIFIER_ENABLED", True)
    llm = _FakeLLM(text='{"task": "general_health_education"}')
    route = route_question("我青霉素过敏，能用头孢吗？", llm=llm)
    assert route.task is TaskType.MEDICATION_ALLERGY_CHECK
