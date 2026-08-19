"""Claim 提取（Bounded Safety）—— 把回答拆成可验证的论断。

优先使用 LLM 结构化提取（输出 JSON Claim 列表）；超时/失败/关闭时回退到
确定性分句 + 关键词/实体分类，保证链路不中断。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Optional

from app.schemas.retrieval import (
    Claim,
    ClaimType,
    EvidenceSourceType,
    TaskContract,
)


def _extraction_enabled() -> bool:
    return os.getenv("CLAIM_EXTRACTION_ENABLED", "true").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

_SENTENCE_SPLIT = re.compile(r"(?<=[。！？；\n])")

_PATIENT_MARKERS = (
    "我", "你", "您", "孩子", "该患者", "这位患者", "本人", "上次", "目前", "正在",
    "记录", "病历", "就诊", "过敏史", "诊断", "手术", "最近", "复诊",
    "服用", "用药", "检查",
)
_INTERPRETATION_MARKERS = (
    "控制", "改善", "恶化", "正常", "异常", "升高", "下降", "稳定",
    "良好", "较前", "相比", "趋势", "原因", "关系",
)
_FORBIDDEN_VERBS = (
    "停药", "减量", "加量", "换药", "停用", "替换", "开药", "处方",
    "剂量", "吃几片", "吃多少",
)
_RECOMMENDATION_MARKERS = (
    "建议", "应该", "应当", "需要", "可以", "不要", "不能", "请", "务必",
)
_GENERIC_CARE_MARKERS = (
    "就医", "拨打 120", "急诊", "热线", "复诊", "监测", "休息", "饮食",
    "运动", "低盐", "多喝水", "测量", "咨询医生", "咨询药师", "遵医嘱",
    "医生指导", "药师指导", "指导下",
)

_REQUIRED_BY_TYPE: dict[ClaimType, list[EvidenceSourceType]] = {
    ClaimType.PATIENT_FACT: [EvidenceSourceType.PATIENT_RECORD],
    ClaimType.GENERAL_KNOWLEDGE: [
        EvidenceSourceType.REVIEWED_KNOWLEDGE,
        EvidenceSourceType.TRUSTED_MEDICAL_SOURCE,
    ],
    ClaimType.CLINICAL_INTERPRETATION: [
        EvidenceSourceType.PATIENT_RECORD,
        EvidenceSourceType.REVIEWED_KNOWLEDGE,
    ],
    ClaimType.RECOMMENDATION: [
        EvidenceSourceType.PATIENT_RECORD,
        EvidenceSourceType.TRUSTED_MEDICAL_SOURCE,
    ],
    ClaimType.ACTION: [
        EvidenceSourceType.PATIENT_RECORD,
        EvidenceSourceType.TRUSTED_MEDICAL_SOURCE,
    ],
}

_EXTRACTION_SYSTEM_PROMPT = """你是医疗回答的【论断提取器】。把回答拆成互不重叠的关键论断，每条只保留一句话级别的断言。

论断类型（claim_type）：
- patient_fact：涉及患者个人的事实（诊断、过敏、用药、手术、就诊、医生、复诊等）
- general_knowledge：一般医学/药物知识（不针对个人）
- clinical_interpretation：对患者记录/指标/症状的判断或解读（如“控制良好”“指标升高”）
- recommendation：给用户的行动建议（含“建议/应该/不要”等）
- action：直接以祈使句给出的动作（如“停药”“减量”“拨打 120”）

required_evidence_types 从以下枚举中选择该论断需要的证据：
- patient_record：患者结构化记录
- reviewed_knowledge：已审核知识
- trusted_medical_source：可信医学来源（说明书/指南）
- model_knowledge：模型知识（仅低风险通识允许）

严格输出 JSON（不要输出其他文字）：
{"claims": [{"text": "论断原文", "claim_type": "patient_fact|general_knowledge|clinical_interpretation|recommendation|action", "required_evidence_types": ["..." ]}]}

