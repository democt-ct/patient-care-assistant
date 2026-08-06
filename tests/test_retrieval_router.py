"""确定性任务路由的回归测试（四个黄金场景）。"""

import pytest

from app.schemas.retrieval import RetrievalSource, TaskType
from app.services.retrieval_router import route_for_task, route_question


@pytest.mark.parametrize(
    ("question", "expected_task"),
    [
        # 场景 3：高风险分流
        ("我现在胸痛、呼吸困难怎么办？", TaskType.RISK_TRIAGE),
        ("孩子高热抽搐了怎么办？", TaskType.RISK_TRIAGE),
        ("我突然晕倒了怎么办？", TaskType.RISK_TRIAGE),
        ("我术后伤口突然大量出血怎么办？", TaskType.RISK_TRIAGE),
        ("我胸痛，能吃硝酸甘油吗？", TaskType.RISK_TRIAGE),
        # 场景 2：用药与过敏核对
        ("我青霉素过敏，阿莫西林能不能吃？", TaskType.MEDICATION_ALLERGY_CHECK),
        ("缬沙坦我应该吃几片？", TaskType.MEDICATION_ALLERGY_CHECK),
        ("我可以自己停药吗？", TaskType.MEDICATION_ALLERGY_CHECK),
        ("孩子可以吃布洛芬吗？", TaskType.MEDICATION_ALLERGY_CHECK),
        ("我对什么药物过敏？", TaskType.MEDICATION_ALLERGY_CHECK),
        # 一般药物教育（不得误归用药核对）
        ("阿莫西林是治什么的？", TaskType.GENERAL_HEALTH_EDUCATION),
        ("缬沙坦一般什么时候吃比较好？", TaskType.GENERAL_HEALTH_EDUCATION),
        ("这个药有什么副作用？", TaskType.GENERAL_HEALTH_EDUCATION),
        ("布洛芬是饭前吃还是饭后吃？", TaskType.GENERAL_HEALTH_EDUCATION),
        # 场景 1：病历事实核验
        ("我以前被诊断过高血压吗？", TaskType.FACT_VERIFICATION),
        ("上次接诊我的医生是谁？", TaskType.FACT_VERIFICATION),
        ("我做过什么手术？", TaskType.FACT_VERIFICATION),
        ("我的紧急联系人是谁？", TaskType.FACT_VERIFICATION),
        ("孩子上次发热是什么时候？", TaskType.FACT_VERIFICATION),
        ("我上次在消化内科看了什么？", TaskType.FACT_VERIFICATION),
        # 场景 4：证据不足与冲突（任务归类到事实/用药，判定由证据策略完成）
        ("我做过阑尾炎手术吗？", TaskType.FACT_VERIFICATION),
        ("我青霉素过敏，能用头孢吗？", TaskType.MEDICATION_ALLERGY_CHECK),
        # P1：一般健康教育
        ("高血压日常生活中应注意什么？", TaskType.GENERAL_HEALTH_EDUCATION),
    ],
)
def test_route_question_classifies_golden_scenarios(question, expected_task):
    route = route_question(question)
    assert route.task is expected_task


def test_route_question_falls_back_to_non_individualized_education():
    route = route_question("你好，随便聊聊")
    assert route.task is TaskType.GENERAL_HEALTH_EDUCATION
    assert route.route_reason == "fallback_non_individualized"
    assert RetrievalSource.CLINICAL_KNOWLEDGE in route.sources


def test_risk_triage_route_forbids_self_treatment():
    route = route_question("我胸口疼得厉害，喘不上气怎么办？")
    assert route.task is TaskType.RISK_TRIAGE
    assert "self_treatment" in route.forbidden_actions
    assert "diagnosis" in route.forbidden_actions
    assert route.sources == [RetrievalSource.NO_RETRIEVAL]
    assert route.max_retrieval_rounds == 0


def test_medication_route_carries_required_facts_and_forbidden_actions():
    route = route_question("我对什么药物过敏？")
    assert route.task is TaskType.MEDICATION_ALLERGY_CHECK
    assert route.required_facts == ["allergy_history"]
    assert "dose_change" in route.forbidden_actions
    assert "stop_medication" in route.forbidden_actions
    assert route.max_retrieval_rounds <= 2


def test_current_medications_lookup_only_requires_medications():
    route = route_question("我现在在吃什么药？")
    assert route.task is TaskType.MEDICATION_ALLERGY_CHECK
    assert route.required_facts == ["current_medications"]
    assert "dose_change" in route.forbidden_actions
    assert "stop_medication" in route.forbidden_actions
    assert route.max_retrieval_rounds <= 2


def test_individualized_dose_requires_allergy_and_medications():
    route = route_question("缬沙坦我应该吃几片？")
    assert route.task is TaskType.MEDICATION_ALLERGY_CHECK
    assert route.required_facts == ["allergy_history", "current_medications"]
    assert "dose_change" in route.forbidden_actions
    assert "stop_medication" in route.forbidden_actions
    assert route.max_retrieval_rounds <= 2


def test_drug_education_route_has_no_required_facts():
    route = route_question("阿莫西林是治什么的？")
    assert route.task is TaskType.GENERAL_HEALTH_EDUCATION
    assert route.required_facts == []
    assert "individualized_advice" in route.forbidden_actions


def test_individualized_dose_still_routes_to_medication_check():
    route = route_question("缬沙坦我应该吃几片？")
    assert route.task is TaskType.MEDICATION_ALLERGY_CHECK


def test_fact_verification_route_requires_no_llm_rewrite():
    route = route_question("我做过什么手术？")
    assert route.task is TaskType.FACT_VERIFICATION
    assert "diagnosis_inference" in route.forbidden_actions
    assert route.max_retrieval_rounds == 0


def test_every_task_type_has_a_default_route():
    for task in TaskType:
        route = route_for_task(task)
        assert route.task is task
        assert route.max_retrieval_rounds <= 2
