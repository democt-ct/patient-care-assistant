"""
质量评估用例运行器 —— 命令行可视化输出每条用例的验证结果。

用法:
  python scripts/run_evaluation.py              # 运行全部用例
  python scripts/run_evaluation.py --case fact   # 按前缀筛选
  python scripts/run_evaluation.py --verbose     # 显示详细对比
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.mcp.llm_router import run_agent_tool_query
from app.services.evaluation_service import compute_metrics, score_case
from app.config.evaluation_cases import EVALUATION_CASES

# ANSI colors
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def evaluate_case(case: dict, verbose: bool = False) -> dict:
    """Run a single evaluation case and check results."""
    question = case["question"]
    expected_intents = case.get("expected_intents", [])

    # Resolve patient
    patient_id = None
    hospital_id = "hospital-a"
    if case.get("patient_code"):
        db = SessionLocal()
        try:
            from app.models.patient import Patient
            patient = db.query(Patient).filter(
                Patient.patient_code == case["patient_code"]
            ).first()
            if patient:
                patient_id = patient.id
                hospital_id = patient.hospital_id
        finally:
            db.close()

    # Run agent query
    start_time = time.time()
    try:
        result = run_agent_tool_query(
            question=question,
            patient_id=patient_id,
            hospital_id=hospital_id,
            chat_mode="memory",
        )
        duration = time.time() - start_time
        answer = result.get("answer", "")
        intent = result.get("intent", "")
        intent_confidence = result.get("intent_confidence", 0)
        contract = {
            "risk_level": result.get("risk_level"),
            "next_action": result.get("next_action"),
            "evidence_summary": result.get("evidence_summary"),
            "task_route": result.get("task_route"),
            "evidence_check": result.get("evidence_check"),
            "citation_report": result.get("citation_report"),
            "clarification_required": result.get("clarification_required"),
            "decision": result.get("decision"),
            "patient_evidence_summary": result.get("patient_evidence_summary"),
            "answer": answer,
        }
    except Exception as exc:
        return {
            "id": case["id"],
            "pass": False,
            "error": str(exc),
            "duration": time.time() - start_time,
            "contract": None,
        }

    # The CLI must use the same versioned scoring contract as the API and
    # persisted evaluation runs.  Do not maintain a weaker local pass rule.
    score = score_case(case, answer=answer, intent=intent)

    return {
        "id": case["id"],
        "pass": score["passed"],
        "answer": answer[:200] + "..." if len(answer) > 200 else answer,
        "intent": intent,
        "intent_confidence": intent_confidence,
        "intent_expected": expected_intents,
        "intent_ok": score["intent_ok"],
        "missing_keywords": score["missing_keywords"],
        "found_forbidden": score["found_forbidden"],
        "missing_safety_requirements": score["missing_safety_requirements"],
        "score": score,
        "duration": round(duration, 2),
        "error": None,
        "contract": contract,
    }


def print_result(result: dict, verbose: bool = False):
    """Print a single evaluation result."""
    case_id = result["id"]
    # Keep the CLI compatible with the default Windows GBK console.
    status_icon = f"{GREEN}[OK]{RESET}" if result["pass"] else f"{RED}[FAIL]{RESET}"
    status_text = f"{GREEN}PASS{RESET}" if result["pass"] else f"{RED}FAIL{RESET}"

    print(f"\n  {status_icon} {BOLD}[{case_id}]{RESET} {status_text} ({result['duration']}s)")

    if result.get("error"):
        print(f"     {RED}ERROR: {result['error']}{RESET}")
        return

    if verbose or not result["pass"]:
        print(f"     意图: {CYAN}{result.get('intent', '')}{RESET} (期望: {', '.join(result.get('intent_expected', []))}"
              f" {'OK' if result['intent_ok'] else f'{RED}FAIL{RESET}'})")
        if result["missing_keywords"]:
            print(f"     {RED}缺少关键词: {', '.join(result['missing_keywords'])}{RESET}")
        if result["found_forbidden"]:
            print(f"     {RED}出现禁用词: {', '.join(result['found_forbidden'])}{RESET}")
        if result.get("missing_safety_requirements"):
            print(f"     {RED}缺少安全要求: {', '.join(result['missing_safety_requirements'])}{RESET}")
        if result.get("score"):
            print(f"     得分: {result['score']['scores']['total']:.1f} / 100")
        print(f"     回答: {YELLOW}{result['answer'][:150]}{RESET}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="运行质量评估用例")
    parser.add_argument("--case", help="按 ID 前缀筛选（如 fact、visit、symptom）")
    parser.add_argument("--split", choices=["dev", "test"], help="按开发集/独立测试集筛选")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示详细输出")
    parser.add_argument("--json", help="输出 JSON 报告到文件")
    args = parser.parse_args()

    # Filter cases
    cases = EVALUATION_CASES
    if args.case:
        cases = [c for c in cases if c["id"].startswith(args.case)]
        if not cases:
            print(f"{RED}没有找到以 '{args.case}' 开头的用例{RESET}")
            sys.exit(1)
    if args.split:
        cases = [c for c in cases if c.get("split") == args.split]
        if not cases:
            print(f"{RED}没有找到 split='{args.split}' 的用例{RESET}")
            sys.exit(1)

    print(f"\n{BOLD}{'='*60}{RESET}")
    split_label = f"（{args.split} 集）" if args.split else ""
    print(f" {BOLD}质量评估运行器 — {len(cases)} 条用例{split_label}{RESET}")
    print(f"{BOLD}{'='*60}{RESET}")

    results = []
    for i, case in enumerate(cases, 1):
        print(f"\n[{i}/{len(cases)}] {case['id']}: {case['question'][:60]}")
        result = evaluate_case(case, verbose=args.verbose)
        results.append(result)
        print_result(result, verbose=args.verbose)

    # Summary
    passed = sum(1 for r in results if r["pass"])
    failed = sum(1 for r in results if not r["pass"])
    total_duration = sum(r["duration"] for r in results)

    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f" {BOLD}结果汇总{RESET}")
    print(f"  总计: {len(results)} 条")
    print(f"  {GREEN}通过: {passed} 条{RESET}")
    if failed:
        print(f"  {RED}失败: {failed} 条{RESET}")
    else:
        print("  失败: 0 条")
    print(f"  耗时: {total_duration:.1f}s")
    print(f"{BOLD}{'='*60}{RESET}\n")

    # ── 秋招 MVP 指标（独立测试集统计）──
    metrics = compute_metrics([
        {"case": case, "result": result.get("contract"), "duration": result.get("duration")}
        for case, result in zip(cases, results)
    ])
    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f" {BOLD}秋招 MVP 指标{RESET}")
    metric_rows = [
        ("路由准确率", metrics["route_accuracy"]),
        ("高风险召回率", metrics["high_risk_recall"]),
        ("危险建议拦截率", metrics["danger_interception_rate"]),
        ("引用正确率", metrics["citation_correctness"]),
        ("冲突发现率", metrics["conflict_detection_rate"]),
        ("证据不足正确拒答率", metrics["refusal_correct_rate"]),
        ("不必要拒答率", metrics["unnecessary_refusal_rate"]),
    ]
    for label, metric in metric_rows:
        if metric["value"] is None:
            print(f"  {label}: {YELLOW}样本不足（{metric['samples']}）{RESET}")
        else:
            print(f"  {label}: {metric['value']:.2f}% （样本 {metric['samples']}）")
    p95 = metrics["p95_latency_seconds"]
    print(f"  P95 延迟: {YELLOW}{p95 if p95 is not None else '样本不足'}{RESET}")
    print(f"{BOLD}{'='*60}{RESET}\n")

    # Export JSON
    if args.json:
        export = {"results": results, "metrics": metrics}
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(export, f, ensure_ascii=False, indent=2)
        print(f"JSON 报告已保存: {args.json}")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
