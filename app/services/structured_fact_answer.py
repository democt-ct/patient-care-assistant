"""Deterministic, patient-readable answers for explicit record lookup questions."""

from __future__ import annotations

from typing import Any, Mapping, Optional


def _text(value: Any) -> str:
    return str(value or "").strip()


def _first_record(records: list[Mapping[str, Any]], *fields: str) -> Optional[Mapping[str, Any]]:
    for record in records:
        if any(_text(record.get(field)) for field in fields):
            return record
    return None


def answer_from_structured_facts(
    *,
    question: str,
    tool_name: str,
    tool_result: Mapping[str, Any],
) -> Optional[str]:
    """Answer narrow factual questions from retrieved records without an LLM rewrite.

    Returns ``None`` for questions that need synthesis or clinical judgement.
    """
    data = tool_result.get("data") or {}
    if not isinstance(data, Mapping):
        return None

    normalized = _text(question).lower()
    patient = data.get("patient") or {}
    medical_records = [item for item in (data.get("medical_records") or []) if isinstance(item, Mapping)]
    visit_records = [item for item in (data.get("visit_records") or []) if isinstance(item, Mapping)]

    if tool_name == "get_patient_profile":
        if any(keyword in normalized for keyword in ("紧急联系人", "联系人")):
            contact = _text(patient.get("emergency_contact_name"))
            if contact:
                return f"你登记的紧急联系人是 {contact}。"
        if "过敏" in normalized or any(drug in normalized for drug in ("磺胺", "青霉素", "头孢", "阿司匹林")):
            allergy = _text(patient.get("allergy_history"))
            if allergy:
                allergy_drugs = tuple(
                    drug for drug in ("磺胺", "青霉素", "头孢", "阿司匹林")
                    if drug in normalized and drug in allergy
                )
                if allergy_drugs and any(word in normalized for word in ("可以", "能否", "能不能", "是否", "能用", "使用")):
                    drug_names = "、".join(allergy_drugs)
                    return f"记录显示你对{drug_names}相关药物过敏，不能使用；请让医生或药师确认合适的替代方案。"
                return f"你已登记的过敏史是：{allergy}。"

    if tool_name in {"get_medical_records", "get_patient_profile"} and medical_records:
        if any(keyword in normalized for keyword in ("吃什么药", "什么药", "用药", "药物")):
            record = _first_record(medical_records, "medications")
            medications = _text(record.get("medications")) if record else ""
            if medications:
                return f"根据最近病历记录，你目前使用的药物是：{medications}。请以当前开方医生的医嘱为准，不要自行调整。"

        if "手术" in normalized:
            record = next(
                (
                    item for item in medical_records
                    if "手术" in " ".join(_text(item.get(field)) for field in ("title", "diagnosis", "present_illness", "treatment_plan"))
                ),
                None,
            )
            if record:
                date = _text(record.get("record_date")) or "日期未记录"
                title = _text(record.get("title")) or _text(record.get("diagnosis")) or "相关手术"
                return f"病历记录显示，你在 {date} 的记录为：{title}。"

        if any(keyword in normalized for keyword in ("诊断", "什么病", "疾病")):
            record = _first_record(medical_records, "diagnosis")
            diagnosis = _text(record.get("diagnosis")) if record else ""
            if diagnosis:
                return f"根据最近病历记录，诊断是：{diagnosis}。"

        if any(keyword in normalized for keyword in ("血糖", "hba1c", "糖化血红蛋白")):
            record = next(
                (
                    item for item in medical_records
                    if any(keyword in " ".join(_text(item.get(field)) for field in ("chief_complaint", "present_illness", "diagnosis")) for keyword in ("血糖", "HbA1c"))
                ),
                None,
            )
            if record:
                detail = _text(record.get("present_illness")) or _text(record.get("chief_complaint"))
                if detail:
                    return f"病历中记录的血糖情况：{detail}"

    if tool_name in {"get_visit_records", "get_patient_profile"} and visit_records:
        latest = visit_records[0]
        if any(keyword in normalized for keyword in ("医生是谁", "看病的医生", "就诊医生", "接诊医生")):
            doctor = _text(latest.get("doctor_name"))
            if doctor:
                return f"最近一次就诊的医生是 {doctor}。"
        if any(keyword in normalized for keyword in ("复诊", "复查", "下次", "什么时候")):
            follow_up = _text(latest.get("follow_up_plan"))
            if follow_up:
                return f"最近就诊记录中的复诊安排是：{follow_up}"
        if any(keyword in normalized for keyword in ("看了什么", "就诊", "看病")):
            summary = _text(latest.get("visit_summary"))
            if summary:
                return f"最近一次就诊记录：{summary}"

    return None
