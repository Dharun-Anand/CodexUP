#!/usr/bin/env python3
import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


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


def _coverage_path_from_proof_dir(proof_dir: Path) -> Path:
    return proof_dir / "build" / "report" / "json" / "viewer-coverage.json"


def _verification_path_from_proof_dir(proof_dir: Path) -> Path:
    return proof_dir / "build" / "report" / "json" / "viewer-result.json"


def _read_coverage_metrics(proof_dir: Path) -> Tuple[Optional[int], Optional[int]]:
    coverage_path = _coverage_path_from_proof_dir(proof_dir)
    if not coverage_path.exists():
        return None, None

    data = _read_json(coverage_path)
    if not isinstance(data, dict):
        return None, None

    viewer = data.get("viewer-coverage", {})
    coverage = viewer.get("coverage", {})
    if not isinstance(coverage, dict):
        return None, None

    hit = 0
    total = 0
    for file_path, funcs in coverage.items():
        if str(file_path).endswith("_harness.c"):
            continue
        if not isinstance(funcs, dict):
            continue
        for _func, lines in funcs.items():
            if not isinstance(lines, dict):
                continue
            for _line, status in lines.items():
                total += 1
                if str(status).lower() in {"hit", "covered", "both", "1", "true"}:
                    hit += 1
    return hit, total


def _count_harness_size(proof_dir: Path) -> Optional[int]:
    coverage_path = _coverage_path_from_proof_dir(proof_dir)
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
        for _func, lines in funcs.items():
            if not isinstance(lines, dict):
                continue
            total += len(lines)
    return total


def _count_program_files(proof_dir: Path) -> Optional[int]:
    coverage_path = _coverage_path_from_proof_dir(proof_dir)
    data = _read_json(coverage_path)
    if not isinstance(data, dict):
        return None

    viewer = data.get("viewer-coverage", {})
    coverage = viewer.get("coverage", {})
    if not isinstance(coverage, dict):
        return None

    count = 0
    for file_path in coverage.keys():
        if str(file_path).endswith("_harness.c"):
            continue
        count += 1
    return count


def _parse_loop_limits(proof_dir: Path) -> Tuple[Optional[int], Optional[int]]:
    makefile = proof_dir / "Makefile"
    try:
        text = makefile.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None, None

    unwindset_limits = []
    for match in __import__("re").finditer(r"--unwindset\s+[^\s]+:(\d+)", text):
        try:
            unwindset_limits.append(int(match.group(1)))
        except Exception:
            continue

    unwind_limits = []
    for match in __import__("re").finditer(r"--unwind\s+(\d+)", text):
        try:
            unwind_limits.append(int(match.group(1)))
        except Exception:
            continue

    max_limit = None
    if unwindset_limits or unwind_limits:
        max_limit = max(unwindset_limits + unwind_limits)
    return len(unwindset_limits), max_limit


def _count_preconditions(proof_dir: Path) -> Optional[int]:
    pattern = re.compile(r"__CPROVER_precondition|CBMC_PRECONDITION|__CPROVER_assume")
    scope = _gather_scope_files(proof_dir)
    files = [p for p in scope if p.suffix.lower() == ".c"]
    if not files:
        return 0
    total = 0
    for path in files:
        total += len(pattern.findall(_safe_read_text(path)))
    return total


def _count_stubs(proof_dir: Path) -> Optional[int]:
    import subprocess

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


def _read_verification_error_count(proof_dir: Path) -> Optional[int]:
    result_path = _verification_path_from_proof_dir(proof_dir)
    data = _read_json(result_path)
    if not isinstance(data, dict):
        return None
    result = data.get("viewer-result", {})
    if not isinstance(result, dict):
        return None
    results = result.get("results", {})
    if not isinstance(results, dict):
        return None
    false_list = results.get("false", [])
    if not isinstance(false_list, list):
        false_list = []
    return len(false_list)


def _iter_proof_dirs(run_root: Path) -> List[Path]:
    out: List[Path] = []
    if not run_root.is_dir():
        return out
    for entry in run_root.iterdir():
        if not entry.is_dir():
            continue
        if (entry / "Makefile").exists():
            out.append(entry)
    return sorted(out)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute unit proofing quality metrics from a CodexUP run root."
    )
    parser.add_argument(
        "run_root",
        nargs="?",
        help="Path to a CodexUP run root (e.g., /home/.../CodexUP_RIOT_AllPrompt).",
    )
    parser.add_argument(
        "--paths-file",
        help="Text file with one run root path per line",
    )
    parser.add_argument(
        "--results-dir",
        default="/home/dananday/Research/CodexUP/results",
        help="Directory to write up_quality_metrics.csv (default: /home/dananday/Research/CodexUP/results).",
    )
    args = parser.parse_args()

    run_roots: List[Path] = []
    if args.paths_file:
        paths_file = Path(args.paths_file)
        if not paths_file.exists():
            raise SystemExit(f"Paths file not found: {paths_file}")
        with paths_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                run_roots.append(Path(line))
    else:
        if not args.run_root:
            raise SystemExit("run_root is required unless --paths-file is provided.")
        run_roots.append(Path(args.run_root))

    for run_root in run_roots:
        if not run_root.is_dir():
            raise SystemExit(f"Run root not found: {run_root}")

        out_path = Path(args.results_dir) / f"UP_Quality_{run_root.name}.csv"
        out_path.parent.mkdir(parents=True, exist_ok=True)

        columns = [
            "function",
            "compile_success",
            "harness_size",
            "program_files",
            "coverage.non_harness.hit",
            "coverage.non_harness.total",
            "custom_loop_limits",
            "max_loop_limit",
            "num_preconditions",
            "stubs",
            "verification.error_count",
        ]

        with out_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            for proof_dir in _iter_proof_dirs(run_root):
                function = proof_dir.name
                coverage_path = _coverage_path_from_proof_dir(proof_dir)
                compile_success = coverage_path.exists()
                cov_hit, cov_total = _read_coverage_metrics(proof_dir)
                custom_loop_limits, max_loop_limit = _parse_loop_limits(proof_dir)
                num_preconditions = _count_preconditions(proof_dir)
                stubs = _count_stubs(proof_dir)
                harness_size = _count_harness_size(proof_dir)
                program_files = _count_program_files(proof_dir)
                verification_errors = _read_verification_error_count(proof_dir)

                writer.writerow(
                    {
                        "function": function,
                        "compile_success": compile_success,
                        "harness_size": harness_size,
                        "program_files": program_files,
                        "coverage.non_harness.hit": cov_hit,
                        "coverage.non_harness.total": cov_total,
                        "custom_loop_limits": custom_loop_limits,
                        "max_loop_limit": max_loop_limit,
                        "num_preconditions": num_preconditions,
                        "stubs": stubs,
                        "verification.error_count": verification_errors,
                    }
                )

        print(f"[codexup] wrote unit proof quality metrics: {out_path}")


if __name__ == "__main__":
    main()
