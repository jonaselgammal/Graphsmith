# Autogen Battery

This battery is a small end-to-end check for automatic skill generation.

It is intentionally narrow:
- a few known-good prompts
- one out-of-scope prompt
- one no-match prompt

The goal is not broad coverage. The goal is to catch obvious regressions
quickly in the user-facing `create-skill-from-goal` flow.

## Run it

```bash
python scripts/run_autogen_battery.py
```

The runner uses:
- `specs/autogen_prompt_battery.json`
- a temporary output directory
- the CLI entrypoint itself

## What it checks

For each prompt, it verifies:
- whether the command should succeed or fail
- whether the output contains the expected identifying text

## Interpreting failures

- A known-good prompt failing usually means generation, validation, or
  example testing regressed.
- An out-of-scope prompt succeeding usually means the safety boundary
  regressed.
- A no-match prompt succeeding usually means template matching became
  too permissive.

Use this battery as a quick gate before broader autogen or closed-loop
testing.
