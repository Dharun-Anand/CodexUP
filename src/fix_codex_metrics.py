#!/usr/bin/env python3
import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Tuple


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

try:
    from codexup import read_coverage_metrics
except Exception as exc:  # pragma: no cover - import guard for CLI use
    raise SystemExit(f"Failed to import codexup.py: {exc}")


Record = Dict[str, Any]
Fixer = Callable[[Record, Dict[str, Any]], bool]


def _flatten_coverage(coverage: Dict[str, Any]) -> Dict[str, Any]:
    overall = coverage.get("overall") or {}
    non_harness = coverage.get("non_harness") or {}
    harness = coverage.get("harness") or {}
    return {
        "coverage.coverage_path": coverage.get("coverage_path"),
        "coverage.overall.hit": overall.get("hit"),
        "coverage.overall.total": overall.get("total"),
        "coverage.overall.percentage": overall.get("percentage"),
        "coverage.non_harness.hit": non_harness.get("hit"),
        "coverage.non_harness.total": non_harness.get("total"),
        "coverage.non_harness.percentage": non_harness.get("percentage"),
        "coverage.harness.hit": harness.get("hit"),
        "coverage.harness.total": harness.get("total"),
        "coverage.harness.percentage": harness.get("percentage"),
    }


def fix_coverage(record: Record, _ctx: Dict[str, Any]) -> bool:
    proof_dir = record.get("proof_dir")
    if not isinstance(proof_dir, str) or not proof_dir:
        return False
    coverage = read_coverage_metrics(proof_dir)

    changed = False
    if isinstance(record.get("coverage"), dict) or "coverage" in record:
        record["coverage"] = coverage
        changed = True

    flattened = _flatten_coverage(coverage)
    if any(k.startswith("coverage.") for k in record.keys()):
        for key, value in flattened.items():
            if record.get(key) != value:
                record[key] = value
                changed = True

    if not changed:
        record["coverage"] = coverage
        changed = True

    return changed


def fix_paths(record: Record, ctx: Dict[str, Any]) -> bool:
    proof_dir = record.get("proof_dir")
    if not isinstance(proof_dir, str) or not proof_dir:
        return False

    new_root = ctx.get("run_root")
    if not isinstance(new_root, Path):
        return False

    old_proof = Path(proof_dir)
    old_root = old_proof.parent
    new_proof = new_root / old_proof.name

    changed = False
    if str(old_proof) != str(new_proof):
        record["proof_dir"] = str(new_proof)
        changed = True

    def _rewrite_path(value: Any) -> Any:
        if not isinstance(value, str) or not value:
            return value
        try:
            p = Path(value)
        except Exception:
            return value
        try:
            p.relative_to(old_root)
        except Exception:
            return value
        return str(new_root / p.relative_to(old_root))

    for key in ("log_path", "coverage_path", "verification_result_path", "session_path"):
        if key in record:
            new_val = _rewrite_path(record.get(key))
            if new_val != record.get(key):
                record[key] = new_val
                changed = True

    coverage = record.get("coverage")
    if isinstance(coverage, dict):
        cov_path = coverage.get("coverage_path")
        new_cov = _rewrite_path(cov_path)
        if new_cov != cov_path:
            coverage["coverage_path"] = new_cov
            changed = True

    verification = record.get("verification")
    if isinstance(verification, dict):
        res_path = verification.get("result_path")
        new_res = _rewrite_path(res_path)
        if new_res != res_path:
            verification["result_path"] = new_res
            changed = True

    flat_cov_path = record.get("coverage.coverage_path")
    new_flat_cov = _rewrite_path(flat_cov_path)
    if new_flat_cov != flat_cov_path:
        record["coverage.coverage_path"] = new_flat_cov
        changed = True

    flat_ver_path = record.get("verification.result_path")
    new_flat_ver = _rewrite_path(flat_ver_path)
    if new_flat_ver != flat_ver_path:
        record["verification.result_path"] = new_flat_ver
        changed = True

    return changed


AVAILABLE_FIXERS: Dict[str, Fixer] = {
    "coverage": fix_coverage,
    "paths": fix_paths,
}


