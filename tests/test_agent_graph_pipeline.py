def test_pipeline_records_evidence_stage_for_agent_result(monkeypatch):
    import app.mcp.llm_router.pipeline as pipeline

    namespace = {
        "run_agent_tool_query": lambda question, **kwargs: {
            "question": question,
            "answer": "record answer",
            "chosen_tool": "get_patient_profile",
            "tool_result": {"success": True, "data": {"patient": {"id": "masked"}}},
            "planning": {},
        },
        "run_agent_execution": lambda question, **kwargs: {
            "question": question,
            "answer": "record answer",
            "chosen_tool": "get_patient_profile",
            "tool_result": {"success": True, "data": {"patient": {"id": "masked"}}},
            "planning": {},
        },
        "evaluate_medical_safety": lambda question: type(
            "Decision",
            (),
            {"blocked": False, "action": type("Action", (), {"value": "allow"})()},
        )(),
        "_build_safety_gate_result": lambda question, decision: {},
        "_try_structured_fact_query": lambda **kwargs: None,
    }

    pipeline.install_graph_pipeline(namespace)
    result = namespace["run_agent_tool_query"]("总结我的情况")

    assert result["evidence_check"]["status"] == "sufficient"
    assert result["evidence_check"]["decision"] == "generate"
    assert [item["node"] for item in result["agent_trajectory"]] == [
        "safety",
        "task_route",
        "retrieval",
        "generate",
        "evidence_check",
        "citation_validate",
        "output_assemble",
    ]
    assert result["planning"]["graph"]["entrypoint"] == "safety"
    assert result["task_route"]["task"] == "general_health_education"
    assert result["risk_level"] == "routine"
    assert result["next_action"] in {"view_records", "continue_supplement"}
    assert result["evidence_summary"]


def test_pipeline_structured_fact_path_goes_through_evidence_and_assembly(monkeypatch):
    import app.mcp.llm_router.pipeline as pipeline

    judge_calls = []
    monkeypatch.setattr(
        pipeline,
        "judge_evidence",
        lambda *args, **kwargs: judge_calls.append((args, kwargs)),
    )

    namespace = {
        "run_agent_tool_query": lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("legacy pipeline should not run")
        ),
        "run_agent_execution": lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("executor should not run when a direct record answers")
        ),
        "evaluate_medical_safety": lambda question: type(
            "Decision",
            (),
            {"blocked": False, "action": type("Action", (), {"value": "allow"})()},
        )(),
        "_build_safety_gate_result": lambda question, decision: {},
        "_try_structured_fact_query": lambda **kwargs: {
            "answer": "direct record",
            "chosen_tool": "get_medical_records",
            "tool_result": {"success": True, "data": {"medical_records": [{"diagnosis": "高血压"}]}},
        },
    }

    pipeline.install_graph_pipeline(namespace)
    result = namespace["run_agent_tool_query"]("我以前吃过什么药？", patient_id="patient")

    assert result["answer"].startswith("direct record")
    assert [item["node"] for item in result["agent_trajectory"]] == [
        "safety",
        "task_route",
        "retrieval",
        "evidence_check",
        "retrieval",
        "evidence_check",
        "citation_validate",
        "output_assemble",
    ]
    assert result["evidence_check"]["status"] == "missing"
    assert result["evidence_check"]["decision"] == "clarify"
    assert result["evidence_check"]["attempt"] == 2
    assert result["task_route"]["task"] == "medication_allergy_check"
    assert result["risk_level"] == "routine"
    assert result["next_action"] == "continue_supplement"
    assert result["evidence_summary"]
    assert judge_calls == []


def test_pipeline_exposes_official_health_sources_to_clients(monkeypatch):
    import app.mcp.llm_router.pipeline as pipeline

    judge_calls = []
    monkeypatch.setattr(
        pipeline,
        "judge_evidence",
        lambda *args, **kwargs: judge_calls.append((args, kwargs)),
    )

    namespace = {
        "run_agent_tool_query": lambda question, **kwargs: {
            "question": question,
            "answer": "高血压患者应结合医生建议管理饮食与运动。",
            "chosen_tool": "direct_model_answer",
            "tool_result": {"success": True, "data": {"source": "direct_model_answer"}},
            "planning": {},
        },
        "run_agent_execution": lambda question, **kwargs: (_ for _ in ()).throw(
            RuntimeError("model unavailable")
        ),
        "evaluate_medical_safety": lambda question: type(
            "Decision",
            (),
            {"blocked": False, "action": type("Action", (), {"value": "allow"})()},
        )(),
        "_build_safety_gate_result": lambda question, decision: {},
        "_try_structured_fact_query": lambda **kwargs: None,
    }

    pipeline.install_graph_pipeline(namespace)
    result = namespace["run_agent_tool_query"]("高血压患者饮食和运动需要注意什么？")

    assert result["knowledge_sources"][0]["source_id"] == "nhc_hypertension_2024"
    assert result["knowledge_sources"][0]["source_url"].startswith("https://www.nhc.gov.cn/")
    assert "国家卫生健康委" in result["evidence_summary"]
    assert result["evidence_coverage"] == result["evidence_check"]["coverage"]
    assert result["chosen_tool"] == "official_health_knowledge_fallback"
    assert judge_calls == []


