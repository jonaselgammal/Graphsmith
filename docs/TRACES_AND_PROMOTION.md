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
2. Extract two signatures from each trace:
   - a flat top-level op-sequence signature
   - a richer structural signature that includes nested child traces when present
3. Group traces by identical structural signature.
4. Any signature appearing >= `min_frequency` times is a
   promotion candidate.

This is still intentionally heuristic. It does not inspect full edge wiring or
full config equivalence, but it is more informative than the original flat
op-only grouping.

## Promotion candidate model

```
PromotionCandidate
  signature: str           # e.g. "template.render -> llm.generate"
  structural_signature: str
  ops: list[str]           # ordered op list
  frequency: int           # how many traces matched
  trace_ids: list[str]     # supporting trace IDs
  inferred_inputs: list[str]  # input port names seen across traces
  inferred_outputs: list[str] # output port names seen across traces
  suggested_skill_id: str
  suggested_name: str
  confidence: float
  notes: str               # limitations / caveats
```

## Evidence attached to a candidate

- The exact trace IDs where the pattern appeared.
- Frequency count.
- Union of input/output names observed across matching traces.
- The flat op sequence and the richer structural signature.
- A suggested reusable skill identity for follow-up review.
- A heuristic confidence score.

## Explicit limitations

- No full graph structure matching.
- No exact config comparison — two runs with different templates
  can still collapse together.
- No automatic publication — candidates are advisory only.
- No confidence scoring beyond raw frequency.
- Suggested skill IDs are heuristics, not authoritative promotion decisions.

## Human workflow

The intended workflow is:

1. Execute real plans with trace capture enabled.
2. Inspect stored traces:
   - `graphsmith traces-list --summary`
   - `graphsmith traces-show <trace_id> --summary`
3. Mine repeated patterns:
   - `graphsmith promote-candidates`
4. Inspect example traces attached to a candidate.
5. Decide manually whether the repeated fragment is:
   - a reusable skill worth promoting
   - only a coincidental op-sequence match
   - still too unstable or too underspecified

Graphsmith does not auto-promote candidates. Promotion remains a human
judgment step so the registry grows deliberately rather than
optimistically.
