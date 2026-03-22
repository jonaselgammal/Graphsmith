# Graphsmith

**Semantic planner + compiler for graph-based AI workflows.**

Graphsmith composes typed, executable skill graphs from natural language goals.
An LLM plans *what* to do; Graphsmith deterministically compiles *how* to wire it.

## How it works

```
goal → decompose → generate IR candidates → score → compile → validate → execute
         (LLM)         (LLM × N)         (rules)  (deterministic)
```

1. **Decomposition** — LLM classifies the goal into content transforms + presentation intent
2. **IR generation** — LLM produces N candidate plans as semantic IR
3. **Scoring** — deterministic semantic scorer ranks candidates
4. **Compilation** — compiler lowers IR to executable graph
5. **Validation** — structural checks (types, DAG, bindings) before execution

The LLM never serializes raw graph structures. The compiler handles all graph
mechanics deterministically.

## Results

| Set | Claude Haiku | Llama 3.1 8B |
|-----|-------------|--------------|
| Benchmark (9) | 9/9 (100%) | 8-9/9 |
| Holdout (15) | 15/15 (100%) | 12-14/15 |
| Challenge (12) | 12/12 (100%) | 10-12/12 |
| **Total (36)** | **36/36 (100%)** | **~86-94%** |

## Where to start

- **[Getting Started](getting_started.md)** — install, configure, run your first plan
- **[CLI Reference](cli.md)** — all commands and flags
- **[Skills](SKILLS.md)** — 21 built-in skills + how to create your own
- **[Architecture](architecture.md)** — how the system works
- **[Examples](examples.md)** — end-to-end usage examples
- **[Evaluation](evaluation.md)** — running benchmarks
- **[Debugging](debugging.md)** — inspecting traces and failures

## Links

- [GitHub Repository](https://github.com/jonaselgammal/Graphsmith)
- [Changelog](https://github.com/jonaselgammal/Graphsmith/blob/main/CHANGELOG.md)
