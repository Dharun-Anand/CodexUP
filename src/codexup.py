#!/usr/bin/env python3
import argparse
import os
import re
import shutil
import subprocess
import sys
from typing import Dict, Any
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


def run_codex(prompt: str, log_path: str, dry_run: bool, cwd: str) -> int:
    """Run codex with the rendered prompt and write stdout/stderr to a log file."""
    cmd = ["codex", "exec", "--full-auto", prompt]
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


def _run_target(
    template: str,
    target: Dict[str, Any],
    project_root: str,
    proof_root: str,
    makefile_include_dir: str,
    examples_dir: str,
    use_examples: bool,
    dry_run: bool,
) -> int:
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

    os.makedirs(proof_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"codex_{function}.log")

    return run_codex(prompt, log_path, dry_run, cwd=project_root)


def main() -> None:
    """CLI entry point: render prompts per target and invoke Codex."""
    parser = argparse.ArgumentParser(description="CodexUP: run Codex per target proof.")
    parser.add_argument("--config", required=True, help="Path to target YAML.")
    parser.add_argument("--prompt", required=True, help="Path to prompt template.")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without running Codex (default: False).")
    parser.add_argument("--use-examples", action="store_true", help="Include examples section in the prompt (default: False).")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of targets to run (default: 0 = all).")
    parser.add_argument("--jobs", type=int, default=1, help="Number of parallel targets to run (default: 1).")
    args = parser.parse_args()

    check_codex_prereqs()

    config = load_config(args.config)

    project_root = config.get("project_root")
    proof_root = config.get("proof_root")
    makefile_include_dir = config.get("makefile_include_dir")
    examples_dir = config.get("examples_dir", "")

    if not project_root or not proof_root or not makefile_include_dir:
        _fail("Config missing required fields: project_root, proof_root, makefile_include_dir")

    targets = config.get("targets") or []
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
            ): target
            for target in selected_targets
        }

        for future in as_completed(futures):
            target = futures[future]
            function = target.get("function", "<unknown>")
            try:
                exit_code = future.result()
            except Exception as exc:
                print(f"[codexup] {function} failed with exception: {exc}", file=sys.stderr)
                failures += 1
                continue
            if exit_code != 0:
                print(f"[codexup] {function} failed (exit {exit_code}).", file=sys.stderr)
                failures += 1

    if failures:
        _fail(f"{failures} target(s) failed.")


if __name__ == "__main__":
    main()
