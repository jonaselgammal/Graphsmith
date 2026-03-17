# Graphsmith Traces and Promotion (v1)

## Trace persistence format

One JSON file per run, stored as:
```
<trace_root>/
  <trace_id>.json
```

`trace_id` is `<skill_id>__<timestamp_compact>`, e.g.
`text.summarize.v1__20260316T170000Z`.

Each file contains the full `RunTrace.to_dict()` output — a nested
JSON tree. Nested `skill.invoke` child traces are inlined.

## Trace storage layout

Default root: `~/.graphsmith/traces/`
Configurable via `TraceStore(root=...)` for tests.

## Trace identity model

A trace is identified by its filename (without `.json`).
There is no separate index — the filesystem is the index.
Listing scans the directory.

## Array op semantics

### `array.map`

| Field | Source | Description |
|-------|--------|-------------|
| **input** `items` | bound port | The source array |
| **config** `field` | config | Field name to extract from each item (projection mode) |
| **config** `template` | config | Template string applied to each item (template mode) |

Exactly one of `field` or `template` must be set.

- **Projection mode**: each item must be a dict; returns `[item[field], ...]`
- **Template mode**: each item is passed as `{{item}}`; returns rendered strings

Output port: `mapped`

### `array.filter`

| Field | Source | Description |
|-------|--------|-------------|
| **input** `items` | bound port | The source array |
| **config** `field` | config | Field name to check on each item |
| **config** `value` | config (optional) | If set, keep items where `item[field] == value` |

- If only `field` is set: keep items where `item[field]` is truthy
- If `field` and `value` are set: keep items where `item[field] == value`

Output port: `filtered`

## Fragment mining heuristic (v1)

The promotion prototype uses a deliberately simple heuristic:

1. Load all stored traces.
2. Extract the **op-sequence signature** from each trace:
   the ordered list of `(op,)` tuples from top-level nodes.
3. Group traces by identical op-sequence signature.
4. Any signature appearing >= `min_frequency` times is a
   promotion candidate.

This is a string-level match on the op sequence. It does not
inspect edge wiring, config, or nested structure. It is
intentionally honest about its limitations.

## Promotion candidate model

```
PromotionCandidate
  signature: str           # e.g. "template.render -> llm.generate"
  ops: list[str]           # ordered op list
  frequency: int           # how many traces matched
  trace_ids: list[str]     # supporting trace IDs
  inferred_inputs: list[str]  # input port names seen across traces
  inferred_outputs: list[str] # output port names seen across traces
  notes: str               # limitations / caveats
```

## Evidence attached to a candidate

- The exact trace IDs where the pattern appeared.
- Frequency count.
- Union of input/output names observed across matching traces.
- The op sequence itself.

## Explicit limitations

- No graph structure matching — only op sequences.
- No config comparison — two runs with different templates
  but the same op sequence are considered the same pattern.
- No nested skill.invoke inspection.
- No automatic publication — candidates are advisory only.
- No confidence scoring beyond raw frequency.
- The heuristic is intentionally simple to avoid false sophistication.
