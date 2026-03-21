# Changelog

## 1.0.0

### Planning IR Architecture
- Semantic Planning IR: LLM emits structured intent (steps, sources, config),
  compiler deterministically lowers to executable graphs
- Deterministic compiler: step name sanitization, type normalization, edge
  construction, DAG validation — no raw graph editing by LLM
- Semantic decomposition: optional stage that classifies goals into content
  transforms + presentation intent before IR generation
- Multi-candidate reranking: generate N IR candidates, score with deterministic
  semantic scorer, select best valid candidate
- IR prompt versioning (ir-v3) with step count guidance, paraphrase mapping,
  and output naming rules

### Evaluation
- 36 evaluation goals across 3 sets (benchmark, holdout, challenge)
- Claude Haiku: 36/36 (100%)
- Llama 3.1 8B: ~86-94% with decomposition + reranking
- Stability harness: repeated-run measurement with per-goal stability tracking
- Candidate-level dataset pipeline for reranking analysis

### Infrastructure
- .env file support for API key management
- OpenAI-compatible provider fallback for GRAPHSMITH_GROQ_API_KEY
- Trace export (JSONL) with decomposition, candidates, scores
- Comparison scripts for direct vs IR planner evaluation
- 928 tests

### Skills
- 15 skill packages: text processing, JSON extraction, formatting
- Includes distractor skills for challenge evaluation

## 0.2.0

### Spec and Runtime (Sprints 01-02)
- Pydantic v2 models for skill contracts, graph bodies, and examples
- YAML package loader with validation
- Deterministic topological executor with value-binding semantics
- 8 primitive ops: template.render, json.parse, select.fields,
  assert.check, branch.if, fallback.try, llm.generate, llm.extract
- Mock LLM provider for testing
- CLI: validate, inspect, run, schema

### Local Registry (Sprint 03)
- Filesystem-based registry with JSON index
- Publish, fetch, search with text + metadata filters
- skill.invoke for recursive sub-skill execution

### Planner (Sprint 04)
- Mock planner backend with candidate retrieval
- GlueGraph model (task-specific, not publishable)
- Unresolved hole reporting
- CLI: plan

### Traces and Promotion (Sprint 05)
- Trace persistence, listing, viewing, pruning
- Promotion candidate mining via op-sequence signature matching

### Provider Integration (Sprint 08)
- AnthropicProvider and OpenAICompatibleProvider via httpx
- Provider factory with env-var configuration
- Robust parser: code fences, balanced-brace extraction

### Multi-Skill Library (Sprint 10)
- 4 initial example skills
- Multi-skill composition
- Optional input semantics

## 0.1.0

Initial scaffold with spec, models, and placeholder modules.
