#!/usr/bin/env python3
import argparse
import os
import re
import shutil
import subprocess
import sys
import json
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import yaml  # type: ignore
except Exception:
    yaml = None


def _fail(msg: str) -> None:
    """Print an error message and exit."""
    print(f"[codexup] {msg}", file=sys.stderr)
    sys.exit(1)


def check_codex_prereqs() -> None:
    """Ensure codex CLI and API key are available."""
    if shutil.which("codex") is None:
        _fail("codex CLI not found in PATH. Install it and try again.")
    if not os.getenv("OPENAI_API_KEY"):
        _fail("OPENAI_API_KEY is not set. Export it before running CodexUP.")


def load_config(path: str) -> Dict[str, Any]:
    """Load and validate the YAML config file."""
    if yaml is None:
        _fail("PyYAML is not installed. Please `pip install pyyaml`.")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        _fail("Config must be a YAML mapping.")
    return data


def remove_section(text: str, header: str) -> str:
    """Remove a bracketed section by name, up to the next section header."""
    pattern = re.compile(
        rf"\[{re.escape(header)}\][\s\S]*?(\n\[[^\]]+\])",
        re.MULTILINE,
    )
    match = pattern.search(text)
    if not match:
        # If this is the last section, drop to end of file.
        tail_pattern = re.compile(
            rf"\[{re.escape(header)}\][\s\S]*$",
            re.MULTILINE,
        )
        tail_match = tail_pattern.search(text)
        if not tail_match:
            return text
        return text[: tail_match.start()]
    replaced = text[: match.start()] + match.group(1) + text[match.end():]
    return replaced


def render_prompt(template: str, ctx: Dict[str, str], use_examples: bool) -> str:
    """Render the prompt template with placeholder substitutions."""
    out = template
    if not use_examples:
        out = remove_section(out, "Examples")

    return out.format_map(ctx)


def run_codex(
    prompt: str,
    log_path: str,
    dry_run: bool,
    cwd: str,
    model: Optional[str],
    extra_args: Optional[list[str]],
) -> int:
    """Run codex with the rendered prompt and write stdout/stderr to a log file."""
    cmd = ["codex", "exec", "--full-auto"]
    if model:
        cmd += ["--model", model]
    if extra_args:
        cmd += extra_args
    cmd.append(prompt)
    if dry_run:
        print("[codexup] dry-run:", " ".join(cmd))
        print(f"[codexup] log: {log_path}")
        print(f"[codexup] cwd: {cwd}")
        return 0

    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    with open(log_path, "w", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="")
            log_file.write(line)
        return process.wait()

_metrics_lock = threading.Lock()
_RUN_MARKER_PREFIX = "[Run-ID] CODEXUP_RUN_ID="


def inject_run_marker(prompt: str, run_id: str) -> str:
    """Inject a unique marker into the prompt for session attribution."""
    marker = f"<ignore this ID>{_RUN_MARKER_PREFIX}{run_id}</ignore this ID>"
    return f"{marker}\n\n{prompt}"


def _get_codex_sessions_root() -> Path:
    codex_home = os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))
    return Path(codex_home) / "sessions"


def find_session_file_by_marker(run_id: str) -> Optional[Path]:
    """Find a Codex session JSONL file containing the run marker."""
    sessions_root = _get_codex_sessions_root()
    if not sessions_root.exists():
        return None

    marker = f"{_RUN_MARKER_PREFIX}{run_id}"
    candidates = sessions_root.glob("**/rollout-*.jsonl")
    for path in candidates:
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    if marker in line:
                        return path
        except Exception:
            continue
    return None


def parse_token_usage_from_session(session_path: Path) -> Dict[str, Optional[int]]:
    """Parse token usage from a Codex session JSONL file."""
    if not session_path or not session_path.exists():
        return {
            "input_tokens": None,
            "cached_tokens": None,
            "output_tokens": None,
            "reasoning_tokens": None,
            "total_tokens": None,
        }

    last_total = None
    try:
        with session_path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if obj.get("type") != "event_msg":
                    continue
                payload = obj.get("payload") or {}
                if payload.get("type") != "token_count":
                    continue
                info = payload.get("info") or {}
                total = info.get("total_token_usage")
                if isinstance(total, dict):
                    last_total = total
    except Exception:
        last_total = None

    if not isinstance(last_total, dict):
        return {
            "input_tokens": None,
            "cached_tokens": None,
            "output_tokens": None,
            "reasoning_tokens": None,
            "total_tokens": None,
        }

    return {
        "input_tokens": last_total.get("input_tokens"),
        "cached_tokens": last_total.get("cached_input_tokens"),
        "output_tokens": last_total.get("output_tokens"),
        "reasoning_tokens": last_total.get("reasoning_output_tokens"),
        "total_tokens": last_total.get("total_tokens"),
    }


