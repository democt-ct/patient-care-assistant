"""质量评估用例 HTTP 接口。

本路由将 ``app/config/evaluation_cases.py:EVALUATION_CASES``（评估用例的单一
数据源）通过 HTTP 暴露给质量评估控制台 ``app/static/evaluate.html``，
避免前端硬编码副本。

接口:
  - GET /api/v1/evaluation/cases   返回完整评估用例集
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config.evaluation_cases import EVALUATION_CASES
from app.core.database import get_db
from app.models.audit_log import EvaluationRun
from app.services.evaluation_service import (
    case_version,
    persist_evaluation_run,
    score_case,
    serialize_evaluation_run,
    summarize_evaluation_runs,
)

router = APIRouter(prefix="/api/v1/evaluation", tags=["质量评估（evaluation）"])


class EvaluationScoreRequest(BaseModel):
    case_id: str = Field(min_length=1, max_length=100)
    answer: str = Field(default="", max_length=20_000)
    intent: Optional[str] = Field(default=None, max_length=100)


class EvaluationRunRequest(EvaluationScoreRequest):
    run_id: Optional[str] = Field(default=None, max_length=36)
    duration_seconds: Optional[float] = Field(default=None, ge=0, le=3600)
    model_version: Optional[str] = Field(default=None, max_length=255)
    prompt_version: Optional[str] = Field(default=None, max_length=255)
    knowledge_base_version: Optional[str] = Field(default=None, max_length=255)
    trace_id: Optional[str] = Field(default=None, max_length=64)
    extra_result: Optional[Dict[str, Any]] = None


def _case_by_id(case_id: str) -> Dict[str, Any]:
    for case in EVALUATION_CASES:
        if case["id"] == case_id:
            return case
    raise HTTPException(status_code=404, detail=f"Unknown evaluation case: {case_id}")


@router.get(
    "/cases",
    summary="获取质量评估用例集",
    description=(
        "返回完整的质量评估用例集。该接口是评估用例的【单一数据源】—— "
        "质量评估控制台、命令行运行器均从此处（或其底层 "
        "`app/config/evaluation_cases.py:EVALUATION_CASES`）获取用例，"
        "禁止在前端硬编码副本。"
    ),
)
def list_evaluation_cases() -> Dict[str, Any]:
    """返回评估用例集 + 聚合统计信息。"""
    categories: Dict[str, int] = {}
    for case in EVALUATION_CASES:
        prefix = case["id"].split("-")[0]
        categories[prefix] = categories.get(prefix, 0) + 1

    return {
        "count": len(EVALUATION_CASES),
        "categories": categories,
        "cases": _serialize_cases(EVALUATION_CASES),
    }


@router.post("/score", summary="统一评分（不保存结果）")
def evaluate_score(payload: EvaluationScoreRequest) -> Dict[str, Any]:
    """Apply the canonical scoring contract shared by all evaluation clients."""
    case = _case_by_id(payload.case_id)
    return {
        "case_id": case["id"],
        **score_case(case, answer=payload.answer, intent=payload.intent),
    }


@router.post("/runs", status_code=201, summary="评分并保存一次评估运行")
def create_evaluation_run(
    payload: EvaluationRunRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Persist a versioned result without storing patient identifiers or prompts."""
    case = _case_by_id(payload.case_id)
    record = persist_evaluation_run(
        db,
        case=case,
        answer=payload.answer,
        intent=payload.intent,
        duration_seconds=payload.duration_seconds,
        run_id=payload.run_id,
        model_version=payload.model_version,
        prompt_version=payload.prompt_version,
        knowledge_base_version=payload.knowledge_base_version,
        trace_id=payload.trace_id,
        extra_result=payload.extra_result,
    )
    return serialize_evaluation_run(record)


@router.get("/runs", summary="获取评估运行历史")
def list_evaluation_runs(
    case_id: Optional[str] = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    query = db.query(EvaluationRun)
    if case_id:
        query = query.filter(EvaluationRun.case_id == case_id)
    rows = query.order_by(EvaluationRun.created_at.desc()).limit(limit).all()
    return {"count": len(rows), "runs": [serialize_evaluation_run(row) for row in rows]}


@router.get("/runs/summary", summary="获取评估运行聚合趋势")
def evaluation_run_summary(
    limit: int = Query(default=500, ge=1, le=2_000),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    rows = db.query(EvaluationRun).order_by(EvaluationRun.created_at.desc()).limit(limit).all()
    return {"window_size": len(rows), "summary": summarize_evaluation_runs(rows)}


def _serialize_cases(cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Serialize cases to JSON-safe dicts (patient_code may be None)."""
    return [
        {
            "id": c["id"],
            "patient_code": c.get("patient_code"),
            "question": c["question"],
            "expected_intents": c.get("expected_intents", []),
            "expected_keywords": c.get("expected_keywords", []),
            "forbidden_keywords": c.get("forbidden_keywords", []),
            "safety_policy": c.get("safety_policy", {}),
            "evaluation_hint": c.get("evaluation_hint", ""),
            "task": c.get("task", ""),
            "golden_scenario": c.get("golden_scenario"),
            "split": c.get("split", "dev"),
            "expected_refusal": c.get("expected_refusal", False),
            "expected_conflict": c.get("expected_conflict", False),
            "scoring": c.get(
                "scoring",
                {"intent_weight": 0.3, "keyword_weight": 0.4, "safety_weight": 0.3, "safety_notes": ""},
            ),
            "case_version": case_version(c),
        }
        for c in cases
    ]
