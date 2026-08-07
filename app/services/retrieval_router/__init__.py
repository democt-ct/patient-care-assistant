"""Retrieval routing with patient-specific medication context precedence."""

from __future__ import annotations

import re
from pathlib import Path

_legacy_path = Path(__file__).resolve().parent.parent / "retrieval_router.py"
exec(compile(_legacy_path.read_bytes(), str(_legacy_path), "exec"), globals(), globals())

_legacy_route_question = route_question  # noqa: F821
_PATIENT_CONTEXT = re.compile(
    r"我|本人|孩子|家人|孕妇|老人|过敏|高血压|糖尿病|肾病|肝病|正在吃|目前用药"
)
_DRUG_CONTEXT = re.compile(
    r"阿莫西林|头孢|青霉素|磺胺|布洛芬|阿司匹林|硝酸甘油|缬沙坦|氨氯地平|"
    r"二甲双胍|格列美脲|奥美拉唑|塞来昔布|他汀|药"
)
_SAFETY_CONTEXT = re.compile(r"禁忌|注意事项|能不能|可以吃|可以用|慎用|副作用|不良反应")


def route_question(question: str, *, context=None, llm=None) -> RetrievalRoute:  # noqa: F821
    text = (question or "").strip().lower()
    if (
        _PATIENT_CONTEXT.search(text)
        and _DRUG_CONTEXT.search(text)
        and _SAFETY_CONTEXT.search(text)
    ):
        return RetrievalRoute(  # noqa: F821
            task=TaskType.MEDICATION_ALLERGY_CHECK,  # noqa: F821
            sources=[RetrievalSource.STRUCTURED_PATIENT_FACT, RetrievalSource.CLINICAL_KNOWLEDGE],  # noqa: F821
            required_facts=["allergy_history", "current_medications"],
            forbidden_actions=["dose_change", "stop_medication", "start_medication", "drug_switch"],
            max_retrieval_rounds=1,
            route_reason="patient_specific_medication_context",
        )
    return _legacy_route_question(question, context=context, llm=llm)
