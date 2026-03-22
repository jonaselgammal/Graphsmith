# CLI Reference

## graphsmith --version

Print the installed version.

```bash
graphsmith --version
# graphsmith 1.0.0
```

## graphsmith doctor

Check system readiness: Python version, dependencies, API keys, skills.

```bash
graphsmith doctor
```

## graphsmith run-interactive

Interactive planning session. Type goals, inspect candidates, compare alternatives.

```bash
graphsmith run-interactive [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--provider` | `anthropic` | LLM provider: anthropic, openai |
| `--model` | auto | Model name |
| `--base-url` | none | Base URL for OpenAI-compatible providers |
| `--candidates` | `3` | Number of IR candidates to generate |
| `--decompose/--no-decompose` | `--decompose` | Enable semantic decomposition |

### Interactive commands

| Command | Description |
|---------|-------------|
| `:help` | Show all commands |
| `:candidates` | Show all candidates with scores |
| `:compare` | Diff selected vs alternative candidate |
| `:decomposition` | Show the semantic decomposition |
| `:rerun` | Rerun the last goal |
| `:rerun N` | Rerun with N candidates |
| `:history` | Show previous goals |
| `:quit` | Exit |

## graphsmith eval-planner

Evaluate planner quality against goal sets.

```bash
graphsmith eval-planner [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--goals` | `evaluation/goals` | Directory containing goal JSON files |
| `--registry` | default | Registry root with published skills |
| `--backend` | `mock` | Planner: `mock`, `llm` (direct), `ir` (recommended) |
| `--ir-candidates` | `1` | IR candidates for reranking |
| `--decompose` | off | Enable semantic decomposition |
| `--provider` | `echo` | LLM provider |
| `--model` | none | Model name |
| `--base-url` | none | OpenAI-compatible base URL |
| `--delay` | `0` | Seconds between goals (rate limiting) |
| `--save-diagnostics` | none | Save per-goal diagnostics JSON |
| `--save-failed-plans` | none | Save failed plan artifacts |

### Recommended configuration

```bash
graphsmith eval-planner \
  --backend ir \
  --ir-candidates 3 \
  --decompose \
  --provider anthropic \
  --model claude-haiku-4-5-20251001 \
  --goals evaluation/goals \
  --registry "$REG" \
  --delay 2
```

## graphsmith create-skill

Generate a new skill scaffold.

```bash
graphsmith create-skill <name> [--output-dir DIR]
```

Creates `skill.yaml`, `graph.yaml`, and `examples.yaml` in a new directory.

## graphsmith validate

Validate a skill package.

```bash
graphsmith validate examples/skills/text.normalize.v1
```

## graphsmith publish

Publish a skill to a local registry.

```bash
graphsmith publish examples/skills/text.normalize.v1 --registry "$REG"
```

## graphsmith plan

Generate a plan from a natural language goal.

```bash
graphsmith plan "normalize and summarize" \
  --backend ir --provider anthropic --registry "$REG"
```

## graphsmith run

Run a skill package directly.

```bash
graphsmith run examples/skills/text.normalize.v1 \
  --input '{"text": "  Hello World  "}'
```

## graphsmith run-plan

Run a saved plan JSON.

```bash
graphsmith run-plan plan.json --input '{"text": "hello"}' --registry "$REG"
```

## graphsmith search

Search published skills.

```bash
graphsmith search "keywords" --registry "$REG"
```

## graphsmith list-ops

List all primitive ops.

```bash
graphsmith list-ops
```
