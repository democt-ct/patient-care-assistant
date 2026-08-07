"""V2 证据双轨：LLM 证据法官解析、降级与合并的测试。"""

from __future__ import annotations

import pytest

from app.mcp.llm_router.pipeline import _merge_judge_verdict
from app.schemas.retrieval import (
    EvidenceCheck,
    EvidenceDecision,
    EvidenceItem,
    EvidenceJudgeResult,
    EvidenceJudgeVerdict,
    EvidencePack,
    EvidenceStatus,
    RetrievalRoute,
    RetrievalSource,
    TaskType,
)
from app.services.evidence_judge import (
    EVIDENCE_JUDGE_ENABLED,
    judge_evidence,
)


@pytest.fixture(autouse=True)
def _enable_judge_for_tests(monkeypatch):
    """???????? LLM ?????????????????"""
    import app.services.evidence_judge as judge_module

    monkeypatch.setattr(judge_module, "EVIDENCE_JUDGE_ENABLED", True)


class _FakeLLM:
    def __init__(self, text: str = "", error: Exception | None = None):
        self._text = text
        self._error = error
        self.prompts: list[str] = []

    def invoke(self, prompt: str):
        self.prompts.append(prompt)
        if self._error is not None:
            raise self._error
        return type("R", (), {"content": self._text})()


def _pack_with(*items: EvidenceItem) -> EvidencePack:
    return EvidencePack(items=list(items))


def _item(field: str, value: str, evidence_id: str = "ev-1") -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        source_type="patient_profile",
        source_id="profile-1",
        record_date=None,
        field=field,
        value=value,
    )


def _route() -> RetrievalRoute:
    return RetrievalRoute(
        task=TaskType.MEDICATION_ALLERGY_CHECK,
        sources=[RetrievalSource.STRUCTURED_PATIENT_FACT],
        required_facts=["allergy_history"],
        forbidden_actions=["dose_change"],
        max_retrieval_rounds=1,
    )


def test_judge_parses_supported_verdict_with_claim_bindings():
    llm = _FakeLLM(
        text=(
            '{"verdict": "supported", '
            '"claim_bindings": [{"claim": "患者青霉素过敏", "evidence_ids": ["ev-1"], "verdict": "supported"}], '
            '"reason": "全部论断均有证据"}'
        )
    )
    pack = _pack_with(_item("allergy_history", "青霉素过敏", "ev-1"))
    result = judge_evidence("我对什么过敏？", "你青霉素过敏。", pack, _route(), llm=llm)

    assert result is not None
    assert result.verdict is EvidenceJudgeVerdict.SUPPORTED
    assert result.judge_source == "llm"
    assert len(result.claim_bindings) == 1
    assert result.claim_bindings[0].evidence_ids == ["ev-1"]


def test_judge_filters_evidence_ids_not_in_pack():
    llm = _FakeLLM(
        text=(
            '{"verdict": "supported", '
            '"claim_bindings": [{"claim": "c", "evidence_ids": ["ev-1", "ev-missing"]}], "reason": "r"}'
        )
    )
    pack = _pack_with(_item("allergy_history", "青霉素过敏", "ev-1"))
    result = judge_evidence("q", "a", pack, _route(), llm=llm)

    assert result is not None
    assert result.claim_bindings[0].evidence_ids == ["ev-1"]


def test_judge_returns_none_on_malformed_json():
    llm = _FakeLLM(text="抱歉，我无法回答。")
    pack = _pack_with(_item("allergy_history", "青霉素过敏"))
    assert judge_evidence("q", "a", pack, _route(), llm=llm) is None


def test_judge_returns_none_on_llm_error():
    llm = _FakeLLM(error=RuntimeError("timeout"))
    pack = _pack_with(_item("allergy_history", "青霉素过敏"))
    assert judge_evidence("q", "a", pack, _route(), llm=llm) is None


def test_judge_returns_none_when_disabled(monkeypatch):
    if not EVIDENCE_JUDGE_ENABLED:
        # 测试环境默认关闭；直接验证关闭时返回 None
        import app.services.evidence_judge as module

        monkeypatch.setattr(module, "EVIDENCE_JUDGE_ENABLED", False)
    else:
        import app.services.evidence_judge as module

        monkeypatch.setattr(module, "EVIDENCE_JUDGE_ENABLED", False)
    assert judge_evidence("q", "a", _pack_with(_item("allergy_history", "x")), _route(), llm=_FakeLLM()) is None


def _check(status: EvidenceStatus, decision: EvidenceDecision) -> EvidenceCheck:
    return EvidenceCheck(
        status=status,
        coverage=1.0,
        decision=decision,
        attempt=1,
        max_attempts=1,
    )


def test_merge_judge_conflict_upgrades_deterministic_result():
    check = _merge_judge_verdict(
        _check(EvidenceStatus.SUFFICIENT, EvidenceDecision.GENERATE),
        EvidenceJudgeResult(
            verdict=EvidenceJudgeVerdict.CONFLICT,
            claim_bindings=[],
            reason="语义冲突",
        ),
        _route(),
    )
    assert check.status is EvidenceStatus.CONFLICT
    assert check.decision is EvidenceDecision.CLARIFY
    assert check.verdict_source == "llm"
    assert check.judge is not None
    assert any(conflict.field == "llm_judge" for conflict in check.conflicts)


def test_merge_judge_unsupported_refuses_on_forbidden_route():
    check = _merge_judge_verdict(
        _check(EvidenceStatus.SUFFICIENT, EvidenceDecision.GENERATE),
        EvidenceJudgeResult(
            verdict=EvidenceJudgeVerdict.UNSUPPORTED,
            claim_bindings=[],
            reason="回答含无依据药物建议",
        ),
        _route(),
    )
    assert check.status is EvidenceStatus.HIGH_RISK
    assert check.decision is EvidenceDecision.REFUSE


def test_merge_judge_none_keeps_deterministic_baseline():
    check = _merge_judge_verdict(
        _check(EvidenceStatus.SUFFICIENT, EvidenceDecision.GENERATE),
        None,
        _route(),
    )
    assert check.status is EvidenceStatus.SUFFICIENT
    assert check.decision is EvidenceDecision.GENERATE
    assert check.verdict_source == "deterministic"


def test_merge_judge_supported_does_not_downgrade_deterministic_risk():
    check = _merge_judge_verdict(
        _check(EvidenceStatus.HIGH_RISK, EvidenceDecision.REFUSE),
        EvidenceJudgeResult(
            verdict=EvidenceJudgeVerdict.SUPPORTED,
            claim_bindings=[],
            reason="ok",
        ),
        _route(),
    )
    assert check.status is EvidenceStatus.HIGH_RISK
    assert check.decision is EvidenceDecision.REFUSE
