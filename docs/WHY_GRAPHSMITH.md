# Why Graphsmith

## The problem with tool calls

Most LLM agent frameworks give models a flat list of tools.
Each tool is a function call. Composition is implicit — the LLM
decides which tools to call and in what order, with no shared
contract, no type checking, and no reuse across tasks.

This works for simple cases. It breaks down when:
- the same multi-step workflow is needed repeatedly
- you want to test or validate a workflow before running it
- you want to know what effects a workflow will have
- you want to share a workflow between teams or projects

## The skill graph alternative

Graphsmith explores a different model: **reusable typed subgraphs**.

A skill is a versioned DAG with:
- **Typed inputs and outputs** — you know what goes in and comes out
- **Declared effects** — you know if it calls an LLM, reads the network, etc.
- **Deterministic execution** — same inputs produce same execution path
- **Composability** — skills invoke other skills via `skill.invoke`

Instead of asking an LLM "figure out how to do this with these tools",
you ask: "compose a workflow from these published skills."

## Deterministic runtime

The runtime executes graphs in topological order. Values flow through
a typed address store. Every node runs or fails deterministically.
The only non-deterministic element is LLM provider output, which is
injected and controllable.

This means you can:
- Test a workflow with mock providers
- Validate graph structure before execution
- Record execution traces for every run
- Compare runs across time

## Skill promotion from traces

When the same op-sequence pattern appears across multiple execution
traces, Graphsmith flags it as a **promotion candidate** — a workflow
fragment that might be worth extracting into a reusable skill.

This is the beginning of a feedback loop:
1. Humans or LLMs compose glue graphs
2. The runtime executes and traces them
3. Repeated patterns are surfaced
4. Humans decide what to promote to reusable skills
5. The registry grows, making future planning richer

## Research direction

Graphsmith is a prototype exploring whether this model works in
practice. The current implementation is a reference system — local
only, single-machine, with a small skill library.

Open questions:
- Can LLMs reliably plan against typed skill contracts?
- Does skill reuse actually compound over time?
- What is the right granularity for skills?
- How should skill quality and trust be tracked?

These are research questions. Graphsmith is a tool for investigating them.

## Ecosystem potential

If the model works, the natural next steps are:
- A public skill registry (like npm for graph skills)
- Semantic search over skill contracts
- Automated quality scoring from execution traces
- Multi-agent collaboration through shared skill libraries

None of these exist yet. Graphsmith is the foundation for exploring
whether they should.
