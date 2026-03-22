# Getting Started

## 1. Install

```bash
git clone https://github.com/jonaselgammal/Graphsmith.git
cd Graphsmith
./scripts/install.sh
source .venv/bin/activate
```

The installer creates a virtual environment, installs dependencies, and sets up
a `.env` file for API keys.

## 2. Set API keys

Edit `.env` with at least one provider key:

```
GRAPHSMITH_ANTHROPIC_API_KEY=sk-ant-...
```

Or for Groq (OpenAI-compatible):

```
GRAPHSMITH_GROQ_API_KEY=gsk_...
```

## 3. Verify setup

```bash
graphsmith doctor
```

Expected output:

```
  Graphsmith Doctor
  =================

  ✔ Python 3.12.x
  ✔ pydantic installed
  ✔ typer installed
  ✔ PyYAML installed
  ✔ httpx installed
  ✔ .env file found
  ✔ Anthropic API key set
  ✔ 21 example skills found

  All checks passed. System is ready.
```

## 4. Plan interactively

```bash
graphsmith run-interactive
```

Type a goal:

```
  > normalize this text and extract keywords
```

The system will decompose, generate candidates, score, compile, and show:

```
  Plan Summary
  ----------------------------------------
  Steps:
    1. normalize (text.normalize.v1)
    2. extract (text.extract_keywords.v1)
  Outputs:
    - normalized ← normalize.normalized
    - keywords ← extract.keywords
```

Use `:candidates` to inspect alternatives, `:compare` to see differences.

## 5. Run evaluation

```bash
REG=$(mktemp -d)
for d in examples/skills/*/; do graphsmith publish "$d" --registry "$REG" 2>/dev/null; done

graphsmith eval-planner --goals evaluation/goals --registry "$REG" \
  --backend ir --ir-candidates 3 --decompose \
  --provider anthropic --model claude-haiku-4-5-20251001 --delay 2
```

## 6. Create a new skill

```bash
graphsmith create-skill text.uppercase.v1
```

Then edit the generated files and implement your op. See [Skills](SKILLS.md) for details.

## Next steps

- [CLI Reference](cli.md) — all commands
- [Skills](SKILLS.md) — built-in skills and how to extend
- [Architecture](architecture.md) — how the system works
- [Examples](examples.md) — more usage patterns
