# CodexUP
General Code Agent for Automated Unit Proof Generation

## Quick start

```bash
pip install -r requirements.txt
export OPENAI_API_KEY="your_api_key_here"
# Ensure the codex CLI is installed and on your PATH
python /home/dananday/Research/CodexUP/src/codexup.py \
  --proof-config /home/dananday/Research/CodexUP/configs/target-RIOT.yaml \
  --codex-config /home/dananday/Research/CodexUP/configs/codex-gpt-5.2-codex.yaml \
  --prompt /home/dananday/Research/CodexUP/prompts/prompt.txt \
  --use-examples
```

## Prompt placeholders

The prompt template supports these variables:

- `{TARGET_FILE}`
- `{FUNCTION_NAME}`
- `{MAKEFILE_INCLUDE}`
- `{PROOF_DIR}`
- `{EXAMPLES_DIR}`
- `{LOG_DIR}`

If `--use-examples` is not set, the entire `[Examples]` section is removed.

## Options

- `--proof-config`: Path to proof/targets YAML.
- `--codex-config`: Path to Codex agent YAML.
- `--dry-run`: Print the Codex command and log path without executing.
- `--use-examples`: Keep the [Examples] section in the prompt; otherwise it is removed.
- `--limit N`: Run only the first N targets.

## Metrics output

After a run, CodexUP writes:

- Per-target metrics: `<project_root>/<proof_root>/logs/codex_metrics.jsonl`
- Summary metrics: `<project_root>/<proof_root>/logs/codex_summary.json`

Token usage is collected by injecting a unique run marker into each prompt and
matching it to the Codex session JSONL under `~/.codex/sessions/**/rollout-*.jsonl`.

### Optional cost estimation

Example Codex agent config for `gpt-5.2-codex`:

```yaml
pricing:
  input_per_1m: 1.75
  cached_per_1m: 0.175
  output_per_1m: 14.0
```

## Notes

- Logs are written to `<project_root>/<proof_root>/logs/codex_<function>.log`.
