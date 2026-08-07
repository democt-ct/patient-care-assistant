"""
SSE 流式响应端点 —— 为 Agent 问答提供打字机效果。

与 POST /api/v1/mcp/agent/query 使用相同的处理流程，但响应
通过 Server-Sent Events 流式返回，包含阶段状态和文本逐块输出。
"""

import asyncio
import json
import os
import time
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from starlette.responses import StreamingResponse

from app.api.mcp_routes import (
    SHORT_TERM_ROUND_LIMIT,
    _build_knowledge_context_block,
    _build_long_term_memory_context,
    _build_memory_debug_payload,
    _merge_conversation_contexts,
    _render_short_term_memory_context,
    _resolve_bound_identity,
)
from app.core.database import get_db
from app.core.redis_client import (
    get_short_term_memory,
    set_short_term_memory,
)
from app.mcp.llm_router import run_agent_tool_query_stream
from app.mcp.schemas import (
    MCPAgentQueryRequest,
    MCPRiskSignals,
    MCPShortTermMemory,
)
from app.services.memory_extraction_service import (
    create_conversation_message,
)

router = APIRouter(prefix="/api/v1/mcp/agent", tags=["智能问答与工具（mcp-server）"])

STREAM_AGENT_TIMEOUT_SECONDS = float(os.getenv("STREAM_AGENT_TIMEOUT_SECONDS", "20"))


def _fallback_stream_result(question: str) -> dict:
    answer = "当前智能问答服务暂时不可用，请稍后重试。若涉及胸痛、呼吸困难等紧急症状，请立即联系急救服务。"
    return {
        "question": question,
        "answer": answer,
        "speech_text": answer,
        "intent": "service_unavailable",
        "chosen_tool": "service_fallback",
    }


def _sse_event(event_type: str, data: dict) -> str:
    """Format an SSE event."""
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _async_sleep(seconds: float):
    import asyncio
    await asyncio.sleep(seconds)


