import pytest

from app.agent.graph import AgentGraph, AgentGraphState, AgentNode


def test_agent_graph_routes_and_records_user_safe_trajectory():
    graph = AgentGraph(entrypoint="start")
    graph.add_node(
        AgentNode(
            name="start",
            phase="classify",
            message="classifying",
            handler=lambda state: (state.note("classified"), "finish")[1],
        )
    )
    graph.add_node(
        AgentNode(
            name="finish",
            phase="answer",
            message="answering",
            handler=lambda state: (setattr(state, "result", {"answer": "ok"}), None)[1],
        )
    )

    phases = []
    result = graph.run(AgentGraphState(context={}, on_phase=lambda phase, _: phases.append(phase)))

    assert result["answer"] == "ok"
    assert phases == ["classify", "answer"]
    assert [item["node"] for item in result["agent_trajectory"]] == ["start", "finish"]
    assert result["agent_trajectory"][0]["summary"] == "classified"
    assert all("raw" not in item for item in result["agent_trajectory"])


def test_agent_graph_has_a_bounded_step_count():
    graph = AgentGraph(entrypoint="loop", max_steps=2)
    graph.add_node(
        AgentNode(
            name="loop",
            phase="planning",
            message="planning",
            handler=lambda _: "loop",
        )
    )

    with pytest.raises(RuntimeError, match="maximum step count"):
        graph.run(AgentGraphState(context={}))


def test_agent_graph_rejects_unknown_nodes():
    graph = AgentGraph(entrypoint="missing")

    with pytest.raises(RuntimeError, match="Unknown agent graph node"):
        graph.run(AgentGraphState(context={}))
