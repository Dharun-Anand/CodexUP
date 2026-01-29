#!/usr/bin/env python3
import argparse
import os
import re
import subprocess
import sys
from typing import Dict, Any

try:
    import yaml  # type: ignore
except Exception:
    yaml = None


def _fail(msg: str) -> None:
    """Print an error message and exit."""
    print(f"[codexup] {msg}", file=sys.stderr)
    sys.exit(1)


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


def run_codex(prompt: str, log_path: str, dry_run: bool) -> int:
    """Run codex with the rendered prompt and write stdout/stderr to a log file."""
    cmd = ["codex", "exec", "--full-auto", prompt]
    if dry_run:
        print("[codexup] dry-run:", " ".join(cmd))
        print(f"[codexup] log: {log_path}")
        return 0

    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    with open(log_path, "w", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="")
            log_file.write(line)
        return process.wait()


def main() -> None:
    """CLI entry point: render prompts per target and invoke Codex."""
    parser = argparse.ArgumentParser(description="CodexUP: run Codex per target proof.")
    parser.add_argument("--config", required=True, help="Path to target YAML.")
    parser.add_argument("--prompt", required=True, help="Path to prompt template.")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without running Codex (default: False).")
    parser.add_argument("--use-examples", action="store_true", help="Include examples section in the prompt (default: False).")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of targets to run (default: 0 = all).")
    args = parser.parse_args()

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

    count = 0
    for target in targets:
        if args.limit and count >= args.limit:
            break
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

        prompt = render_prompt(template, ctx, args.use_examples)

        log_path = os.path.join(log_dir, f"codex_{function}.log")

        exit_code = run_codex(prompt, log_path, args.dry_run)
        if exit_code != 0:
            _fail(f"Codex failed for {function} (exit {exit_code}).")
        count += 1


if __name__ == "__main__":
    main()