def read_coverage_metrics(proof_dir: str) -> Dict[str, Any]:
    coverage_path = os.path.join(proof_dir, "build", "report", "json", "viewer-coverage.json")
    if not os.path.exists(coverage_path):
        return {"coverage_path": coverage_path, "overall": None, "non_harness": None}

    try:
        with open(coverage_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"coverage_path": coverage_path, "overall": None, "non_harness": None}

    viewer = data.get("viewer-coverage", {})
    overall = viewer.get("overall_coverage", {})

    coverage = viewer.get("coverage", {})
    non_harness_hit = 0
    non_harness_total = 0
    if isinstance(coverage, dict):
        for file_path, funcs in coverage.items():
            if str(file_path).endswith("_harness.c"):
                continue
            if not isinstance(funcs, dict):
                continue
            for _func, lines in funcs.items():
                if not isinstance(lines, dict):
                    continue
                for _line, status in lines.items():
                    non_harness_total += 1
                    if str(status).lower() in {"hit", "covered", "1", "true"}:
                        non_harness_hit += 1

    non_harness_pct = (non_harness_hit / non_harness_total) if non_harness_total else None

    return {
        "coverage_path": coverage_path,
        "overall": {
            "hit": overall.get("hit"),
            "total": overall.get("total"),
            "percentage": overall.get("percentage"),
        },
        "non_harness": {
            "hit": non_harness_hit,
            "total": non_harness_total,
            "percentage": non_harness_pct,
        },
    }


def read_verification_results(proof_dir: str) -> Dict[str, Any]:
    result_path = os.path.join(proof_dir, "build", "report", "json", "viewer-result.json")
    if not os.path.exists(result_path):
        return {"result_path": result_path, "error_count": None}
    try:
        with open(result_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"result_path": result_path, "error_count": None}
    results = data.get("viewer-result", {}).get("results", {})
    false_list = results.get("false", [])
    if not isinstance(false_list, list):
        false_list = []
    return {"result_path": result_path, "error_count": len(false_list)}


def estimate_cost(tokens: Dict[str, Optional[int]], pricing: Optional[Dict[str, float]]) -> Dict[str, Optional[float]]:
    if not pricing:
        return {
            "input_cost": None,
            "output_cost": None,
            "cached_cost": None,
            "reasoning_cost": None,
            "total_cost": None,
        }

    def _cost(count: Optional[int], key: str) -> Optional[float]:
        if count is None:
            return None
        rate = pricing.get(key)
        if rate is None:
            return None
        return (count / 1_000_000.0) * rate

    input_cost = _cost(tokens.get("input_tokens"), "input_per_1m")
    output_cost = _cost(tokens.get("output_tokens"), "output_per_1m")
    cached_cost = _cost(tokens.get("cached_tokens"), "cached_per_1m")
    reasoning_cost = _cost(tokens.get("reasoning_tokens"), "reasoning_per_1m")

    total_cost = 0.0
    any_cost = False
    for v in (input_cost, output_cost, cached_cost, reasoning_cost):
        if v is not None:
            total_cost += v
            any_cost = True

    return {
        "input_cost": input_cost,
        "output_cost": output_cost,
        "cached_cost": cached_cost,
        "reasoning_cost": reasoning_cost,
        "total_cost": total_cost if any_cost else None,
    }


def write_metrics(metrics_path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(metrics_path), exist_ok=True)
    with _metrics_lock:
        with open(metrics_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(data) + "\n")


