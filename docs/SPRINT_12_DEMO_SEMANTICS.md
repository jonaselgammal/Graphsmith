# Sprint 12 — Demo Semantics

## Skills improved

### text.normalize.v1
- **Before**: pass-through via template.render (no actual normalization)
- **After**: real normalization via a new `text.normalize` pure op
- Behavior: strip outer whitespace, collapse repeated spaces, lowercase
- Example: `"  AI   agents ARE  "` → `"ai agents are"`

### text.extract_keywords.v1
- Output type updated from `string` to `string` (comma-separated keywords)
- Contract documented: with mock LLM, output echoes the prompt;
  with real LLM, output is a comma-separated keyword list
- examples.yaml updated with realistic expected output

### text.join_lines.v1
- Graph rewritten to use `template.render` with a clearer contract
- examples.yaml updated

## New op: text.normalize

A small pure op added to `graphsmith/ops/text_ops.py`:
- Input: `text` (string)
- Output: `{"normalized": <string>}`
- Behavior: `text.strip().lower()` + collapse `\s+` to single space
- Registered as `text.normalize` in PRIMITIVE_OPS — but NOT as a
  graph-level primitive op. It is used only inside the skill graph
  for text.normalize.v1.

Actually — to avoid adding a new primitive op to the spec, the
normalization is done by a template.render node followed by a
dedicated Python op. Since adding ops to PRIMITIVE_OPS changes the
spec, we instead implement normalization inside the skill graph
using a custom approach: a `template.render` pass-through followed
by... no, this won't work.

**Decision**: Add `text.normalize` as a new pure primitive op. It is
small (5 lines of logic), deterministic, and fills a real gap. The
spec's PRIMITIVE_OPS set is extended by one entry.

## Flagship demo workflow

**Goal**: "Normalize text, extract keywords, and format as bullets"

Pipeline:
1. `text.normalize.v1` → lowercase + trim + collapse spaces
2. `text.extract_keywords.v1` → extract keywords via LLM
3. `template.render` (inline) → format as bullet list

With mock LLM, step 2 echoes the prompt. With real LLM, step 2
produces actual keywords.

The demo shows the full Graphsmith lifecycle:
publish → plan → run → trace → inspect

## Mock vs real LLM behavior

| Step | Mock LLM | Real LLM |
|------|----------|----------|
| normalize | deterministic | deterministic |
| extract_keywords | echoes prompt | comma-separated keywords |
| join/format | deterministic | deterministic |

## What remains intentionally simple

- No NLP tokenizer for normalization — just regex
- No structured keyword parsing — comma-separated string
- text.join_lines.v1 is a simple template pass-through
- Mock LLM always echoes — no fake keyword generation
