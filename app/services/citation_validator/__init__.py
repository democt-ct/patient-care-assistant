"""Expanded deterministic citation validation for medical claims."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Optional

_legacy_path = Path(__file__).resolve().parent.parent / "citation_validator.py"
exec(compile(_legacy_path.read_bytes(), str(_legacy_path), "exec"), globals(), globals())

_legacy_validate_answer = validate_answer
_PERCENT_RE = re.compile(r"\d+(?:\.\d+)?\s*%")
_MEDICAL_ENTITY_RE = re.compile(
    r"高血压|糖尿病|冠心病|心肌梗死|脑卒中|肺炎|哮喘|肾功能不全|肝功能异常|"
    r"手术|置换术|切除术|HbA1c|糖化血红蛋白|肌酐|转氨酶|血压|血糖"
)


def validate_answer(answer: str, pack: EvidencePack, *, task: Optional[str] = None) -> CitationReport:
    report = _legacy_validate_answer(answer, pack, task=task)
    if not answer or task == "general_health_education":
        return report
    pack_text = _pack_text(pack)

    for claim in _PERCENT_RE.findall(answer):
        if claim.lower() in pack_text:
            report.supported_claims.append(claim)
        elif claim not in report.unsupported_claims:
            report.unsupported_claims.append(claim)

    for claim in _MEDICAL_ENTITY_RE.findall(answer):
        if claim.lower() in pack_text:
            report.supported_claims.append(claim)
        elif claim not in report.unsupported_claims:
            report.unsupported_claims.append(claim)
    return report