def summarize_metrics(metrics: list[Dict[str, Any]]) -> Dict[str, Any]:
    if not metrics:
        return {}

    total = len(metrics)
    compile_success = sum(1 for m in metrics if m.get("compile_success"))
    coverage_over_90 = sum(
        1 for m in metrics
        if (m.get("coverage", {}).get("overall", {}).get("percentage") or 0) >= 0.9
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


def _run_target(
    template: str,
    target: Dict[str, Any],
    project_root: str,
    proof_root: str,
    makefile_include_dir: str,
    examples_dir: str,
    use_examples: bool,
    dry_run: bool,
    metrics_path: str,
    pricing: Optional[Dict[str, float]],
    model: Optional[str],
    extra_args: Optional[list[str]],
) -> Dict[str, Any]:
    """Run Codex for a single target definition."""
    function = target.get("function")
    file_path = target.get("file_path")
    if not function or not file_path:
        _fail("Each target must include function and file_path.")

    target_file = os.path.join(project_root, file_path)
    proof_dir = os.path.join(project_root, proof_root, function)
    makefile_include = os.path.join(project_root, makefile_include_dir, "Makefile.include")
    log_dir = os.path.join(project_root, proof_root, "logs")

    ctx = {
        "FUNCTION_NAME": function,
        "TARGET_FILE": target_file,
        "PROOF_DIR": proof_dir,
        "MAKEFILE_INCLUDE": makefile_include,
        "EXAMPLES_DIR": examples_dir,
        "LOG_DIR": log_dir,
    }

    prompt = render_prompt(template, ctx, use_examples)
    run_id = uuid.uuid4().hex
    prompt = inject_run_marker(prompt, run_id)

    os.makedirs(proof_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"codex_{function}.log")

    start = time.time()
    exit_code = run_codex(
        prompt,
        log_path,
        dry_run,
        cwd=project_root,
        model=model,
        extra_args=extra_args,
    )
    duration_sec = time.time() - start

    session_path = find_session_file_by_marker(run_id)
    tokens = parse_token_usage_from_session(session_path) if session_path else {
        "input_tokens": None,
        "cached_tokens": None,
        "output_tokens": None,
        "reasoning_tokens": None,
        "total_tokens": None,
    }
    costs = estimate_cost(tokens, pricing)

    coverage = read_coverage_metrics(proof_dir)
    verification = read_verification_results(proof_dir)

    compile_success = os.path.exists(coverage.get("coverage_path", ""))

    metrics = {
        "function": function,
        "proof_dir": proof_dir,
        "log_path": log_path,
        "run_id": run_id,
        "session_path": str(session_path) if session_path else None,
        "success": exit_code == 0,
        "exit_code": exit_code,
        "duration_sec": duration_sec,
        "compile_success": compile_success,
        "tokens": tokens,
        "costs": costs,
        "coverage": coverage,
        "verification": verification,
    }
    write_metrics(metrics_path, metrics)
    return metrics


def main() -> None:
    """CLI entry point: render prompts per target and invoke Codex."""
    parser = argparse.ArgumentParser(description="CodexUP: run Codex per target proof.")
    parser.add_argument("--proof-config", required=True, help="Path to proof/targets YAML.")
    parser.add_argument("--codex-config", required=True, help="Path to Codex agent YAML.")
    parser.add_argument("--prompt", required=True, help="Path to prompt template.")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without running Codex (default: False).")
    parser.add_argument("--use-examples", action="store_true", help="Include examples section in the prompt (default: False).")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of targets to run (default: 0 = all).")
    parser.add_argument("--jobs", type=int, default=1, help="Number of parallel targets to run (default: 1).")
    args = parser.parse_args()

    check_codex_prereqs()

    proof_config = load_config(args.proof_config)
    codex_config = load_config(args.codex_config)

    project_root = proof_config.get("project_root")
    proof_root = proof_config.get("proof_root")
    makefile_include_dir = proof_config.get("makefile_include_dir")
    examples_dir = proof_config.get("examples_dir", "")
    pricing = codex_config.get("pricing")
    model = codex_config.get("model")
    extra_args = codex_config.get("codex_cli_args")

    if not project_root or not proof_root or not makefile_include_dir:
        _fail("Config missing required fields: project_root, proof_root, makefile_include_dir")

    targets = proof_config.get("targets") or []
    if not targets:
        _fail("No targets found in config.")

    with open(args.prompt, "r", encoding="utf-8") as f:
        template = f.read()

    proof_root_dir = os.path.join(project_root, proof_root)
    os.makedirs(proof_root_dir, exist_ok=True)
    prompt_path = os.path.join(proof_root_dir, "prompt.txt")
    if not os.path.exists(prompt_path):
        with open(prompt_path, "w", encoding="utf-8") as prompt_file:
            prompt_file.write(template)

    selected_targets = targets[: args.limit] if args.limit else targets

    metrics_path = os.path.join(project_root, proof_root, "logs", "codex_metrics.jsonl")
    summary_path = os.path.join(project_root, proof_root, "logs", "codex_summary.json")

    metrics_list: list[Dict[str, Any]] = []
    failures = 0
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as executor:
        futures = {
            executor.submit(
                _run_target,
                template,
                target,
                project_root,
                proof_root,
                makefile_include_dir,
                examples_dir,
                args.use_examples,
                args.dry_run,
                metrics_path,
                pricing,
                model,
                extra_args,
            ): target
            for target in selected_targets
        }

        for future in as_completed(futures):
            target = futures[future]
            function = target.get("function", "<unknown>")
            try:
                metrics = future.result()
                metrics_list.append(metrics)
            except Exception as exc:
                print(f"[codexup] {function} failed with exception: {exc}", file=sys.stderr)
                failures += 1
                continue
            if metrics.get("exit_code", 0) != 0:
                print(f"[codexup] {function} failed (exit {metrics.get('exit_code')}).", file=sys.stderr)
                failures += 1

    summary = summarize_metrics(metrics_list)
    if summary:
        os.makedirs(os.path.dirname(summary_path), exist_ok=True)
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)

    if failures:
        _fail(f"{failures} target(s) failed.")


if __name__ == "__main__":
    main()
