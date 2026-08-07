from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.memory_preference import MemoryPreference
from app.services.patient_service import get_patient


def get_memory_preference(db: Session, patient_id: str) -> MemoryPreference:
    preference = db.query(MemoryPreference).filter(MemoryPreference.patient_id == patient_id).first()
    if not preference:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="当前患者尚未配置长期记忆偏好",
        )
    return preference


def get_memory_preference_optional(db: Session, patient_id: str) -> Optional[MemoryPreference]:
    return db.query(MemoryPreference).filter(MemoryPreference.patient_id == patient_id).first()


def preference_payload(pref: Optional[MemoryPreference]) -> Optional[dict[str, Any]]:
    """把偏好模型转成可注入提示词的字典（字段级，不含隐私备注）。"""
    if pref is None:
        return None
    return {
        "answer_style": pref.answer_style,
        "answer_length": pref.answer_length,
        "tone_style": pref.tone_style,
        "medical_term_level": pref.medical_term_level,
        "risk_alert_level": pref.risk_alert_level,
        "preferred_language": pref.preferred_language,
        "prefer_summary_first": bool(pref.prefer_summary_first),
        "prefer_step_by_step": bool(pref.prefer_step_by_step),
    }


def upsert_memory_preference(
    db: Session,
    *,
    patient_id: str,
    hospital_id: Optional[str],
    answer_style: str,
    answer_length: str,
    tone_style: str,
    medical_term_level: str,
    risk_alert_level: str,
    preferred_language: str,
    prefer_summary_first: bool,
    prefer_step_by_step: bool,
    notes: Optional[str],
) -> MemoryPreference:
    patient = get_patient(db, patient_id)
    if hospital_id and patient.hospital_id != hospital_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="hospital_id 与患者主档不匹配",
        )

    preference = get_memory_preference_optional(db, patient_id)
    if not preference:
        preference = MemoryPreference(
            patient_id=patient.id,
            hospital_id=patient.hospital_id,
        )
        db.add(preference)

    preference.hospital_id = patient.hospital_id
    preference.answer_style = answer_style
    preference.answer_length = answer_length
    preference.tone_style = tone_style
    preference.medical_term_level = medical_term_level
    preference.risk_alert_level = risk_alert_level
    preference.preferred_language = preferred_language
    preference.prefer_summary_first = prefer_summary_first
    preference.prefer_step_by_step = prefer_step_by_step
    preference.notes = notes.strip() if isinstance(notes, str) and notes.strip() else None

    db.commit()
    db.refresh(preference)
    return preference
