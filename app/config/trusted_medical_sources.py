"""可信医学来源注册表（Trusted Medical Source，Bounded Safety 第二层证据）。

策展条目为药品说明书 / 权威指南级别的通用事实（作用机制、适应症、一般
注意事项），**不包含个体化剂量**。每条带 source_id / 版本 / 审核标记，
命中后作为 ``TRUSTED_MEDICAL_SOURCE`` 证据注入。

第一期覆盖种子数据与评估用例涉及的常见药物；后续按治理流程扩充。
"""

from __future__ import annotations

from typing import Any

from app.schemas.retrieval import RetrievalRoute, TaskType

TRUSTED_MEDICAL_ENTRIES: tuple[dict[str, Any], ...] = (
    {
        "source_id": "drug_label_aspirin",
        "source_name": "药品说明书（阿司匹林）",
        "source_url": "https://www.nmpa.gov.cn/",
        "version": "2026-01-01",
        "title": "阿司匹林通用药品信息",
        "keywords": ("阿司匹林",),
        "content": (
            "阿司匹林具有解热镇痛作用，并可用于抗血小板聚集以降低血栓风险；"
            "具体适应症、剂量与疗程必须由医生根据病情决定，擅自停药、减量或加量可能增加出血或血栓风险。"
        ),
        "review_status": "approved",
    },
    {
        "source_id": "drug_label_ibuprofen",
        "source_name": "药品说明书（布洛芬）",
        "source_url": "https://www.nmpa.gov.cn/",
        "version": "2026-01-01",
        "title": "布洛芬通用药品信息",
        "keywords": ("布洛芬",),
        "content": (
            "布洛芬为非甾体抗炎药，用于解热镇痛；儿童用量需按体重并遵医嘱，"
            "哮喘、过敏或肾功能异常患者使用前应咨询医生。"
        ),
        "review_status": "approved",
    },
    {
        "source_id": "drug_label_valsartan",
        "source_name": "药品说明书（缬沙坦）",
        "source_url": "https://www.nmpa.gov.cn/",
        "version": "2026-01-01",
        "title": "缬沙坦通用药品信息",
        "keywords": ("缬沙坦",),
        "content": (
            "缬沙坦为血管紧张素 II 受体拮抗剂类降压药；剂量调整与联合用药必须由医生进行，"
            "孕妇及严重肝肾功能不全者使用需医生评估。"
        ),
        "review_status": "approved",
    },
    {
        "source_id": "drug_label_amlodipine",
        "source_name": "药品说明书（氨氯地平）",
        "source_url": "https://www.nmpa.gov.cn/",
        "version": "2026-01-01",
        "title": "氨氯地平通用药品信息",
        "keywords": ("氨氯地平",),
        "content": (
            "氨氯地平为钙通道阻滞剂类降压药；具体剂量与合并用药需遵医嘱，"
            "出现明显低血压或水肿等不良反应应及时就医。"
        ),
        "review_status": "approved",
    },
    {
        "source_id": "drug_label_metformin",
        "source_name": "药品说明书（二甲双胍）",
        "source_url": "https://www.nmpa.gov.cn/",
        "version": "2026-01-01",
        "title": "二甲双胍通用药品信息",
        "keywords": ("二甲双胍",),
        "content": (
            "二甲双胍为口服降糖药，用于 2 型糖尿病血糖管理；剂量调整需遵医嘱，"
            "严重肾功能不全或急性代谢紊乱时禁用，需由医生评估。"
        ),
        "review_status": "approved",
    },
    {
        "source_id": "drug_label_gliclazide",
        "source_name": "药品说明书（格列美脲）",
        "source_url": "https://www.nmpa.gov.cn/",
        "version": "2026-01-01",
        "title": "格列美脲通用药品信息",
        "keywords": ("格列美脲",),
        "content": (
            "格列美脲为磺脲类口服降糖药，可能引起低血糖；剂量与用药时间必须遵医嘱，"
            "出现心慌、出汗、意识改变等低血糖信号时应立即就医。"
        ),
        "review_status": "approved",
    },
    {
        "source_id": "drug_label_omeprazole",
        "source_name": "药品说明书（奥美拉唑）",
        "source_url": "https://www.nmpa.gov.cn/",
        "version": "2026-01-01",
        "title": "奥美拉唑通用药品信息",
        "keywords": ("奥美拉唑",),
        "content": (
            "奥美拉唑为质子泵抑制剂，用于胃酸相关疾病；疗程与剂量需遵医嘱，"
            "长期用药的风险评估由医生进行。"
        ),
        "review_status": "approved",
    },
    {
        "source_id": "drug_label_cefuroxime",
        "source_name": "药品说明书（头孢呋辛）",
        "source_url": "https://www.nmpa.gov.cn/",
        "version": "2026-01-01",
        "title": "头孢呋辛通用药品信息",
        "keywords": ("头孢呋辛", "头孢"),
        "content": (
            "头孢呋辛为头孢类抗菌药，用于敏感菌感染；有青霉素或头孢过敏史者使用前必须由医生评估，"
            "禁止自行选用或更换抗菌药。"
        ),
        "review_status": "approved",
    },
    {
        "source_id": "drug_label_sulfonamide",
        "source_name": "药品说明书（磺胺类）",
        "source_url": "https://www.nmpa.gov.cn/",
        "version": "2026-01-01",
        "title": "磺胺类抗菌药通用信息",
        "keywords": ("磺胺",),
        "content": (
            "磺胺类为抗菌药；对磺胺过敏者禁止使用，过敏反应可能严重，"
            "是否可选用替代药物必须由医生或药师评估。"
        ),
        "review_status": "approved",
    },
    {
        "source_id": "drug_label_nitroglycerin",
        "source_name": "药品说明书（硝酸甘油）",
        "source_url": "https://www.nmpa.gov.cn/",
        "version": "2026-01-01",
        "title": "硝酸甘油通用药品信息",
        "keywords": ("硝酸甘油",),
        "content": (
            "硝酸甘油用于心绞痛急性发作的缓解；胸痛持续不缓解或伴呼吸困难时属于紧急情况，"
            "应立即拨打 120 或前往急诊，具体用法须遵医嘱。"
        ),
        "review_status": "approved",
    },
)


def trusted_medical_context_for(
    question: str,
    route: RetrievalRoute | None,
) -> list[dict[str, Any]]:
    """返回与问题相关的策展可信医学来源条目。"""
    if route is not None and route.task not in {
        TaskType.GENERAL_MEDICAL_EDUCATION,
        TaskType.MEDICATION_EDUCATION,
        TaskType.MEDICATION_RECONCILIATION,
        TaskType.MEDICATION_DOSING,
        TaskType.SYMPTOM_TRIAGE,
        TaskType.CLINICAL_DECISION,
        TaskType.GENERAL_HEALTH_EDUCATION,
        TaskType.MEDICATION_ALLERGY_CHECK,
    }:
        return []
    text = (question or "").lower()
    return [
        {key: value for key, value in entry.items() if key != "keywords"}
        for entry in TRUSTED_MEDICAL_ENTRIES
        if any(keyword in text for keyword in entry["keywords"])
    ]