async def _agent_stream_generator(
    question: str,
    patient_id: str = None,
    hospital_id: str = None,
    auth_token: str = None,
    session_id: str = None,
    chat_mode: str = "memory",
    db: Session = None,
) -> AsyncGenerator[str, None]:
    """Async generator that performs agent query and streams SSE events."""

    # ── Phase 1: Identity ──
    yield _sse_event("status", {"phase": "identity", "message": "正在验证身份..."})
    try:
        resolved_pid, resolved_hid = _resolve_bound_identity(
            db, patient_id=patient_id, hospital_id=hospital_id, auth_token=auth_token,
        )
        if resolved_pid:
            patient_id, hospital_id = resolved_pid, resolved_hid
    except Exception:
        yield _sse_event("error", {"detail": "身份验证失败"})
        return

    # ── Phase 2: Load context ──
    yield _sse_event("status", {"phase": "context", "message": "正在加载记忆和知识..."})

    short_term_memory = get_short_term_memory(session_id) or {}
    recent_messages = (short_term_memory or {}).get("recent_messages", [])[-SHORT_TERM_ROUND_LIMIT:]

    conversation_context = ""
    long_term_memory_context = None
    knowledge_context = None
    rendered_memory_context = None
    if patient_id and chat_mode != "general":
        try:
            long_term_memory_context = _build_long_term_memory_context(db, patient_id, question)
            knowledge_context = _build_knowledge_context_block(question, hospital_id) or ""
            conversation_context = _merge_conversation_contexts([long_term_memory_context, knowledge_context]) or ""
        except Exception:
            pass

    risk_signals = MCPRiskSignals()

    # ── Phase 3: Run agent (streaming) ──
    yield _sse_event("status", {"phase": "agent", "message": "正在分析问题..."})

    # Phase callback: push real-time SSE events as the agent pipeline progresses
    def _on_phase(phase: str, message: str):
        # This will be called synchronously from within run_agent_tool_query_stream.
        # We store events and yield them after the call returns, since we can't
        # yield from inside a sync callback in an async generator.
        pass

    _pending_events: list = []

    def _phase_callback(phase: str, message: str):
        _pending_events.append(("phase", {"phase": phase, "message": message}))

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                run_agent_tool_query_stream,
                question=question,
                on_phase=_phase_callback,
                auth_token=auth_token,
                patient_id=patient_id,
                hospital_id=hospital_id,
                chat_mode=chat_mode,
                session_id=session_id,
                conversation_context=conversation_context,
                risk_signals=risk_signals,
            ),
            timeout=STREAM_AGENT_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        yield _sse_event("error", {"detail": "智能问答服务响应超时，已返回安全降级提示"})
        result = _fallback_stream_result(question)
    except Exception:
        yield _sse_event("error", {"detail": "智能问答服务暂时不可用，已返回安全降级提示"})
        result = _fallback_stream_result(question)

    # Yield buffered phase events
    for event_type, data in _pending_events:
        yield _sse_event(event_type, data)

    # ── Phase 4: Stream answer ──
    answer = result.get("answer", "") or ""
    if answer:
        chunk_size = 5
        for i in range(0, len(answer), chunk_size):
            yield _sse_event("token", {"content": answer[i:i + chunk_size]})
            await _async_sleep(0.015)
    else:
        yield _sse_event("token", {"content": ""})
        await _async_sleep(0.01)

    # ── Phase 5: Build memory debug and finalize ──
    memory_debug = None
    if chat_mode != "general" and patient_id:
        try:
            parsed_stm = MCPShortTermMemory.model_validate(short_term_memory) if short_term_memory else None
            if parsed_stm:
                rendered_memory_context = _render_short_term_memory_context(parsed_stm)
                memory_debug = _build_memory_debug_payload(
                    chat_mode=chat_mode,
                    question=question,
                    conversation_context=conversation_context or None,
                    rendered_short_term_memory=rendered_memory_context,
                    long_term_memory_context=long_term_memory_context,
                    knowledge_context=knowledge_context,
                    updated_short_term_memory=parsed_stm,
                )
        except Exception:
            pass

    if session_id:
        try:
            updated_messages = list(recent_messages)
            updated_messages.append({"role": "user", "content": question, "created_at": time.time()})
            updated_messages.append({"role": "assistant", "content": answer, "created_at": time.time()})
            set_short_term_memory(session_id, {
                "recent_messages": updated_messages[-SHORT_TERM_ROUND_LIMIT * 2:],
            })
            if patient_id:
                create_conversation_message(
                    db, session_id=session_id, patient_id=patient_id,
                    hospital_id=hospital_id, role="user", content=question,
                )
                create_conversation_message(
                    db, session_id=session_id, patient_id=patient_id,
                    hospital_id=hospital_id, role="assistant", content=answer,
                )
        except Exception:
            pass

    done_data = {
        "answer": answer,
        "speech_text": result.get("speech_text", ""),
        "intent": result.get("intent", ""),
        "intent_confidence": result.get("intent_confidence"),
        "chosen_tool": result.get("chosen_tool", ""),
        "session_id": session_id,
        "patient_id": patient_id,
        "risk_level": result.get("risk_level", "routine"),
        "next_action": result.get("next_action", "view_records"),
        "evidence_summary": result.get("evidence_summary", ""),
        "task_route": result.get("task_route"),
        "citation_report": result.get("citation_report"),
    }
    if memory_debug:
        done_data["memory_debug"] = memory_debug
    yield _sse_event("done", done_data)


@router.post("/query-stream")
async def agent_query_stream(
    payload: MCPAgentQueryRequest,
    db: Session = Depends(get_db),
):
    """SSE streaming endpoint for agent queries.

    Returns Server-Sent Events with event types:
      status → intent → planning → tool_execution → token* → done | error
    """
    question = (payload.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="问题不能为空")

    return StreamingResponse(
        _agent_stream_generator(
            question=question,
            patient_id=payload.patient_id,
            hospital_id=payload.hospital_id,
            auth_token=payload.auth_token,
            session_id=payload.session_id,
            chat_mode=(payload.chat_mode or "memory").strip().lower(),
            db=db,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
