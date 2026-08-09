"""Small, source-verified public-health knowledge pack for patient education.

Entries are concise paraphrases with canonical public URLs.  They are limited
to health education and escalation signals; they are not drug labels or
individual treatment instructions.
"""

from __future__ import annotations

from typing import Any

from app.schemas.retrieval import RetrievalRoute, TaskType


OFFICIAL_HEALTH_ENTRIES: tuple[dict[str, Any], ...] = (
    {
        "source_id": "nhc_hypertension_2024",
        "source_name": "国家卫生健康委",
        "source_url": "https://www.nhc.gov.cn/ylyjs/gzdt/202407/256b4eb8398440a8811344c7be50a333.shtml",
        "version": "2024-07-01",
        "title": "高血压等慢性病营养和运动指导原则（2024年版）",
        "keywords": ("高血压", "血压", "低盐", "饮食", "运动"),
        "content": "健康教育要点：高血压的生活方式管理可围绕合理膳食、控制盐和油脂摄入、规律运动及体重管理展开；具体运动强度和治疗方案应结合医生建议。",
    },
    {
        "source_id": "china_cdc_rsv_2025",
        "source_name": "中国疾病预防控制中心",
        "source_url": "https://www.chinacdc.cn/jkkp/crb/qtcr/202502/t20250210_304202.html",
        "version": "2025-02-10",
        "title": "正确识别呼吸道合胞病毒感染，守护儿童健康",
        "keywords": ("儿童", "孩子", "发热", "咳嗽", "喘", "呼吸", "脱水", "嗜睡"),
        "content": "风险提示：儿童出现呼吸急促、明显喘息、精神状态差或嗜睡、喂养困难、口唇发青、尿量减少等情况，应尽快线下就医。",
    },
    {
        "source_id": "china_cdc_herpangina_2025",
        "source_name": "中国疾病预防控制中心",
        "source_url": "https://www.chinacdc.cn/jkkp/crb/bcr/202507/t20250723_308690.html",
        "version": "2025-07-23",
        "title": "儿童发热相关重症信号健康科普",
        "keywords": ("儿童", "孩子", "发热", "高热", "抽搐", "精神", "脱水"),
        "content": "风险提示：儿童发热伴持续嗜睡或异常烦躁、肢体抖动、呼吸急促、顽固高热或脱水时，提示可能需要紧急医疗评估。",
    },
)


def official_health_context_for(question: str, route: RetrievalRoute | None) -> list[dict[str, Any]]:
    """Return source-verified, low-risk education entries relevant to a query."""
    if route is not None and route.task not in {TaskType.GENERAL_HEALTH_EDUCATION, TaskType.RISK_TRIAGE}:
        return []
    text = (question or "").lower()
    return [
        {key: value for key, value in entry.items() if key != "keywords"}
        for entry in OFFICIAL_HEALTH_ENTRIES
        if any(keyword in text for keyword in entry["keywords"])
    ]
