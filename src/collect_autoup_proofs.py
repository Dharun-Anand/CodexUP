#!/usr/bin/env python3
import argparse
import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _parse_targets_from_yaml(path: Path) -> List[str]:
    functions: List[str] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return functions

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "function:" in line:
            # handles "function: foo" and "- function: foo"
            fn = line.split("function:", 1)[1].strip()
            if fn:
                functions.append(fn)
    return functions


def _is_valid_proof_dir(path: Path) -> bool:
    if not (path / "Makefile").is_file():
        return False
    if not list(path.glob("*_harness.c")):
        return False
    if not (path / "build").is_dir():
        return False
    return True


def _find_latest_proof_dirs(root: Path, functions: List[str]) -> Dict[str, Path]:
    wanted = set(functions)
    latest: Dict[str, Tuple[float, Path]] = {}

    for dirpath, dirnames, _filenames in os.walk(root):
        for d in list(dirnames):
            if d not in wanted:
                continue
            p = Path(dirpath) / d
            if not _is_valid_proof_dir(p):
                continue
            try:
                mtime = p.stat().st_mtime
            except Exception:
                continue
            current = latest.get(d)
            if current is None or mtime > current[0]:
                latest[d] = (mtime, p)

    return {k: v[1] for k, v in latest.items()}


def _copy_dir(src: Path, dest: Path, overwrite: bool) -> None:
    if dest.exists():
        if not overwrite:
            return
        shutil.rmtree(dest)
    def _ignore(dirpath: str, names: List[str]) -> set:
        ignored = set()
        for name in names:
            if name == ".cache":
                ignored.add(name)
                continue
            try:
                p = Path(dirpath) / name
                if not os.access(p, os.R_OK):
                    ignored.add(name)
            except Exception:
                ignored.add(name)
        return ignored

    shutil.copytree(src, dest, ignore=_ignore)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect latest AutoUP proof directories for functions in a target YAML."
    )
    parser.add_argument("targets_yaml", help="Path to target-*.yaml with function list.")
    parser.add_argument("autoup_root", help="Root directory to search for AutoUP proofs.")
    parser.add_argument(
        "--out-dir",
        default="/home/dananday/Research/AutoUP-Proofs",
        help="Destination directory (default: /home/dananday/Research/AutoUP-Proofs).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite destination folders if they already exist.",
    )
    args = parser.parse_args()

    targets_yaml = Path(args.targets_yaml)
    if not targets_yaml.exists():
        raise SystemExit(f"Targets YAML not found: {targets_yaml}")

    autoup_root = Path(args.autoup_root)
    if not autoup_root.is_dir():
        raise SystemExit(f"AutoUP root not found: {autoup_root}")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    functions = _parse_targets_from_yaml(targets_yaml)
    if not functions:
        raise SystemExit(f"No functions found in {targets_yaml}")

    latest = _find_latest_proof_dirs(autoup_root, functions)
    missing = [fn for fn in functions if fn not in latest]

    for fn, src in latest.items():
        dest = out_dir / fn
        _copy_dir(src, dest, overwrite=args.overwrite)
        print(f"[autoup] copied {fn}: {src} -> {dest}")

    if missing:
        print(f"[autoup] missing {len(missing)} functions:")
        for fn in missing:
            print(f"  - {fn}")


if __name__ == "__main__":
    main()
