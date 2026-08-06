from app.services.structured_fact_answer import answer_from_structured_facts


def test_returns_recorded_medications_without_model_rewrite():
    answer = answer_from_structured_facts(
        question="我现在在吃什么药？",
        tool_name="get_medical_records",
        tool_result={"data": {"medical_records": [{"medications": "二甲双胍；格列美脲"}]}},
    )

    assert answer is not None
    assert "二甲双胍" in answer
    assert "格列美脲" in answer


def test_returns_diagnosis_and_follow_up_from_retrieved_records():
    diagnosis = answer_from_structured_facts(
        question="我的糖尿病诊断是什么？",
        tool_name="get_medical_records",
        tool_result={"data": {"medical_records": [{"diagnosis": "2型糖尿病，血糖控制不良"}]}},
    )
    follow_up = answer_from_structured_facts(
        question="我下次什么时候复诊？",
        tool_name="get_visit_records",
        tool_result={"data": {"visit_records": [{"follow_up_plan": "三周后复诊内分泌科"}]}},
    )

    assert diagnosis == "根据最近病历记录，诊断是：2型糖尿病，血糖控制不良。"
    assert follow_up == "最近就诊记录中的复诊安排是：三周后复诊内分泌科"


def test_returns_allergy_and_emergency_contact_from_patient_profile():
    result = {"data": {"patient": {"allergy_history": "磺胺类药物过敏", "emergency_contact_name": "张芳（女儿）"}}}

    assert "磺胺类药物过敏" in answer_from_structured_facts(question="我有什么药物过敏吗？", tool_name="get_patient_profile", tool_result=result)
    assert "张芳" in answer_from_structured_facts(question="我的紧急联系人是谁？", tool_name="get_patient_profile", tool_result=result)


def test_warns_against_a_recorded_allergy_medication():
    answer = answer_from_structured_facts(
        question="我可以用磺胺类抗生素吗？",
        tool_name="get_patient_profile",
        tool_result={"data": {"patient": {"allergy_history": "磺胺类药物过敏"}}},
    )

    assert answer is not None
    assert "磺胺" in answer
    assert "不能使用" in answer


def test_visit_date_answer_with_department():
    answer = answer_from_structured_facts(
        question="我最近一次去心内科是哪天？",
        tool_name="get_visit_records",
        tool_result={
            "data": {
                "visit_records": [
                    {"visit_date": "2025-12-01T00:00:00+00:00", "department": "心内科", "visit_type": "outpatient"},
                ],
            },
        },
    )

    assert answer is not None
    assert "2025-12-01" in answer
    assert "心内科" in answer


def test_cephalosporin_reconciliation_answer():
    answer = answer_from_structured_facts(
        question="磺胺过敏，可以用头孢吗？",
        tool_name="get_patient_profile",
        tool_result={
            "data": {
                "patient": {"allergy_history": "磺胺类药物过敏（全身皮疹+发热）；酒精过敏（面部潮红）"},
                "medical_records": [
                    {"department": "骨科", "medications": "头孢呋辛 1.5g iv q12h（预防感染）"},
                ],
            },
        },
    )

    assert answer is not None
    assert "头孢呋辛" in answer
    assert "医生或药师确认" in answer
