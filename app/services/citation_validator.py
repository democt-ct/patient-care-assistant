"""确定性引用校验：验证回答中的日期、数值、药物/诊断实体与 EvidenceItem 对应。

设计依据：``docs/执行计划.md`` 阶段 C。本模块独立负责引用验证；
``hallucination_guard`` 继续负责实体与危险内容检测，不承担引用验证职责。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from app.schemas.retrieval import EvidencePack

_KNOWN_DRUGS = (
    "青霉素", "头孢", "磺胺", "阿莫西林", "布洛芬", "阿司匹林", "硝酸甘油",
    "缬沙坦", "氨氯地平", "二甲双胍", "格列美脲", "奥美拉唑", "阿托伐他汀",
    "塞来昔布", "曲马多", "低分子肝素", "头孢呋辛", "厄贝沙坦", "铝碳酸镁",
)
_DATE_RE = re.compile(r"(?:19|20)\d{2}[-/年.]\d{1,2}(?:[-/月.]\d{1,2}日?)?")
_DOSE_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:mg|g|ml|μg|mcg|iu|mmol/l|mmhg|kg)\b", re.IGNORECASE)

# 教育性任务允许引用证据包之外的药物通用知识（如"阿莫西林是治什么的"）；
# 这些任务的回答不按个体化 claim 做证据包匹配，避免过度拒答。
_EDUCATIONAL_TASKS = ("general_health_education",)


@dataclass
class CitationReport:
    """引用校验结果。``valid`` 为 False 表示回答包含证据包无法支持的 claim。"""

    supported_claims: list[str] = field(default_factory=list)
    unsupported_claims: list[str] = field(default_factory=list)
    checked: bool = False

    @property
    def valid(self) -> bool:
        return not self.unsupported_claims


def _pack_text(pack: EvidencePack) -> str:
    parts = [item.value for item in pack.items]
    parts.extend(item.record_date or "" for item in pack.items if item.record_date)
    parts.extend(str(hit.get("content", "")) for hit in pack.knowledge_hits)
    return " ".join(parts).lower()


def validate_answer(
    answer: str,
    pack: EvidencePack,
    *,
    task: Optional[str] = None,
) -> CitationReport:
    """校验回答中的药物实体、日期和剂量是否被证据包支持。

    保守策略：回答中出现的已知药物 / 日期 / 剂量必须能在证据包中找到；
    找不到即标记为 unsupported。未出现在回答中的证据不校验。
    """
    report = CitationReport(checked=True)
    text = answer or ""
    if not text:
        return report
    if task in _EDUCATIONAL_TASKS:
        # 非个体化教育：不校验药物/剂量/日期是否在患者证据包中。
        return report
    pack_text = _pack_text(pack)

    for drug in _KNOWN_DRUGS:
        if drug in text:
            if drug in pack_text:
                report.supported_claims.append(drug)
            else:
                report.unsupported_claims.append(drug)

    for date in _DATE_RE.findall(text):
        if date in pack_text:
            report.supported_claims.append(date)
        else:
            report.unsupported_claims.append(date)

    for dose in _DOSE_RE.findall(text):
        if dose.lower() in pack_text:
            report.supported_claims.append(dose)
        else:
            report.unsupported_claims.append(dose)

    return report
