"""导入规则手册知识块（review_status=approved，走治理准入）。

用法:
  python scripts/import_rulebook_knowledge.py           # 校验并导出 JSON 清单
  python scripts/import_rulebook_knowledge.py --ingest  # 额外写入 Chroma（需本地嵌入可用）

运行时注入使用 ``app/config/rulebook_knowledge.py`` 的确定性检索（按任务取块），
本脚本负责治理准入校验与可审计导出。
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config.rulebook_knowledge import RULEBOOK_ENTRIES  # noqa: E402
from app.services.clinical_knowledge_governance import (  # noqa: E402
    validate_clinical_knowledge_payload,
)


def main() -> int:
    ingest = "--ingest" in sys.argv
    validated: list[dict] = []
    for entry in RULEBOOK_ENTRIES:
        normalized = validate_clinical_knowledge_payload(entry, allow_publish=True)
        validated.append(normalized)

    out_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data",
        "rulebook_knowledge.json",
    )
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(validated, handle, ensure_ascii=False, indent=2)
    print(f"validated {len(validated)} rulebook entries -> {out_path}")

    if ingest:
        print("--ingest：Chroma 向量化需要本地嵌入可用，默认跳过（运行时为确定性注入）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
