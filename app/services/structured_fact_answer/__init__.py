"""Patient-readable fact answers with conservative medication wording."""

from __future__ import annotations

from pathlib import Path

_legacy_path = Path(__file__).resolve().parent.parent / "structured_fact_answer.py"
exec(compile(_legacy_path.read_bytes(), str(_legacy_path), "exec"), globals(), globals())

_legacy_answer_from_structured_facts = answer_from_structured_facts


def answer_from_structured_facts(*, question, tool_name, tool_result):
    answer = _legacy_answer_from_structured_facts(
        question=question,
        tool_name=tool_name,
        tool_result=tool_result,
    )
    if answer and "你目前使用的药物是" in answer:
        answer = answer.replace(
            "根据最近病历记录，你目前使用的药物是：",
            "根据最近病历记录，曾记录的用药包括：",
        ).replace(
            "请以当前开方医生的医嘱为准，不要自行调整。",
            "病历无法确认你现在是否仍在服用；请结合当前处方、药盒或向医生、药师核对，不要自行调整。",
        )
    return answer
