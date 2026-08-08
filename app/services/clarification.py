"""模糊主诉澄清闭环：追问问卷 + 会话状态机（V2 阶段 2 / 阶段 9 增强）。

设计依据：``docs/patient_medical_information_agent_design.md`` V2 章节。

- 非强信号模糊主诉（胸闷、头晕、头疼、乏力等）进入结构化追问问卷；
- 问卷字段：性质 / 部位 / 持续时间 / 伴随症状 / 危险因素，部位问题给出常见选项提示；
- 每题回答后给出通用安全建议（不给药物/个体化方案），并按步评估：
  - 恶化信号（越来越重、冒冷汗、晕厥等）→ 立即升级就医指引；
  - 症状消失（不疼了、缓解了等）→ 清除问卷并收尾；
  - 问卷进行到中途插入一次「是否缓解」确认，未缓解继续追问，最终缓解确认未缓解才升级；
- 症状更新语义：关键字段（性质/部位/持续时间）以最近一次为准覆盖并记录变更，
  补充字段追加，缓解/消失触发整份问卷状态清除；
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

# 追问问卷：字段名 → 问题话术（部位问题给出常见选项提示，兼容"头哪里疼"类询问）
QUESTION_FLOW = [
    ("nature", "这个症状具体是怎样的？比如是持续性的还是阵发性的，活动或按压时会不会加重？"),
    ("location", "症状主要出现在哪个部位？如果是头部不适，可以具体说说是额头、后脑勺、太阳穴，还是偏一侧？"),
    ("duration", "这种情况持续多久了？是第一次出现还是反复出现？"),
    ("associated", "有没有伴随其他症状（比如出汗、恶心、发热）？"),
    ("risk_factors", "最近有没有熬夜、劳累、感冒、饮食变化等可能诱因？"),
]

# 每题回答后的通用安全建议（非个体化，不含药物方案）
QUESTION_ADVICE = {
    "nature": "先休息、避免剧烈活动，暂时不要自行用药。",
    "location": "可以轻轻按摩或热敷不适部位，但要注意疼痛是否转移或加剧。",
    "duration": "如果症状持续较久或反复发作，建议尽快就医评估。",
    "associated": "出现出汗、恶心、发热等伴随症状时请密切观察，必要时及时就医。",
    "risk_factors": "减少熬夜和劳累，避免长时间待在空调房，注意补水。",
}

RELIEF_QUESTION = "目前症状是否有所缓解？（回复“缓解了”或“没有缓解”）"
MID_RELIEF_QUESTION = "目前症状有没有缓解？如果没有缓解也没关系，我们继续了解几个细节。"

NON_RELIEF_PATTERNS = (r"没有|没缓解|未缓解|更严重|加重|还是难受|还是不舒服|没有好转",)
RELIEF_PATTERNS = (r"缓解|好转|没事了|好多了|减轻|好了|不疼",)

UPGRADE_GUIDANCE = (
    "你描述的症状在追问后仍未见缓解或出现加重，建议尽快前往医疗机构就诊评估，不要拖延；"
    "如果症状突然加重或出现呼吸困难、意识异常等情况，请立即拨打 120 或前往急诊。"
)

# 关键字段：以最近一次为准覆盖；其余字段按追加语义处理
KEY_OVERWRITE_FIELDS = ("nature", "location", "duration")

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

    if state.completed_questionnaire():
        return None
    if state.step_index == 2 and not state.mid_relief_asked:
        state.mid_relief_asked = True
        return MID_RELIEF
    return QUESTION_FLOW[state.step_index][1]


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