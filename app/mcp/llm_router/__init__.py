"""Explicit graph wrapper around the current Agent implementation."""

from __future__ import annotations

from pathlib import Path

from app.agent.graph import AgentGraph, AgentGraphState, AgentNode

_legacy_path = Path(__file__).resolve().parent.parent / "llm_router.py"
exec(compile(_legacy_path.read_bytes(), str(_legacy_path), "exec"), globals(), globals())

from app.mcp.llm_router.pipeline import install_graph_pipeline

install_graph_pipeline(globals())

