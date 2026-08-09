"""模糊主诉的最小信息澄清与安全行动建议。

设计依据：``docs/patient_medical_information_agent_design.md`` V2 章节。

- 非强信号模糊主诉（胸闷、头晕、头疼、乏力等）先收集一组会改变分流结果的最小信息；
- 患者补充后立即输出一般性行动建议、就医阈值和紧急红旗，而不是机械问完固定问卷；
- 安全边界不变：不给出诊断、处方、剂量或替代医生的个体化治疗方案；
- 每轮仍按风险评估：
  - 恶化信号（越来越重、冒冷汗、晕厥等）→ 立即升级就医指引；
  - 症状消失（不疼了、缓解了等）→ 清除问卷并收尾；
  - 症状消失（不疼了、缓解了等）→ 收尾并提示复发时重新评估；
- 澄清状态记录到会话（Redis 优先，内存兜底），且不改变安全红线判定
  （安全门禁始终在澄清之前执行，强信号不会进入本模块）。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Optional

CLARIFICATION_TTL_SECONDS = int(os.getenv("CLARIFICATION_TTL_SECONDS", "3600"))

# 模糊主诉关键词（非强信号；强信号由安全门禁先行短路）
VAGUE_SYMPTOM_PATTERNS = (
    r"胸闷|头晕|头疼|头痛|头胀|头部不适|晕眩|乏力|心悸|心慌|恶心|腹痛|咳嗽|失眠|没力气|不舒服|食欲不振",
)

# 强信号排除：命中的话不作为模糊主诉处理（也不应走到本模块，双保险）
_STRONG_SIGNAL_EXCLUSIONS = (
    r"胸痛|呼吸困难|喘不上气|昏迷|意识不清|抽搐|惊厥|大出血|大量出血|"
    r"自杀|轻生|不想活|割腕|晕厥|卒中|中风|心梗|心肌梗死",
)

# 恶化信号：任意一轮回答命中 → 立即升级就医指引（按步风险评估）
WORSENING_PATTERNS = (
    r"越来越|更严重|明显加重|加重很多|冒冷汗|冷汗|发晕|站不稳|晕倒|晕厥|"
    r"呼吸困难|喘不上气|意识不清|疼得受不了|痛得受不了",
)

# 症状消失/缓解表述：命中 → 清除当前问卷并收尾
SYMPTOM_CLEARED_PATTERNS = (
    r"不疼了|不痛了|好了|缓解|没事了|消失了|减轻了|不晕了|不恶心了",
)

# 否定的缓解表述：不得当作“症状消失”
_NEGATED_CLEARED_PATTERNS = (
    r"没有缓解|没缓解|未缓解|没有好转|没好转|没有减轻|没减轻|还是疼|还是痛|还是难受",
)

# 一次追问仅收集会改变分流结果的最小信息。后续不把患者困在固定问卷中。
QUESTION_FLOW = [
    (
        "triage_facts",
        "为了先判断是否需要尽快就医，请用一句话补充：症状从什么时候开始、是突然很剧烈还是逐渐出现，"
        "以及有没有肢体无力、说话不清、意识异常、反复呕吐、发热或颈部发硬。",
    ),
]

QUESTION_ADVICE: dict[str, str] = {}
RELIEF_QUESTION = "如果症状反复、持续不缓解或加重，请再次告诉我或尽快线下就医。"
MID_RELIEF_QUESTION = RELIEF_QUESTION

NON_RELIEF_PATTERNS = (r"没有|没缓解|未缓解|更严重|加重|还是难受|还是不舒服|没有好转",)
RELIEF_PATTERNS = (r"缓解|好转|没事了|好多了|减轻|好了|不疼",)

UPGRADE_GUIDANCE = (
    "你描述的症状在追问后仍未见缓解或出现加重，建议尽快前往医疗机构就诊评估，不要拖延；"
    "如果症状突然加重或出现呼吸困难、意识异常等情况，请立即拨打 120 或前往急诊。"
)

# 关键字段：以最近一次为准覆盖；其余字段按追加语义处理
KEY_OVERWRITE_FIELDS = ("triage_facts",)

MID_RELIEF = "MID_RELIEF"


@dataclass
class ClarificationState:
    """一次追问问卷的会话状态。"""

    session_id: str
    original_question: str
    step_index: int = 0
    answers: dict[str, str] = field(default_factory=dict)
    updates: list[str] = field(default_factory=list)
    relief_asked: bool = False
    mid_relief_asked: bool = False
    waiting_mid_relief: bool = False
    upgraded: bool = False

    def completed_questionnaire(self) -> bool:
        return self.step_index >= len(QUESTION_FLOW)


def classify_vague_symptom(question: str) -> bool:
    """判断是否属于模糊主诉（非强信号）。"""
    text = (question or "").strip()
    if not text:
        return False
    if re.search("|".join(_STRONG_SIGNAL_EXCLUSIONS), text, re.IGNORECASE):
        return False
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in VAGUE_SYMPTOM_PATTERNS)


def classify_worsening(answer: str) -> bool:
    """按步风险评估：回答是否包含恶化信号。"""
    text = (answer or "").strip()
    if not text:
        return False
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in WORSENING_PATTERNS)


def symptom_cleared(answer: str) -> bool:
    """是否出现症状消失/缓解表述（排除“没有缓解”等否定形式）。"""
    text = (answer or "").strip()
    if not text:
        return False
    if re.search("|".join(_NEGATED_CLEARED_PATTERNS), text, re.IGNORECASE):
        return False
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in SYMPTOM_CLEARED_PATTERNS)


def new_state(session_id: str, question: str) -> ClarificationState:
    return ClarificationState(session_id=session_id, original_question=(question or "").strip()[:200])


def next_prompt(state: ClarificationState) -> Optional[str]:
    """返回当前应展示的问题；问卷已完成时返回缓解追问。"""
    if state.completed_questionnaire():
        return RELIEF_QUESTION
    return QUESTION_FLOW[state.step_index][1]


def apply_answer(state: ClarificationState, answer: str) -> Optional[str]:
    """记录当前答案并推进；返回下一步问题，或 MID_RELIEF（中途缓解确认），问卷完成返回 None。

    症状更新语义：关键字段覆盖并记录变更（updates），补充字段追加。
    """
    if state.completed_questionnaire():
        return None
    key, _ = QUESTION_FLOW[state.step_index]
    value = (answer or "").strip()[:200]
    previous = state.answers.get(key)
    if previous is not None and previous != value:
        state.updates.append(f"{key}:{previous}→{value}")
    state.answers[key] = value
    state.step_index += 1

    return None if state.completed_questionnaire() else QUESTION_FLOW[state.step_index][1]


def build_safe_symptom_guidance(state: ClarificationState) -> str:
    """Build a non-diagnostic, actionable response after minimal triage facts.

    The response deliberately distinguishes general self-care from individual
    medical decisions. Red flags themselves are handled earlier by the safety
    gate / worsening detector and never depend on this text.
    """
    facts = state.answers.get("triage_facts", "").strip()
    facts_line = f"我已记录你补充的情况：{facts}。\n\n" if facts else ""
    return (
        f"{facts_line}目前这些信息不足以判断具体病因，我不能据此替代医生作诊断或开药。"
        "但如果当前没有突发剧烈加重或上述警示信号，症状较轻时可以先休息、补充水分、"
        "减少熬夜和长时间用眼，暂时避免自行叠加或调整药物。\n\n"
        "建议你观察症状是否持续、反复或影响日常生活；出现这种情况时，预约线下门诊评估。\n\n"
        "如果出现突然剧烈加重、肢体无力或麻木、说话不清、意识异常、反复呕吐，"
        "或伴高热和颈部发硬，请立即前往急诊或拨打 120。"
    )


def classify_relief(answer: str) -> Optional[bool]:
    """True=已缓解；False=未缓解；None=无法判断。"""
    text = (answer or "").strip()
    if not text:
        return None
    if re.search("|".join(NON_RELIEF_PATTERNS), text, re.IGNORECASE):
        return False
    if re.search("|".join(RELIEF_PATTERNS), text, re.IGNORECASE):
        return True
    return None


class ClarificationStore:
    """会话状态存储：Redis 优先，内存兜底（测试/离线可用）。"""

    def __init__(self) -> None:
        self._memory: dict[str, str] = {}
        self._backend: object = None

    def _get_backend(self):
        if self._backend is None:
            try:
                from app.core.redis_client import get_redis_client

                self._backend = get_redis_client()
            except Exception:
                self._backend = False
        return self._backend

    @staticmethod
    def _key(session_id: str) -> str:
        return f"clarification:{session_id}"

    def get(self, session_id: str) -> Optional[ClarificationState]:
        if not session_id:
            return None
        raw: Optional[str] = None
        backend = self._get_backend()
        if backend:
            try:
                raw = backend.get(self._key(session_id))
            except Exception:
                raw = None
        if raw is None:
            raw = self._memory.get(session_id)
        if not raw:
            return None
        try:
            payload = json.loads(raw)
            return ClarificationState(**payload)
        except Exception:
            return None

    def set(self, state: ClarificationState) -> None:
        payload = json.dumps(asdict(state), ensure_ascii=False)
        backend = self._get_backend()
        if backend:
            try:
                backend.set(self._key(state.session_id), payload, ex=CLARIFICATION_TTL_SECONDS)
            except Exception:
                pass
        self._memory[state.session_id] = payload

    def clear(self, session_id: str) -> None:
        backend = self._get_backend()
        if backend:
            try:
                backend.delete(self._key(session_id))
            except Exception:
                pass
        self._memory.pop(session_id, None)


_store: Optional[ClarificationStore] = None


def get_clarification_store() -> ClarificationStore:
    global _store
    if _store is None:
        _store = ClarificationStore()
    return _store
