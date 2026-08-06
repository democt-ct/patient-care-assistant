from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any, Callable, Optional


PhaseCallback = Callable[[str, str], None]
NodeHandler = Callable[["AgentGraphState"], Optional[str]]


@dataclass
class AgentGraphState:
    """Mutable state shared by graph nodes during one agent turn."""

    context: dict[str, Any]
    result: Optional[dict[str, Any]] = None
    trajectory: list[dict[str, Any]] = field(default_factory=list)
    current_summary: str = ""
    on_phase: Optional[PhaseCallback] = None

    def note(self, summary: str) -> None:
        self.current_summary = summary

    def emit(self, phase: str, message: str) -> None:
        if not self.on_phase:
            return
        try:
            self.on_phase(phase, message)
        except Exception:
            pass


@dataclass(frozen=True)
class AgentNode:
    name: str
    phase: str
    message: str
    handler: NodeHandler


class AgentGraph:
    """Deterministic graph runner with bounded execution and trajectory capture."""

    def __init__(self, *, entrypoint: str, max_steps: int = 20) -> None:
        self.entrypoint = entrypoint
        self.max_steps = max_steps
        self._nodes: dict[str, AgentNode] = {}

    def add_node(self, node: AgentNode) -> None:
        if node.name in self._nodes:
            raise ValueError(f"Duplicate agent graph node: {node.name}")
        self._nodes[node.name] = node

    def describe(self) -> dict[str, Any]:
        return {
            "entrypoint": self.entrypoint,
            "max_steps": self.max_steps,
            "nodes": [
                {"name": node.name, "phase": node.phase}
                for node in self._nodes.values()
            ],
        }

    def run(self, state: AgentGraphState) -> dict[str, Any]:
        current = self.entrypoint
        steps = 0

        while current:
            steps += 1
            if steps > self.max_steps:
                raise RuntimeError("Agent graph exceeded its maximum step count")

            node = self._nodes.get(current)
            if node is None:
                raise RuntimeError(f"Unknown agent graph node: {current}")

            state.current_summary = ""
            state.emit(node.phase, node.message)
            started = time.perf_counter()
            try:
                next_node = node.handler(state)
            except Exception as exc:
                state.trajectory.append(
                    {
                        "node": node.name,
                        "phase": node.phase,
                        "status": "error",
                        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                        "summary": state.current_summary or type(exc).__name__,
                    }
                )
                raise

            halted = state.result is not None
            state.trajectory.append(
                {
                    "node": node.name,
                    "phase": node.phase,
                    "status": "halted" if halted else "completed",
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    "summary": state.current_summary,
                    "next_node": None if halted else next_node,
                }
            )
            if halted:
                break
            current = next_node

        if state.result is None:
            raise RuntimeError("Agent graph completed without producing a result")

        state.result["agent_trajectory"] = list(state.trajectory)
        return state.result
