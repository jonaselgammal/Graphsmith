# Graphsmith Runtime — Value-Binding Semantics (v1)

## Overview

This document defines how values flow through a Graphsmith graph at runtime.
These rules are intentionally simple and explicit. No implicit coercion,
no silent override, no ambient state.

## Concepts

| Term | Definition |
|------|-----------|
| **address** | A dotted string `<scope>.<port>` that names a value. |
| **scope** | Either `input` (graph-level inputs) or a `<node_id>`. |
| **port** | A named slot within a scope (e.g. `text`, `rendered`). |
| **value store** | A flat `dict[str, Any]` keyed by address. Populated during execution. |

## Binding sources (in order of resolution)

A node receives inputs from three sources:

1. **Edges** — `from: input.text  to: prompt.text` writes the graph input
   `text` into node `prompt`'s port `text`.
2. **Node `inputs`** — `inputs: {prompt: prompt.rendered}` is shorthand:
   the value at address `prompt.rendered` is bound to this node's port `prompt`.
3. **Node `config`** — static parameters passed to the op (e.g. a template string).
   Config is **not** part of the port namespace; it is passed separately.

## Conflict rule

Edges and node `inputs` both write into the same port namespace.
If both bind the **same port** on the same node, execution fails with a
deterministic error **before** any node runs.

## Resolution order

1. **Before execution** — Build a per-node input binding map by merging
   edges and node `inputs`. Detect conflicts.
2. **At execution time** — For each node (in topological order), resolve
   every binding address against the value store.
   - **Required input** addresses must resolve; a missing address is a
     runtime error.
   - **Optional input** addresses (`input.<name>` where `<name>` is
     declared `required: false` in the skill contract) are skipped if
     absent — the port is simply not included in the node's inputs.
3. The op receives `(config: dict, inputs: dict)` and returns
   `outputs: dict[str, Any]`.
4. Each key in the returned outputs dict is stored at `<node_id>.<key>`.

## Graph inputs

Before execution, each key `k` from the user-provided input payload is
stored at address `input.<k>`.

## Graph outputs

After all nodes execute, each entry in `graph.yaml`'s `outputs` mapping
is resolved:  `summary: summarize.text` → look up `summarize.text` in
the value store.

## Op output port conventions

Each op defines its own output port names:

| Op | Output ports |
|----|-------------|
| `template.render` | `rendered` |
| `json.parse` | `parsed` |
| `select.fields` | `selected` |
| `assert.check` | `value` (pass-through) |
| `branch.if` | `result` |
| `fallback.try` | `result` |
| `llm.generate` | `text` |
| `llm.extract` | `extracted` |
| `array.map` | `mapped` |
| `array.filter` | `filtered` |
| `parallel.map` | `results` |
| `text.normalize` | `normalized` |

## Determinism

- Topological order is deterministic (stable sort by node ID at each level).
- All value resolution is eager — no lazy evaluation.
- The only non-deterministic element is LLM provider output, which is
  controlled by a pluggable interface.
