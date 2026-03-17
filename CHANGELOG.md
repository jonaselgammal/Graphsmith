# Changelog

## 0.2.0

### Spec and Runtime (Sprints 01–02)
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
- Recursion depth protection and self-recursion detection

### Planner (Sprint 04)
- Mock planner backend with candidate retrieval
- GlueGraph model (task-specific, not publishable)
- Unresolved hole reporting
- Validation of planner output via synthetic SkillPackage
- CLI: plan

### Traces and Promotion (Sprint 05)
- Trace persistence (one JSON file per run)
- Trace listing, viewing, and summary
- Trace pruning by age
- array.map and array.filter ops
- Promotion candidate mining via op-sequence signature matching
- CLI: traces-list, traces-show, traces-prune, promote-candidates

### Integration Hardening (Sprint 06)
- parallel.map with sequential fallback semantics
- All 12 primitive ops implemented
- CLI: version, list-ops

### Plan Execution (Sprint 07)
- LLM planner output parser (JSON extraction from raw text)
- Plan-and-run (plan + validate + execute in one step)
- Save/load plans as first-class GlueGraph JSON
- CLI: plan-and-run, run-plan, plan --save

### Provider Integration (Sprint 08)
- AnthropicProvider and OpenAICompatibleProvider via httpx
- Provider factory with env-var configuration
- Model discovery (list-models)
- Actionable error messages for model-not-found, auth failures
- Structured planning prompt with versioning (v3)
- Provider-level JSON output hints
- Robust parser: handles code fences, surrounding prose, balanced-brace extraction
- CLI: list-models, --provider, --model, --base-url

### Real LLM Validation (Sprint 09)
- Gated smoke tests for Anthropic and OpenAI providers
- End-to-end plan-and-run with real provider
- CLI: version, list-ops

### Multi-Skill Library (Sprint 10)
- 4 new example skills: text.normalize.v1, text.extract_keywords.v1,
  json.reshape.v1, text.join_lines.v1
- Multi-skill composition tests
- Publish-time dependency warnings
- Type grammar alignment (array<string> enforcement)
- Placeholder token elimination from planning prompts
- Output mapping completeness validation
- Required-input satisfiability pre-check at execution time
- Optional input semantics (graceful skip for absent optional bindings)
- Conflicting binding detection at validation time
- --save-on-failure for debugging failed plans

### Release Polish (Sprint 11)
- Version bumped to 0.2.0
- README rewritten as project landing page
- Architecture diagram (Mermaid)
- Example workflows documentation
- Changelog

## 0.1.0

Initial scaffold with spec, models, and placeholder modules.
