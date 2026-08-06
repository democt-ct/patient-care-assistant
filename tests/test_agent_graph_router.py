def test_patient_router_exposes_graph_and_blocks_before_legacy_pipeline(monkeypatch):
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./test.db")

    import app.mcp.llm_router as router

    monkeypatch.setattr(
        router,
        "_legacy_run_agent_tool_query",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("legacy pipeline should not run")),
    )

    result = router.run_agent_tool_query("我现在胸痛，还呼吸困难")

    assert result["chosen_tool"] == "medical_safety_gate"
    assert result["agent_trajectory"][0]["node"] == "safety"
    assert result["agent_trajectory"][0]["status"] == "halted"
    assert router.PATIENT_CARE_AGENT_GRAPH.describe()["entrypoint"] == "safety"
