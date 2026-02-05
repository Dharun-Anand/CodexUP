#!/usr/bin/env python3
import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


def summarize_metrics(metrics: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not metrics:
        return {}

    total = len(metrics)
    compile_success = sum(1 for m in metrics if m.get("compile_success"))
    coverage_over_90 = sum(
        1 for m in metrics
        if (m.get("coverage") or {}).get("overall") is not None
        and ((m.get("coverage") or {}).get("overall", {}).get("percentage") is not None)
        and (m.get("coverage") or {}).get("overall", {}).get("percentage") >= 0.9
    )
    zero_errors = sum(1 for m in metrics if m.get("verification", {}).get("error_count") == 0)
    avg_time = sum(m.get("duration_sec", 0) for m in metrics) / total

    token_totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
    }
    for m in metrics:
        tokens = m.get("tokens") or {}
        for k in token_totals:
            v = tokens.get(k)
            if isinstance(v, int):
                token_totals[k] += v

    cost_totals = {
        "input_cost": 0.0,
        "output_cost": 0.0,
        "cached_cost": 0.0,
        "reasoning_cost": 0.0,
        "total_cost": 0.0,
    }
    any_cost = False
    for m in metrics:
        costs = m.get("costs") or {}
        for k in cost_totals:
            v = costs.get(k)
            if isinstance(v, (int, float)):
                cost_totals[k] += float(v)
                any_cost = True

    return {
        "targets_total": total,
        "compile_success_rate": compile_success / total,
        "coverage_over_90_rate": coverage_over_90 / total,
        "zero_final_errors_rate": zero_errors / total,
        "avg_generation_time_sec": avg_time,
        "token_totals": token_totals,
        "cost_totals": cost_totals if any_cost else None,
    }


def load_metrics_jsonl(path: Path) -> List[Dict[str, Any]]:
    metrics: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                metrics.append(json.loads(line))
            except Exception:
                continue
    return metrics


def _get_nested(obj: Dict[str, Any], *keys: str) -> Optional[Any]:
    cur: Any = obj
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def write_metrics_csv(metrics: List[Dict[str, Any]], out_path: Path) -> None:
    columns = [
        "function",
        "proof_dir",
        "log_path",
        "run_id",
        "session_path",
        "success",
        "exit_code",
        "duration_sec",
        "compile_success",
        "preflight_error",
        "coverage_path",
        "coverage_overall_percentage",
        "coverage_overall_total_lines",
        "coverage_overall_hit_lines",
        "coverage_non_harness_percentage",
        "coverage_non_harness_total_lines",
        "coverage_non_harness_hit_lines",
        "coverage_harness_percentage",
        "coverage_harness_total_lines",
        "coverage_harness_hit_lines",
        "verification_result_path",
        "verification_error_count",
        "tokens_input",
        "tokens_cached",
        "tokens_output",
        "tokens_reasoning",
        "tokens_total",
        "cost_input",
        "cost_cached",
        "cost_output",
        "cost_reasoning",
        "cost_total",
    ]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for m in metrics:
            row = {
                "function": m.get("function"),
                "proof_dir": m.get("proof_dir"),
                "log_path": m.get("log_path"),
                "run_id": m.get("run_id"),
                "session_path": m.get("session_path"),
                "success": m.get("success"),
                "exit_code": m.get("exit_code"),
                "duration_sec": m.get("duration_sec"),
                "compile_success": m.get("compile_success"),
                "preflight_error": m.get("preflight_error"),
                "coverage_path": _get_nested(m, "coverage", "coverage_path"),
                "coverage_overall_percentage": _get_nested(m, "coverage", "overall", "percentage"),
                "coverage_overall_total_lines": _get_nested(m, "coverage", "overall", "total"),
                "coverage_overall_hit_lines": _get_nested(m, "coverage", "overall", "hit"),
                "coverage_non_harness_percentage": _get_nested(m, "coverage", "non_harness", "percentage"),
                "coverage_non_harness_total_lines": _get_nested(m, "coverage", "non_harness", "total"),
                "coverage_non_harness_hit_lines": _get_nested(m, "coverage", "non_harness", "hit"),
                "coverage_harness_percentage": _get_nested(m, "coverage", "harness", "percentage"),
                "coverage_harness_total_lines": _get_nested(m, "coverage", "harness", "total"),
                "coverage_harness_hit_lines": _get_nested(m, "coverage", "harness", "hit"),
                "verification_result_path": _get_nested(m, "verification", "result_path"),
                "verification_error_count": _get_nested(m, "verification", "error_count"),
                "tokens_input": _get_nested(m, "tokens", "input_tokens"),
                "tokens_cached": _get_nested(m, "tokens", "cached_tokens"),
                "tokens_output": _get_nested(m, "tokens", "output_tokens"),
                "tokens_reasoning": _get_nested(m, "tokens", "reasoning_tokens"),
                "tokens_total": _get_nested(m, "tokens", "total_tokens"),
                "cost_input": _get_nested(m, "costs", "input_cost"),
                "cost_cached": _get_nested(m, "costs", "cached_cost"),
                "cost_output": _get_nested(m, "costs", "output_cost"),
                "cost_reasoning": _get_nested(m, "costs", "reasoning_cost"),
                "cost_total": _get_nested(m, "costs", "total_cost"),
            }
            writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize CodexUP metrics JSONL.")
    parser.add_argument("metrics_jsonl", help="Path to codex_metrics.jsonl")
    parser.add_argument(
        "--out",
        help="Optional output JSON path (default: <metrics_jsonl_dir>/codex_summary.json)",
    )
    parser.add_argument(
        "--csv",
        help="Optional output CSV path (default: <metrics_jsonl_dir>/codex_metrics.csv)",
    )
    args = parser.parse_args()

    metrics_path = Path(args.metrics_jsonl)
    if not metrics_path.exists():
        raise SystemExit(f"Metrics file not found: {metrics_path}")

    metrics = load_metrics_jsonl(metrics_path)
    summary = summarize_metrics(metrics)

    if args.out:
        out_path = Path(args.out)
    else:
        stem = metrics_path.stem
        if "metrics" in stem:
            summary_stem = stem.replace("metrics", "summary", 1)
        else:
            summary_stem = f"{stem}_summary"
        out_path = metrics_path.with_name(f"{summary_stem}.json")
    out_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"[codexup] wrote summary: {out_path}")

    csv_path = Path(args.csv) if args.csv else metrics_path.with_suffix(".csv")
    write_metrics_csv(metrics, csv_path)
    print(f"[codexup] wrote csv: {csv_path}")


if __name__ == "__main__":
    main()