约束：
- text 必须来自回答原文，不得改写、不得新增内容。
- 不含关键论断的句子（如“好的”“请问还有什么需要帮助的吗”）不要输出。
"""


def _classify_deterministic(text: str) -> ClaimType:
    """确定性论断类型分类（兜底）。"""
    has_forbidden = any(marker in text for marker in _FORBIDDEN_VERBS)
    if has_forbidden:
        if any(marker in text for marker in _RECOMMENDATION_MARKERS):
            return ClaimType.RECOMMENDATION
        return ClaimType.ACTION
    has_patient = any(marker in text for marker in _PATIENT_MARKERS)
    has_interpretation = any(marker in text for marker in _INTERPRETATION_MARKERS)
    if has_patient and has_interpretation:
        return ClaimType.CLINICAL_INTERPRETATION
    if has_patient:
        return ClaimType.PATIENT_FACT
    if any(marker in text for marker in _RECOMMENDATION_MARKERS) or any(
        marker in text for marker in _GENERIC_CARE_MARKERS
    ):
        return ClaimType.RECOMMENDATION
    return ClaimType.GENERAL_KNOWLEDGE


def _split_sentences(answer: str) -> list[str]:
    parts = [part.strip() for part in _SENTENCE_SPLIT.split(answer or "")]
    return [part for part in parts if part]


def _make_claim(claim_id: str, text: str, claim_type: ClaimType) -> Claim:
    return Claim(
        claim_id=claim_id,
        text=text[:500],
        claim_type=claim_type,
        required_evidence_types=list(_REQUIRED_BY_TYPE.get(claim_type, [])),
    )


def _extract_deterministic(answer: str) -> list[Claim]:
    claims: list[Claim] = []
    for index, sentence in enumerate(_split_sentences(answer), start=1):
        if len(sentence) < 2:
            continue
        claims.append(
            _make_claim(
                f"claim-{index:03d}",
                sentence,
                _classify_deterministic(sentence),
            )
        )
    return claims


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        return "".join(_content_to_text(item) for item in content)
    if isinstance(content, dict):
        return str(content.get("text") or content.get("content") or content)
    return str(content or "")


def _invoke_llm(llm: Any, prompt: str) -> str:
    response = llm.invoke(prompt)
    return _content_to_text(getattr(response, "content", response)).strip()


def _extract_json_object(text: str) -> Optional[dict[str, Any]]:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(cleaned[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return None
    return None


def _parse_llm_claims(raw: str, answer: str) -> list[Claim]:
    payload = _extract_json_object(raw)
    if not payload:
        return []
    claims: list[Claim] = []
    seen: set[str] = set()
    for index, item in enumerate(payload.get("claims") or [], start=1):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text or text in seen:
            continue
        if text not in answer:
            # LLM 可能改写；回退到回答中匹配到的句子
            matched = next(
                (sentence for sentence in _split_sentences(answer) if text in sentence),
                None,
            )
            if matched is None:
                continue
            text = matched
        seen.add(text)
        try:
            claim_type = ClaimType(str(item.get("claim_type") or "").strip().lower())
        except ValueError:
            claim_type = _classify_deterministic(text)
        raw_types = item.get("required_evidence_types") or []
        required: list[EvidenceSourceType] = []
        for raw_type in raw_types:
            try:
                required.append(EvidenceSourceType(str(raw_type).strip().lower()))
            except ValueError:
                continue
        if not required:
            required = list(_REQUIRED_BY_TYPE.get(claim_type, []))
        claims.append(
            Claim(
                claim_id=f"claim-{index:03d}",
                text=text[:500],
                claim_type=claim_type,
                required_evidence_types=required,
            )
        )
    return claims or _extract_deterministic(answer)


def extract_claims(
    question: str,
    answer: str,
    contract: Optional[TaskContract] = None,
    *,
    llm: Any = None,
) -> list[Claim]:
    """提取回答中的论断；LLM 失败/关闭时确定性兜底。"""
    if not answer or not answer.strip():
        return []
    if not _extraction_enabled():
        return _extract_deterministic(answer)
    if llm is None:
        try:
            from app.mcp.config import get_llm

            llm = get_llm()
        except Exception:
            llm = None
    if llm is None:
        return _extract_deterministic(answer)
    contract_block = ""
    if contract is not None:
        allowed = "、".join(claim.value for claim in contract.allowed_claim_types) or "无"
        contract_block = f"\n本轮任务允许的论断类型：{allowed}。只提取回答中实际存在的论断，不要补齐任务期望的类型。"
    prompt = (
        _EXTRACTION_SYSTEM_PROMPT
        + contract_block
        + f"\n\n用户问题：{question}\n回答：{answer}"
    )
    try:
        raw = _invoke_llm(llm, prompt)
        if raw and raw.strip():
            parsed = _parse_llm_claims(raw, answer)
            if parsed:
                return parsed
    except Exception:
        pass
    return _extract_deterministic(answer)
