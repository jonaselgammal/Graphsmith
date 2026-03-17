# Sprint 14 — GitHub Launch Polish

## README introduction structure

1. Title: **Graphsmith**
2. Tagline: *Forge reusable AI skill graphs.*
3. Intro paragraph: positions Graphsmith as a prototype for
   AI-native skill graphs. Research framing appears in
   explanatory text, not the headline.
4. Core concepts: short definitions of SkillGraph, GlueGraph,
   Registry, Validator, Runtime, Planner, Traces, Promotion.
5. Canonical demo: full pipeline with exact commands.
6. Limitations: honest, not apologetic.

## Canonical demo sequence

publish → search → plan → save → run-plan → traces → promote

All commands use `--mock-llm` and temp directories so they work
without API keys on any machine.

## Positioning language

- Headline: "prototype for AI-native skill graphs"
- Not "research-first" or "research-oriented" in titles
- Research direction language appears in WHY_GRAPHSMITH.md
- Limitations section is factual: "still evolving", "stable"

## Limitations stated

- Multi-skill planning quality is still evolving
- Mock planner is naive (picks first candidate)
- Real LLM plans may need prompt iteration
- Runtime and validation layers are stable
- No public registry, web UI, or distributed execution
