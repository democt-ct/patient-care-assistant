"""Claim 提取测试（Bounded Safety M2）：LLM 结构化提取 + 确定性兜底。"""

from __future__ import annotations

from app.schemas.retrieval import ClaimType, TaskContract
from app.services.claim_extraction import (
    _classify_deterministic,
    _extract_deterministic,
    extract_claims,
)


class _FakeLLM:
    def __init__(self, text: str = "", error: Exception | None = None):
        self._text = text
        self._error = error

    def invoke(self, prompt: str):
        if self._error is not None:
            raise self._error
        return type("R", (), {"content": self._text})()


def test_deterministic_extraction_splits_sentences_and_classifies():
    claims = _extract_deterministic(
        "阿司匹林属于抗血小板药物。你目前正在服用阿司匹林。你应该把剂量减少一半。"
    )
    assert len(claims) == 3
    assert claims[0].claim_type is ClaimType.GENERAL_KNOWLEDGE
    assert claims[1].claim_type is ClaimType.PATIENT_FACT
    assert claims[2].claim_type in (ClaimType.RECOMMENDATION, ClaimType.ACTION)


def test_classify_deterministic_core_cases():
    assert _classify_deterministic("高血压患者通常需要注意低盐饮食。") in (
        ClaimType.GENERAL_KNOWLEDGE,
        ClaimType.RECOMMENDATION,
    )
    assert _classify_deterministic("你的血压最近控制良好。") is ClaimType.CLINICAL_INTERPRETATION
    assert _classify_deterministic("你的紧急联系人是张芳。") is ClaimType.PATIENT_FACT
    assert _classify_deterministic("建议停药观察。") in (ClaimType.RECOMMENDATION, ClaimType.ACTION)


def test_llm_extraction_parses_structured_json(monkeypatch):
    monkeypatch.setenv("CLAIM_EXTRACTION_ENABLED", "true")
    llm = _FakeLLM(
        '{"claims": [{"text": "阿司匹林属于抗血小板药物", "claim_type": "general_knowledge", '
        '"required_evidence_types": ["reviewed_knowledge"]}]}'
    )
    claims = extract_claims("阿司匹林是什么药？", "阿司匹林属于抗血小板药物。", llm=llm)
    assert len(claims) == 1
    assert claims[0].claim_type is ClaimType.GENERAL_KNOWLEDGE
    assert claims[0].required_evidence_types[0].value == "reviewed_knowledge"


def test_llm_failure_falls_back_to_deterministic(monkeypatch):
    monkeypatch.setenv("CLAIM_EXTRACTION_ENABLED", "true")
    llm = _FakeLLM(error=RuntimeError("llm unavailable"))
    claims = extract_claims("高血压注意什么？", "高血压患者应注意低盐饮食。", llm=llm)
    assert len(claims) >= 1
    assert claims[0].claim_id.startswith("claim-")


def test_llm_garbage_falls_back_to_deterministic(monkeypatch):
    monkeypatch.setenv("CLAIM_EXTRACTION_ENABLED", "true")
    llm = _FakeLLM(text="not json at all")
    claims = extract_claims("高血压注意什么？", "高血压患者应注意低盐饮食。", llm=llm)
    assert len(claims) >= 1


def test_disabled_extraction_uses_deterministic(monkeypatch):
    monkeypatch.setenv("CLAIM_EXTRACTION_ENABLED", "false")
    claims = extract_claims("高血压注意什么？", "高血压患者应注意低盐饮食。")
    assert claims[0].claim_id.startswith("claim-")


def test_empty_answer_returns_no_claims():
    assert extract_claims("问题", "") == []


def test_contract_injected_into_prompt(monkeypatch):
    monkeypatch.setenv("CLAIM_EXTRACTION_ENABLED", "true")
    seen = {}

    class _CapturingLLM:
        def invoke(self, prompt: str):
            seen["prompt"] = prompt
            return type("R", (), {"content": '{"claims": []}'})()

    contract = TaskContract(task_type=__import__("app.schemas.retrieval", fromlist=["TaskType"]).TaskType.MEDICATION_EDUCATION)
    extract_claims("阿司匹林是什么药？", "阿司匹林是抗血小板药物。", contract, llm=_CapturingLLM())
    assert "允许的论断类型" in seen["prompt"]
