#!/usr/bin/env python3
import argparse
import json
import csv
import os
import subprocess
import re
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


PRECONDITION_PAT = re.compile(r"__CPROVER_precondition|CBMC_PRECONDITION|__CPROVER_assume")


def _get_nested(obj: Dict[str, Any], *keys: str) -> Optional[Any]:
    cur: Any = obj
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _count_preconditions(files: List[Path]) -> int:
    c = 0
    for f in files:
        c += len(PRECONDITION_PAT.findall(_safe_read_text(f)))
    return c


def _gather_scope_files(proof_dir: Path) -> List[Path]:
    leaf = list(proof_dir.rglob("*.c")) + list(proof_dir.rglob("*.h"))

    parent = proof_dir.parent
    parent_add: List[Path] = []
    if parent.is_dir():
        for p in parent.iterdir():
            if not p.is_file():
                continue
            if p.suffix.lower() not in (".c", ".h"):
                continue
            n = p.name.lower()
            if n == "general-stubs.c" or "stub" in n or "model" in n:
                parent_add.append(p)

    seen = set()
    out: List[Path] = []
    for p in leaf + parent_add:
        rp = str(p.resolve())
        if rp not in seen:
            seen.add(rp)
            out.append(p)
    return out




def _coverage_path_from_proof_dir(proof_dir: str) -> Path:
    return Path(proof_dir) / "build" / "report" / "json" / "viewer-coverage.json"


def _count_harness_size(coverage_path: Path) -> Optional[int]:
    data = _read_json(coverage_path)
    if not isinstance(data, dict):
        return None

    viewer = data.get("viewer-coverage", {})
    coverage = viewer.get("coverage", {})
    if not isinstance(coverage, dict):
        return None

    total = 0
    for file_path, funcs in coverage.items():
        if not str(file_path).endswith("_harness.c"):
            continue
        if not isinstance(funcs, dict):
            continue
        harness_lines = funcs.get("harness")
        if not isinstance(harness_lines, dict):
            continue
        total += len(harness_lines)
    return total


def _count_harness_stub_functions_ctags(proof_dir: Path) -> Optional[int]:
    harness_files = list(proof_dir.rglob("*_harness.c"))
    if not harness_files:
        return 0

    total = 0
    for path in harness_files:
        try:
            result = subprocess.run(
                ["ctags", "-x", "--c-kinds=f", str(path)],
                capture_output=True,
                text=True,
                check=False,
            )
        except Exception:
            return None

        if result.returncode != 0:
            return None

        count = 0
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            name = line.split()[0]
            if name == "harness":
                continue
            if name.startswith("__CPROVER_nondet_"):
                continue
            if name.startswith("_assert_") or name.startswith("__assert_"):
                continue
            count += 1
        total += count
    return total


def _parse_loop_limits(proof_dir: Path) -> Dict[str, Optional[int]]:
    makefile = proof_dir / "Makefile"
    try:
        text = makefile.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return {"custom_loop_limits": None, "max_loop_limit": None}

    unwindset_limits = []
    for match in re.finditer(r"--unwindset\s+[^\s]+:(\d+)", text):
        try:
            unwindset_limits.append(int(match.group(1)))
        except Exception:
            continue

    unwind_limits = []
    for match in re.finditer(r"--unwind\s+(\d+)", text):
        try:
            unwind_limits.append(int(match.group(1)))
        except Exception:
            continue

    max_limit = None
    if unwindset_limits or unwind_limits:
        max_limit = max(unwindset_limits + unwind_limits)

    return {
        "custom_loop_limits": len(unwindset_limits),
        "max_loop_limit": max_limit,
    }


