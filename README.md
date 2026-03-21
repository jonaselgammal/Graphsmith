# Graphsmith

**Semantic planner + compiler for graph-based AI workflows.**

Graphsmith composes typed, executable skill graphs from natural language goals.
An LLM plans *what* to do; Graphsmith deterministically compiles *how* to wire it.

Claude Haiku: **36/36 (100%)** on benchmark + holdout + challenge.
Llama 3.1 8B: **~86-94%** with reranking + decomposition.

No public servers. Everything runs locally.

## Key idea

```
goal → decompose → generate IR candidates → score → compile → validate → execute
         (LLM)         (LLM × N)         (rules)  (deterministic)
```

1. **Decomposition** — LLM classifies the goal into content transforms + presentation intent
2. **IR generation** — LLM produces N candidate plans as semantic IR (steps, data flow, config)
3. **Scoring** — deterministic semantic scorer ranks candidates
4. **Compilation** — compiler lowers IR to executable graph (edges, node IDs, outputs)
5. **Validation** — structural checks (types, DAG, bindings) before execution

The LLM never serializes raw graph structures. It only describes semantic intent.
The compiler handles all graph mechanics deterministically.

## Current capabilities

- **Text pipelines**: normalize, summarize, extract keywords, title case, word count, sentiment
- **JSON extraction**: reshape, extract field
- **Formatting**: join lines (lists), template rendering (headers), prefix lines
- **Multi-step workflows**: chains, fan-out, multi-output goals
- **15 skills**, 36 evaluation goals across 3 test sets

## Quickstart

```bash
# Install
pip install -e ".[dev]"

# Create a .env file with your API key (gitignored)
cp .env.example .env
# Edit .env: GRAPHSMITH_ANTHROPIC_API_KEY=sk-ant-...

# Publish all skills
REG=$(mktemp -d)
for d in examples/skills/*/; do graphsmith publish "$d" --registry "$REG"; done

# Run the full evaluation (recommended configuration)
graphsmith eval-planner --goals evaluation/goals --registry "$REG" \
  --backend ir --ir-candidates 3 --decompose \
  --provider anthropic --model claude-haiku-4-5-20251001 --delay 2
```

## Recommended configuration

```bash
graphsmith eval-planner \
  --backend ir \
  --ir-candidates 3 \
  --decompose \
  --provider anthropic \
  --model claude-haiku-4-5-20251001 \
  --goals evaluation/goals \
  --registry "$REG"
```

| Flag | Purpose |
|------|---------|
| `--backend ir` | Use IR pipeline (LLM → IR → compile), not raw graph emission |
| `--ir-candidates 3` | Generate 3 candidates, pick best via semantic scoring |
| `--decompose` | Add decomposition stage for semantic grounding |
| `--provider anthropic` | Use Anthropic API |
| `--model claude-haiku-4-5-20251001` | Fast, capable model |

## Performance

| Set | Goals | Claude Haiku | Llama 3.1 8B |
|-----|-------|-------------|--------------|
| Benchmark | 9 | 9/9 (100%) | 8-9/9 |
| Holdout | 15 | 15/15 (100%) | 12-14/15 |
| Challenge | 12 | 12/12 (100%) | 10-12/12 |
| **Total** | **36** | **36/36 (100%)** | **~31-34/36 (86-94%)** |

Stability on Llama 3.1 8B (3 runs): 28/36 goals always pass, 0 always fail,
8 intermittent (output naming noise).

## Project structure

```
graphsmith/
  planner/          IR pipeline: decomposition, prompt, parser, compiler, scorer
  models/           Pydantic models (SkillGraph, GlueGraph, GraphBody)
  validator/        Deterministic validation (types, DAG, bindings)
  runtime/          Topological executor + value store
  ops/              Primitive ops + LLM providers (Anthropic, OpenAI-compatible)
  registry/         Local skill registry (publish, search, fetch)
  evaluation/       Eval harness, stability analysis, candidate dataset
  cli/              Typer CLI (20+ commands)
  traces/           Execution trace persistence + promotion mining
examples/skills/    15 skill packages
evaluation/         36 eval goals (benchmark + holdout + challenge)
scripts/            Eval runners, analysis tools, data collection
tests/              922 tests
docs/               Architecture and sprint documentation
```

## CLI commands

| Command | Description |
|---------|-------------|
| `eval-planner` | Evaluate planner quality against goal sets |
| `plan` | Generate a plan from a natural language goal |
| `plan-and-run` | Plan + execute in one step |
| `run-plan` | Run a saved plan |
| `run` | Run a skill package directly |
| `publish` | Publish a skill to the local registry |
| `search` | Search published skills |
| `validate` | Validate a skill package |
| `ui` | Launch local plan inspector (browser) |
| `version` | Print version |

Run `graphsmith --help` for the full list.

## LLM providers

```bash
# Anthropic (recommended)
export GRAPHSMITH_ANTHROPIC_API_KEY=sk-ant-...

# Groq / OpenAI-compatible
export GRAPHSMITH_GROQ_API_KEY=gsk_...
graphsmith eval-planner --provider openai --model llama-3.1-8b-instant \
  --base-url https://api.groq.com/openai/v1
```

Or create a `.env` file (gitignored):
```
GRAPHSMITH_ANTHROPIC_API_KEY=sk-ant-...
GRAPHSMITH_GROQ_API_KEY=gsk_...
```

## Testing

```bash
pytest              # 922 tests, no network required
pytest -v           # verbose
pytest -x           # stop on first failure
```

## Status and roadmap

**v1 (current)**: architecture stable, 36/36 on Claude Haiku.

| Component | Status |
|-----------|--------|
| IR compiler | Stable |
| Deterministic scorer | Stable |
| Decomposition | Stable |
| Candidate reranking | Stable |
| Stability measurement | Complete |
| Candidate dataset pipeline | Complete |
| Learned reranker | Prototype (no headroom on Claude) |

**Next steps**:
- Weak-model optimization (Llama 3.1 8B)
- Learned reranker (when Llama data shows headroom)
- Broader skill/goal coverage

## Documentation

- [Architecture (v1)](docs/GRAPHSMITH_ARCHITECTURE_V1.md) — full system design
- [Running evaluations](docs/RUNNING_EVALS.md) — how to reproduce results
- [IR architecture](docs/PLANNING_IR_ARCHITECTURE.md) — IR design rationale
- [Evaluation comparison](docs/IR_EVAL_COMPARISON.md) — sprint-by-sprint results
- [Why Graphsmith](docs/WHY_GRAPHSMITH.md) — motivation

## License

[MIT](LICENSE)
