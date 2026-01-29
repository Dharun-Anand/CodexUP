# CodexUP
General Code Agent for Automated Unit Proof Generation

## Quick start

```bash
pip install -r requirements.txt
python /home/dananday/Research/CodexUP/src/codexup.py \
  --config /home/dananday/Research/CodexUP/configs/target-RIOT.yaml \
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

- `--dry-run`: Print the Codex command and log path without executing.
- `--use-examples`: Keep the [Examples] section in the prompt; otherwise it is removed.
- `--limit N`: Run only the first N targets.

## Notes

- Logs are written to `<project_root>/<proof_root>/logs/codex_<function>.log`.
