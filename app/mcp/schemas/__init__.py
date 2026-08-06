"""Schema compatibility package with Agentic RAG response fields."""

from __future__ import annotations

from pathlib import Path

_legacy_path = Path(__file__).resolve().parent.parent / "schemas.py"
exec(compile(_legacy_path.read_bytes(), str(_legacy_path), "exec"), globals(), globals())

_LegacyMCPAgentQueryResponse = MCPAgentQueryResponse


class MCPAgentQueryResponse(_LegacyMCPAgentQueryResponse):  # type: ignore[misc,valid-type]
    agent_trajectory: list[dict[str, object]] | None = Field(
        default=None,
        description="Observable graph nodes without raw records or private reasoning",
    )
    evidence_check: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Evidence sufficiency, missing facts, conflicts and next decision",
    )
    evidence_coverage: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    retrieval_rounds: Optional[int] = Field(default=None, ge=0, le=2)
