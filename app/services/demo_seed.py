"""Explicitly opt-in demo data for local product walkthroughs.

This module is never called unless ``DEMO_MODE=true``.  It deliberately uses
synthetic identities and an auditable chronic-disease follow-up scenario
rather than real data.

Scenario v2: 2 型糖尿病 + 高血压患者出院后随访。出院随访计划与出院小结
覆盖复诊/复查/监测三类待办、多个中文时间表达与一条不应被提取的句子
（体现规则引擎的克制），并带药物过敏史供智能问诊做过敏安全演示。
"""

from datetime import datetime

from sqlalchemy.orm import Session

from app.models.medical_record import MedicalRecord
from app.models.patient import Patient
from app.models.visit_record import VisitRecord
from app.services.care_plan_service import generate_care_plan


DEMO_HOSPITAL_ID = "demo-hospital"
DEMO_PATIENT_CODE = "DEMO-CARE-001"
SCENARIO_VERSION = "demo-v3"
SCENARIO_LABEL = "演示数据 v3：2型糖尿病 + 高血压随访（虚构）"


def ensure_demo_scenario(db: Session) -> Patient:
    patient = (
        db.query(Patient)
        .filter(Patient.hospital_id == DEMO_HOSPITAL_ID, Patient.patient_code == DEMO_PATIENT_CODE)
        .first()
    )
    # 场景升级时重建旧的演示病例（仅演示数据，级联清理就诊/病历/照护计划）。
    if patient and (patient.notes or "").startswith(SCENARIO_VERSION):
        return patient
    if patient:
        db.delete(patient)
        db.flush()

    patient = Patient(
        hospital_id=DEMO_HOSPITAL_ID,
        patient_code=DEMO_PATIENT_CODE,
        full_name="王秀兰（虚构）",
        gender="女",
        birth_date=datetime(1964, 3, 12).date(),
        phone="13800000000",
        address="演示市幸福路 88 号（虚构）",
        blood_type="A",
        allergy_history="磺胺类药物过敏（演示数据）",
        family_history="父亲患高血压，母亲患 2 型糖尿病（演示数据）",
        notes=f"{SCENARIO_VERSION}：{SCENARIO_LABEL}",
    )
    db.add(patient)
    db.flush()

    visit = VisitRecord(
        patient_id=patient.id,
        hospital_id=DEMO_HOSPITAL_ID,
        visit_type="出院随访",
        department="内分泌科",
        doctor_name="陈医生（演示）",
        chief_complaint="血糖控制不佳住院一周，出院后随访（演示数据）",
        visit_summary=(
            "2 型糖尿病伴血糖控制不佳，高血压 2 级；"
            "住院期间调整降糖方案后血糖平稳，准予出院（演示数据）。"
        ),
        follow_up_plan=(
            "出院两周后复诊内分泌科；"
            "一个月后复查糖化血红蛋白和空腹血糖；"
            "每周监测三次血糖并记录数值；"
            "三个月后复查尿微量白蛋白和肾功能；"
            "如出现低血糖或足部破溃请及时联系医院。"
        ),
        visit_date=datetime(2026, 7, 28, 10, 30),
    )
    db.add(visit)

    medical_record = MedicalRecord(
        patient_id=patient.id,
        hospital_id=DEMO_HOSPITAL_ID,
        record_type="出院小结",
        title="2 型糖尿病伴高血压出院小结",
        department="内分泌科",
        doctor_name="陈医生（演示）",
        chief_complaint="血糖控制不佳住院（演示数据）",
        diagnosis="2 型糖尿病伴血糖控制不佳；高血压 2 级（演示数据）",
        treatment_plan="出院后继续口服二甲双胍和氨氯地平；每天监测血糖并记录；两个月后复查血脂。",
        medications="二甲双胍、氨氯地平",
        notes="磺胺类过敏史，避免使用磺胺类药物（演示数据）。",
        record_date=datetime(2026, 7, 28, 11, 0),
    )
    db.add(medical_record)
    db.commit()

    generate_care_plan(db, patient_id=patient.id, source_type="visit_record", source_id=visit.id)
    generate_care_plan(db, patient_id=patient.id, source_type="medical_record", source_id=medical_record.id)
    return patient