def select_fixers(names: Iterable[str]) -> List[Fixer]:
    requested = list(names)
    # Ensure path rewrites run before coverage recompute.
    if "paths" in requested and "coverage" in requested:
        ordered = ["paths", "coverage"] + [n for n in requested if n not in {"paths", "coverage"}]
    else:
        ordered = requested

    fixers: List[Fixer] = []
    for name in ordered:
        fixer = AVAILABLE_FIXERS.get(name)
        if fixer is None:
            raise SystemExit(f"Unknown fixer: {name}. Available: {', '.join(AVAILABLE_FIXERS)}")
        fixers.append(fixer)
    return fixers


def _open_output(in_path: Path, in_place: bool, suffix: str) -> Tuple[Path, Any]:
    if in_place:
        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            delete=False,
            dir=str(in_path.parent),
            prefix=in_path.name + ".",
            suffix=".tmp",
        )
        return Path(tmp.name), tmp
    out_path = in_path.with_name(in_path.name + suffix)
    return out_path, out_path.open("w", encoding="utf-8")


def process_file(
    in_path: Path,
    fixers: List[Fixer],
    in_place: bool,
    suffix: str,
    dry_run: bool,
) -> Tuple[int, int]:
    total = 0
    changed = 0

    out_path = None
    out_fh = None
    if not dry_run:
        out_path, out_fh = _open_output(in_path, in_place, suffix)

    ctx = {"metrics_path": in_path, "run_root": in_path.parent.parent}

    try:
        with in_path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    if out_fh:
                        out_fh.write(line)
                    continue

                try:
                    record = json.loads(line)
                except Exception:
                    if out_fh:
                        out_fh.write(line)
                    continue

                if not isinstance(record, dict):
                    if out_fh:
                        out_fh.write(line)
                    continue

                total += 1
                did_change = False
                for fixer in fixers:
                    if fixer(record, ctx):
                        did_change = True

                if did_change:
                    changed += 1

                if out_fh:
                    if did_change:
                        out_fh.write(json.dumps(record, ensure_ascii=True) + "\n")
                    else:
                        out_fh.write(line)
    finally:
        if out_fh:
            out_fh.close()

    if not dry_run and in_place and out_path:
        backup_path = in_path.with_name(in_path.name + ".old")
        if backup_path.exists():
            backup_path.unlink()
        in_path.replace(backup_path)
        out_path.replace(in_path)

    return total, changed


def main() -> None:
    parser = argparse.ArgumentParser(description="Fix codex_metrics.jsonl files.")
    parser.add_argument("paths", nargs="*", help="Paths to codex_metrics.jsonl files")
    parser.add_argument(
        "--paths-file",
        help="Text file with one codex_metrics.jsonl path per line",
    )
    parser.add_argument(
        "--revert",
        action="store_true",
        help="Revert files by restoring <name>.old backups",
    )
    parser.add_argument(
        "--only",
        nargs="+",
        default=["coverage"],
        help=f"Fixers to apply (default: coverage). Available: {', '.join(AVAILABLE_FIXERS)}",
    )
    parser.add_argument(
        "--suffix",
        default=".fixed",
        help="Suffix for output files (unused unless --no-in-place is added later)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report changes without writing output files",
    )
    args = parser.parse_args()

    fixers = select_fixers(args.only)
    in_place = True

    paths: List[str] = list(args.paths or [])
    if args.paths_file:
        paths_file = Path(args.paths_file)
        if not paths_file.exists():
            raise SystemExit(f"Paths file not found: {paths_file}")
        with paths_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                paths.append(line)

    if not paths:
        raise SystemExit("No input paths provided. Use paths or --paths-file.")

    for p in paths:
        path = Path(p)
        if not path.exists():
            print(f"[codexup] missing: {path}")
            continue
        if args.revert:
            backup_path = path.with_name(path.name + ".old")
            if not backup_path.exists():
                print(f"[codexup] missing backup: {backup_path}")
                continue
            if args.dry_run:
                print(f"[codexup] {path}: would restore from {backup_path}")
                continue
            path.replace(path.with_name(path.name + ".broken"))
            backup_path.replace(path)
            print(f"[codexup] {path}: restored from {backup_path}")
            continue
        total, changed = process_file(
            path,
            fixers,
            in_place,
            args.suffix,
            args.dry_run,
        )
        if args.dry_run:
            print(f"[codexup] {path}: would change {changed}/{total} records")
        else:
            out_note = "in-place"
            out_note += f" (backup {path.with_name(path.name + '.old')})"
            print(f"[codexup] {path}: changed {changed}/{total} records {out_note}")


if __name__ == "__main__":
    main()
