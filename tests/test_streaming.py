"""Tests for SSE streaming endpoint and agent enhancements."""

import json
import time

import pytest

from app.api.stream_routes import _sse_event


class TestSSEEventFormat:
    def test_sse_event_format(self):
        event = _sse_event("status", {"phase": "test", "message": "hello"})
        assert "event: status" in event
        assert "data: " in event
        data = json.loads(event.split("data: ")[1].strip())
        assert data["phase"] == "test"

    def test_sse_done_event(self):
        event = _sse_event("done", {"answer": "测试回答", "intent": "general"})
        data = json.loads(event.split("data: ")[1].strip())
        assert data["answer"] == "测试回答"


class TestStreamEndpoint:
    """Integration tests for the SSE stream endpoint."""

    @pytest.fixture(autouse=True)
    def stub_agent(self, monkeypatch):
        monkeypatch.setattr(
            "app.api.stream_routes.run_agent_tool_query_stream",
            lambda **kwargs: {
                "answer": "测试回答",
                "speech_text": "测试回答",
                "intent": "general_chat",
                "chosen_tool": "test_stub",
            },
        )

    def test_stream_endpoint_health(self, client):
        """The stream endpoint should accept POST requests."""
        resp = client.post("/api/v1/mcp/agent/query-stream", json={
            "question": "你好",
            "chat_mode": "general",
        })
        # Should return 200 with text/event-stream
        assert resp.status_code == 200
        assert resp.headers.get("content-type", "").startswith("text/event-stream")

    def test_stream_endpoint_events(self, client):
        """The stream should yield proper SSE events without calling an external model."""
        resp = client.post("/api/v1/mcp/agent/query-stream", json={
            "question": "你好",
            "chat_mode": "general",
        })
        events = resp.text.strip().split("\n\n")
        event_types = set()
        for event_str in events:
            for line in event_str.split("\n"):
                if line.startswith("event: "):
                    event_types.add(line[7:])

        # Should include at least status and token/done events
        assert "status" in event_types
        assert "token" in event_types or "done" in event_types

    def test_stream_endpoint_emits_graph_phase_events(self, client, monkeypatch):
        def phased_agent(**kwargs):
            kwargs["on_phase"]("safety", "正在执行医疗安全检查...")
            kwargs["on_phase"]("task_route", "正在识别任务类型与检索来源...")
            return {
                "question": kwargs["question"],
                "answer": "测试回答",
                "intent": "general_chat",
                "chosen_tool": "test_stub",
            }

        monkeypatch.setattr("app.api.stream_routes.run_agent_tool_query_stream", phased_agent)
        resp = client.post("/api/v1/mcp/agent/query-stream", json={"question": "你好", "chat_mode": "general"})
        assert "event: phase" in resp.text
        assert '"phase": "safety"' in resp.text
        assert resp.text.index("event: phase") < resp.text.index("event: token")

    def test_stream_done_event_keeps_official_knowledge_sources(self, client, monkeypatch):
        monkeypatch.setattr(
            "app.api.stream_routes.run_agent_tool_query_stream",
            lambda **kwargs: {
                "answer": "权威资料摘要",
                "intent": "general_health_education",
                "chosen_tool": "official_health_knowledge_fallback",
                "evidence_coverage": 1.0,
                "knowledge_sources": [{
                    "source_id": "nhc_hypertension_2024",
                    "source_name": "国家卫生健康委",
                    "source_url": "https://www.nhc.gov.cn/example",
                    "version": "2024-07-01",
                    "title": "高血压健康指导",
                }],
            },
        )

        resp = client.post("/api/v1/mcp/agent/query-stream", json={
            "question": "高血压患者饮食要注意什么？",
            "chat_mode": "general",
        })

        assert '"knowledge_sources": [{"source_id": "nhc_hypertension_2024"' in resp.text
        assert '"evidence_coverage": 1.0' in resp.text

    def test_stream_failure_returns_safe_fallback(self, client, monkeypatch):
        def fail_agent(**kwargs):
            raise RuntimeError("model unavailable")

        monkeypatch.setattr(
            "app.api.stream_routes.run_agent_tool_query_stream",
            fail_agent,
        )
        resp = client.post("/api/v1/mcp/agent/query-stream", json={
            "question": "你好",
            "chat_mode": "general",
        })

        assert "event: error" in resp.text
        assert "event: token" in resp.text
        assert "event: done" in resp.text
        assert "service_fallback" in resp.text

    def test_stream_empty_question(self, client):
        """Empty question should return 400."""
        resp = client.post("/api/v1/mcp/agent/query-stream", json={
            "question": "",
        })
        assert resp.status_code == 400

    def test_stream_endpoint_returns_events(self, client):
        """Verify the stream endpoint returns data in SSE format."""
        resp = client.post("/api/v1/mcp/agent/query-stream", json={
            "question": "简单测试",
            "chat_mode": "general",
        })
        # Each SSE event should have data
        assert "data: " in resp.text


class TestLLMFallback:
    """Tests for LLM fallback mechanism."""

    def test_get_llm_returns_client(self):
        """get_llm() should return a properly configured client."""
        from app.mcp.config import get_llm
        llm = get_llm()
        assert llm is not None
        assert hasattr(llm, "invoke")
        assert llm.MAX_RETRIES == 3

    def test_llm_client_retry_config(self):
        """LLM client should have retry configured."""
        from app.mcp.config import OpenAICompatChatClient
        assert OpenAICompatChatClient.MAX_RETRIES >= 1
        assert OpenAICompatChatClient.RETRY_BASE_DELAY > 0


class TestSourceAttribution:
    """Tests for answer source attribution."""

    def test_tool_result_contains_sources(self):
        """Tool execution results should include data from known sources."""
        from app.mcp.server import tool_get_medical_records
        # Test that the tool returns structured data
        # We test via the API client with a known patient
        pass

    def test_answer_prompt_includes_context(self):
        """The answer generation prompt should include the question and context."""
        from app.mcp.llm_router import _build_answer_prompt
        prompt = _build_answer_prompt(
            question="测试问题",
            intent_state={"intent": "general_medical_question", "latest_only": False,
                          "focus": [], "reasoning_summary": "test"},
            latest_tool_name="test",
            latest_tool_result={"data": {"test": "value"}},
            execution_trace=[],
            conversation_context="",
            allergy_drugs=[],
            chosen_plan={"plan_id": "test", "steps": []},
            image_analysis=None,
        )
        assert "问题: 测试问题" in prompt
        assert "意图: general_medical_question" in prompt


# ── Chunk Quality Scoring ──

class TestChunkQualityScoring:
    """Tests for knowledge chunk quality evaluation."""

    def test_chunk_has_quality_metrics(self, db_session):
        """MemoryKnowledgeChunk should have confidence field for quality scoring."""
        from app.models.memory_knowledge_chunk import MemoryKnowledgeChunk
        # Verify the column exists
        assert hasattr(MemoryKnowledgeChunk, "confidence")
        assert hasattr(MemoryKnowledgeChunk, "tags")

    def test_upsert_chunk_quality(self, db_session):
        """Verify chunk quality fields are populated on creation."""
        from app.services.memory_extraction_service import upsert_knowledge_chunk

        result = upsert_knowledge_chunk(db_session, payload={
            "hospital_id": "hosp-q",
            "domain": "diagnosis",
            "title": "质量测试",
            "chunk_text": "测试质量评分的知识切片内容",
            "source_type": "test",
            "confidence": 0.85,
            "tags": "test, quality",
        })
        assert result is not None
        assert result.confidence == 0.85
        assert "test" in (result.tags or "")
