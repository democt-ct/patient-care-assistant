"""模糊主诉澄清闭环：追问问卷 + 会话状态机（V2 阶段 2）。

设计依据：``docs/patient_medical_information_agent_design.md`` V2 章节。

- 非强信号模糊主诉（胸闷、头晕、乏力等）进入结构化追问问卷；
- 问卷字段：性质 / 部位 / 持续时间 / 伴随症状 / 危险因素；
- 问卷完成后追加「是否缓解」追问，未缓解升级为就医指引；
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
    r"胸闷|头晕|乏力|心悸|心慌|恶心|腹痛|头痛|咳嗽|失眠|没力气|不舒服|食欲不振",
)

# 强信号排除：命中的话不作为模糊主诉处理（也不应走到本模块，双保险）
_STRONG_SIGNAL_EXCLUSIONS = (
    r"胸痛|呼吸困难|喘不上气|昏迷|意识不清|抽搐|惊厥|大出血|大量出血|"
    r"自杀|轻生|不想活|割腕|晕厥|卒中|中风|心梗|心肌梗死",
)

# 追问问卷：字段名 → 问题话术
QUESTION_FLOW = [
    ("nature", "这个症状具体是怎样的？比如是持续性的还是阵发性的，活动或按压时会不会加重？"),
    ("location", "症状主要出现在哪个部位？"),
    ("duration", "这种情况持续多久了？是第一次出现还是反复出现？"),
    ("associated", "有没有伴随其他症状（比如出汗、恶心、发热）？"),
    ("risk_factors", "最近有没有熬夜、劳累、感冒、饮食变化等可能诱因？"),
]

RELIEF_QUESTION = "目前症状是否有所缓解？（回复“缓解了”或“没有缓解”）"

NON_RELIEF_PATTERNS = (r"没有|没缓解|未缓解|更严重|加重|还是难受|还是不舒服|没有好转",)
RELIEF_PATTERNS = (r"缓解|好转|没事了|好多了|减轻|好了",)

UPGRADE_GUIDANCE = (
    "你描述的症状在追问后仍未见缓解，建议尽快前往医疗机构就诊评估，不要拖延；"
    "如果症状突然加重或出现呼吸困难、意识异常等情况，请立即拨打 120 或前往急诊。"
)


@dataclass
class ClarificationState:
    """一次追问问卷的会话状态。"""

    session_id: str
    original_question: str
    step_index: int = 0
    answers: dict[str, str] = field(default_factory=dict)
    relief_asked: bool = False
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


def new_state(session_id: str, question: str) -> ClarificationState:
    return ClarificationState(session_id=session_id, original_question=(question or "").strip()[:200])


def next_prompt(state: ClarificationState) -> Optional[str]:
    """返回当前应展示的问题；问卷已完成时返回缓解追问。"""
    if state.completed_questionnaire():
        return RELIEF_QUESTION
    return QUESTION_FLOW[state.step_index][1]


def apply_answer(state: ClarificationState, answer: str) -> Optional[str]:
    """记录当前答案并推进；返回下一步问题，问卷刚完成时返回 None。"""
    if not state.completed_questionnaire():
        key, _ = QUESTION_FLOW[state.step_index]
        state.answers[key] = (answer or "").strip()[:200]
        state.step_index += 1
    if state.completed_questionnaire():
        return None
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