def test_pipeline_missing_structured_field_skips_llm_retries():
    import app.mcp.llm_router.pipeline as pipeline

    namespace = {
        "run_agent_tool_query": lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("legacy pipeline should not run")),
        "run_agent_execution": lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("LLM executor should not run")),
        "evaluate_medical_safety": lambda question: type("Decision", (), {"blocked": False, "action": type("Action", (), {"value": "allow"})()})(),
        "_build_safety_gate_result": lambda question, decision: {},
        "_try_structured_fact_query": lambda **kwargs: {
            "answer": "未检索到对应指标，请向医生确认。",
            "chosen_tool": "get_medical_records",
            "tool_result": {"success": True, "data": {"medical_records": []}},
            "structured_fact_missing": True,
            "next_action": "contact_doctor",
            "planning": {},
        },
    }

    pipeline.install_graph_pipeline(namespace)
    result = namespace["run_agent_tool_query"]("我的低密度脂蛋白是多少？", patient_id="patient")

    assert result["next_action"] == "contact_doctor"
    assert result["evidence_check"]["status"] == "missing"
    assert [item["node"] for item in result["agent_trajectory"]] == [
        "safety", "task_route", "retrieval", "output_assemble"
    ]


def test_pipeline_emergency_halts_at_safety_before_any_retrieval():
    import app.mcp.llm_router.pipeline as pipeline

    namespace = {
        "run_agent_tool_query": lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("legacy pipeline should not run")
        ),
        "run_agent_execution": lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("executor should not run for emergency")
        ),
        "evaluate_medical_safety": lambda question: type(
            "Decision",
            (),
            {
                "blocked": True,
                "action": type("Action", (), {"value": "emergency"})(),
                "detected_signals": ("chest_pain",),
            },
        )(),
        "_build_safety_gate_result": lambda question, decision: {
            "question": question,
            "answer": "请立即拨打 120",
            "chosen_tool": "medical_safety_gate",
            "tool_result": {"success": True, "data": {"action": "emergency"}},
        },
        "_try_structured_fact_query": lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("retrieval should not run for emergency")
        ),
    }

    pipeline.install_graph_pipeline(namespace)
    result = namespace["run_agent_tool_query"]("我现在胸痛、呼吸困难怎么办？")

    assert result["chosen_tool"] == "medical_safety_gate"
    assert [item["node"] for item in result["agent_trajectory"]] == ["safety"]
    assert result["risk_level"] == "emergency"
    assert result["next_action"] == "emergency_care"


def test_pipeline_drug_education_is_not_over_refused():
    """药物教育问题不得被引用校验误拒（回归：过度拒答修复）。"""
    import app.mcp.llm_router.pipeline as pipeline

    namespace = {
        "run_agent_tool_query": lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("legacy pipeline should not run")
        ),
        "run_agent_execution": lambda question, **kwargs: {
            "question": question,
            "answer": "阿莫西林是一种青霉素类抗生素，主要用于细菌感染。",
            "chosen_tool": "direct_model_answer",
            "tool_result": {"success": True, "data": {"source": "direct_model_answer"}},
            "planning": {},
        },
        "evaluate_medical_safety": lambda question: type(
            "Decision",
            (),
            {"blocked": False, "action": type("Action", (), {"value": "allow"})()},
        )(),
        "_build_safety_gate_result": lambda question, decision: {},
        "_try_structured_fact_query": lambda **kwargs: None,
    }

    pipeline.install_graph_pipeline(namespace)
    result = namespace["run_agent_tool_query"]("阿莫西林是治什么的？")

    assert result["task_route"]["task"] == "general_health_education"
    assert result["citation_report"]["valid"] is True
    assert "阿莫西林" in result["answer"]
    assert result["answer"] != "当前记录无法支持回答中的具体结论（存在无法核验的药物/剂量/日期表述）。"
