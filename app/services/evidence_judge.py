"""LLM 证据法官（Evidence Judge）—— V2 双轨判定中的智能层。

设计依据：``docs/patient_medical_information_agent_design.md`` V2 章节。

- 确定性层（``evidence_policy.py``）保留为兜底基线；
- 智能层由 LLM 对「证据是否充分支撑回答」「是否存在规则未捕获的语义冲突」
  「回答中的每个关键论断是否有证据支持」做判定，输出结构化 verdict +
  claim → evidence_id 绑定；
- LLM 不可用 / 超时 / 返回空 / 解析失败时**静默返回 None**，由调用方降级到
  确定性判定，不允许因 LLM 失败导致链路崩溃。

隐私约束：prompt 只包含字段级患者事实摘要与回答文本，不含病历原文；返回的
``reason`` 只写判定摘要，不落日志原始回答。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Optional

from app.schemas.retrieval import (
    ClaimBinding,
    EvidenceJudgeResult,
    EvidenceJudgeVerdict,
    EvidencePack,
    RetrievalRoute,
)

EVIDENCE_JUDGE_ENABLED = os.getenv("EVIDENCE_JUDGE_ENABLED", "true").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
EVIDENCE_JUDGE_TIMEOUT_SECONDS = float(os.getenv("EVIDENCE_JUDGE_TIMEOUT_SECONDS", "8"))

_JUDGE_SYSTEM_PROMPT = """你是医疗信息 Agent 的【证据法官】。你只负责裁决证据与回答的关系，不诊断疾病、不给治疗建议。

你将看到：
1. 用户问题
2. Agent 生成的候选回答
3. 证据包（患者结构化事实摘要与已审核医学知识，均为字段级内容，不含病历原文）

请逐条判断回答中的关键事实性论断（药物、剂量、日期、诊断、过敏、手术、检查结果等）是否被证据包支持，并判断：
- 是否存在规则未捕获的语义冲突（两条证据含义相反，但字段名或日期表述不同）；
- 证据是否足够支撑回答所需的关键结论。

严格输出 JSON（不要输出任何其他文字）：
{"verdict": "supported|unsupported|conflict|insufficient", "claim_bindings": [{"claim": "论断摘要", "evidence_ids": ["证据ID"], "verdict": "supported|unsupported", "note": "简短说明"}], "reason": "一句话判定摘要"}

判定标准：
- supported：回答中的关键论断都能在证据包中找到依据，且证据充分。
- unsupported：回答包含证据包无法支持的关键论断（幻觉或编造）。
- conflict：证据包内存在语义冲突，即便字段或日期表述不同。
- insufficient：证据不足以支撑回答所需的关键结论。

约束：
- evidence_ids 只能引用证据包中真实存在的 evidence_id；没有依据的论断 evidence_ids 留空数组。
- claim 写回答中的短论断摘要即可，不要复制病历原文。
"""


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        return "".join(_content_to_text(item) for item in content)
    if isinstance(content, dict):
        return str(content.get("text") or content.get("content") or content)
    return str(content or "")


def _invoke_llm(llm: Any, prompt: str) -> str:
    """调用 LLM 并返回文本；异常向上抛出，由 judge_evidence 捕获。"""
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


def _build_judge_prompt(
    question: str,
    answer: str,
    pack: EvidencePack,
    route: Optional[RetrievalRoute],
) -> str:
    lines = [f"用户问题：{question}", f"候选回答：{answer}", "证据包："]
    if not pack.items and not pack.knowledge_hits:
        lines.append("（空，未检索到任何证据）")
    for item in pack.items:
        lines.append(f"- evidence_id={item.evidence_id} 字段={item.field} 值={item.value[:200]}")
    for hit in pack.knowledge_hits:
        lines.append(f"- knowledge hit: {str(hit.get('content', ''))[:200]}")
    if route is not None:
        lines.append(f"任务类型：{route.task.value}")
        if route.forbidden_actions:
            lines.append(f"禁止动作：{'、'.join(route.forbidden_actions)}")
    return "\n".join(lines)


def _parse_judge_response(raw: str, pack: EvidencePack) -> Optional[EvidenceJudgeResult]:
    payload = _extract_json_object(raw)
    if not payload:
        return None
    raw_verdict = str(payload.get("verdict") or "").strip().lower()
    try:
        verdict = EvidenceJudgeVerdict(raw_verdict)
    except ValueError:
        return None

    bindings: list[ClaimBinding] = []
    pack_ids = {item.evidence_id for item in pack.items}
    for item in payload.get("claim_bindings") or []:
        if not isinstance(item, dict):
            continue
        claim = str(item.get("claim") or "").strip()
        if not claim:
            continue
        raw_binding_verdict = str(item.get("verdict") or verdict.value).strip().lower()
        try:
            binding_verdict = EvidenceJudgeVerdict(raw_binding_verdict)
        except ValueError:
            binding_verdict = verdict
        evidence_ids = [
            str(eid)
            for eid in (item.get("evidence_ids") or [])
            if str(eid) in pack_ids
        ][:20]
        bindings.append(
            ClaimBinding(
                claim=claim[:200],
                evidence_ids=evidence_ids,
                verdict=binding_verdict,
                note=str(item.get("note") or "")[:200],
            )
        )
    return EvidenceJudgeResult(
        verdict=verdict,
        claim_bindings=bindings,
        reason=str(payload.get("reason") or "")[:300],
        judge_source="llm",
    )


def judge_evidence(
    question: str,
    answer: str,
    pack: EvidencePack,
    route: Optional[RetrievalRoute] = None,
    *,
    llm: Any = None,
) -> Optional[EvidenceJudgeResult]:
    """LLM 证据法官入口；任何失败都返回 None（由确定性层兜底）。

    ``llm`` 可注入（测试用）；为 None 时按配置获取默认 LLM。
    """
    if not EVIDENCE_JUDGE_ENABLED:
        return None
    if llm is None:
        try:
            from app.mcp.config import get_llm

            llm = get_llm()
        except Exception:
            return None
    if llm is None:
        return None
    prompt = _build_judge_prompt(question, answer, pack, route)
    try:
        raw = _invoke_llm(llm, prompt)
    except Exception:
        return None
    if not raw or not raw.strip():
        return None
    return _parse_judge_response(raw, pack)