def iter_metrics(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue


def build_paper_row(metrics: Dict[str, Any], run_root: Optional[Path] = None) -> Dict[str, Any]:
    proof_dir = metrics.get("proof_dir")
    function = metrics.get("function")
    effective_proof_dir = None
    if isinstance(proof_dir, str) and proof_dir:
        if Path(proof_dir).is_dir():
            effective_proof_dir = proof_dir
    if effective_proof_dir is None and run_root and function:
        candidate = run_root / str(function)
        if candidate.is_dir():
            effective_proof_dir = str(candidate)

    coverage_path = _get_nested(metrics, "coverage", "coverage_path")
    if coverage_path:
        if not Path(str(coverage_path)).is_file() and effective_proof_dir:
            coverage_path = str(_coverage_path_from_proof_dir(effective_proof_dir))
    elif effective_proof_dir:
        coverage_path = str(_coverage_path_from_proof_dir(effective_proof_dir))

    harness_size = None
    if coverage_path:
        harness_size = _count_harness_size(Path(coverage_path))

    num_preconditions = None
    stubs = None
    custom_loop_limits = None
    max_loop_limit = None
    if effective_proof_dir:
        scope = _gather_scope_files(Path(effective_proof_dir))
        scope_c = [p for p in scope if p.suffix.lower() == ".c"]
        if scope_c:
            num_preconditions = _count_preconditions(scope_c)
        else:
            num_preconditions = 0

    if stubs is None and effective_proof_dir:
        stubs = _count_harness_stub_functions_ctags(Path(effective_proof_dir))

    if effective_proof_dir:
        loop_limits = _parse_loop_limits(Path(effective_proof_dir))
        custom_loop_limits = loop_limits.get("custom_loop_limits")
        max_loop_limit = loop_limits.get("max_loop_limit")

    row = OrderedDict()
    row["function"] = function
    row["proof_dir"] = effective_proof_dir or proof_dir
    row["log_path"] = metrics.get("log_path")
    row["run_id"] = metrics.get("run_id")
    row["session_path"] = metrics.get("session_path")
    row["success"] = metrics.get("success")
    row["exit_code"] = metrics.get("exit_code")
    row["duration_sec"] = metrics.get("duration_sec")
    row["compile_success"] = metrics.get("compile_success")
    row["num_preconditions"] = num_preconditions
    row["stubs"] = stubs
    row["custom_loop_limits"] = custom_loop_limits
    row["max_loop_limit"] = max_loop_limit
    row["tokens.input_tokens"] = _get_nested(metrics, "tokens", "input_tokens")
    row["tokens.cached_tokens"] = _get_nested(metrics, "tokens", "cached_tokens")
    row["tokens.output_tokens"] = _get_nested(metrics, "tokens", "output_tokens")
    row["tokens.reasoning_tokens"] = _get_nested(metrics, "tokens", "reasoning_tokens")
    row["tokens.total_tokens"] = _get_nested(metrics, "tokens", "total_tokens")
    row["costs.input_cost"] = _get_nested(metrics, "costs", "input_cost")
    row["costs.output_cost"] = _get_nested(metrics, "costs", "output_cost")
    row["costs.cached_cost"] = _get_nested(metrics, "costs", "cached_cost")
    row["costs.reasoning_cost"] = _get_nested(metrics, "costs", "reasoning_cost")
    row["costs.total_cost"] = _get_nested(metrics, "costs", "total_cost")
    row["coverage.coverage_path"] = coverage_path
    row["coverage.overall.hit"] = _get_nested(metrics, "coverage", "overall", "hit")
    row["coverage.overall.total"] = _get_nested(metrics, "coverage", "overall", "total")
    row["coverage.overall.percentage"] = _get_nested(metrics, "coverage", "overall", "percentage")
    row["coverage.non_harness.hit"] = _get_nested(metrics, "coverage", "non_harness", "hit")
    row["coverage.non_harness.total"] = _get_nested(metrics, "coverage", "non_harness", "total")
    row["coverage.non_harness.percentage"] = _get_nested(metrics, "coverage", "non_harness", "percentage")
    row["harness_size"] = harness_size
    row["verification.result_path"] = _get_nested(metrics, "verification", "result_path")
    row["verification.error_count"] = _get_nested(metrics, "verification", "error_count")
    return row


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate paper_metrics.jsonl from codex_metrics.jsonl with harness coverage."
    )
    parser.add_argument(
        "run_root",
        nargs="?",
        help="Path to a CodexUP run root (e.g., /home/.../CodexUP_RIOT_AllPrompt).",
    )
    parser.add_argument(
        "--paths-file",
        help="Text file with one codex_metrics.jsonl path per line",
    )
    parser.add_argument(
        "--metrics",
        help="Optional path to codex_metrics.jsonl (default: <run_root>/logs/codex_metrics.jsonl).",
    )
    parser.add_argument(
        "--out",
        help="Optional output path (default: <run_root>/logs/paper_metrics.jsonl).",
    )
    parser.add_argument(
        "--csv",
        action="store_true",
        help="Also write a CSV with selected columns next to the JSONL output.",
    )
    parser.add_argument(
        "--csv-dir",
        help="Directory to write CSVs as <run_root_name>.csv (default: next to JSONL).",
    )
    args = parser.parse_args()

    metrics_paths: List[Path] = []
    if args.paths_file:
        paths_file = Path(args.paths_file)
        if not paths_file.exists():
            raise SystemExit(f"Paths file not found: {paths_file}")
        with paths_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                metrics_paths.append(Path(line))
    else:
        if not args.run_root:
            raise SystemExit("run_root is required unless --paths-file is provided.")
        run_root = Path(args.run_root)
        if args.metrics:
            metrics_paths.append(Path(args.metrics))
        else:
            metrics_paths.append(run_root / "logs" / "codex_metrics.jsonl")

    for metrics_path in metrics_paths:
        if not metrics_path.exists():
            raise SystemExit(f"Metrics file not found: {metrics_path}")
        run_root = metrics_path.parent.parent
        out_path = Path(args.out) if args.out else run_root / "logs" / "paper_metrics.jsonl"
        out_path.parent.mkdir(parents=True, exist_ok=True)

        if args.csv_dir:
            csv_dir = Path(args.csv_dir)
            csv_dir.mkdir(parents=True, exist_ok=True)
            csv_path = csv_dir / f"{run_root.name}.csv"
        else:
            csv_path = out_path.with_suffix(".csv")
        csv_columns = [
            "function",
            "compile_success",
            "duration_sec",
            "num_preconditions",
            "stubs",
            "custom_loop_limits",
            "max_loop_limit",
            "tokens.total_tokens",
            "costs.total_cost",
            "coverage.overall.hit",
            "coverage.overall.total",
            "coverage.non_harness.hit",
            "coverage.non_harness.total",
            "harness_size",
            "verification.error_count",
        ]

        with out_path.open("w", encoding="utf-8") as f:
            csv_file = None
            csv_writer = None
            if args.csv:
                csv_file = csv_path.open("w", encoding="utf-8", newline="")
                csv_writer = csv.DictWriter(csv_file, fieldnames=csv_columns)
                csv_writer.writeheader()
            for m in iter_metrics(metrics_path):
                row = build_paper_row(m, run_root=run_root)
                f.write(json.dumps(row) + "\n")
                if csv_writer:
                    csv_writer.writerow({k: row.get(k) for k in csv_columns})
            if csv_file:
                csv_file.close()

        print(f"[codexup] wrote paper metrics: {out_path}")
        if args.csv:
            print(f"[codexup] wrote paper metrics csv: {csv_path}")


if __name__ == "__main__":
    main()
