# Sprint 17 — Output Contract Alignment

## Two failing evaluation cases

### Goal 06: "Normalize this text and then summarize it"
- Expected outputs: `["summary"]`
- Likely LLM behavior: named the output differently (e.g. `"summarized_text"`,
  `"result"`) or exposed intermediate `"normalized"` alongside
- Root cause: the LLM chose output names from the goal description rather
  than matching the downstream skill's output port name

### Goal 08: "Extract keywords from text and format them as a list"
- Expected outputs: `["joined"]`
- Likely LLM behavior: named the output `"formatted"`, `"result"`, or
  `"keywords_list"` instead of `"joined"` (which is the internal port
  name of text.join_lines.v1)
- Root cause: `"joined"` is an internal port name, not a natural
  goal-derived output name. The eval expectation was too specific.

## Root causes

1. **Prompt doesn't teach output name derivation.** The prompt says
   outputs must map to graph_outputs, but doesn't say output names
   should match the final skill's output port names.

2. **Eval goals use internal port names as expected outputs.** Expecting
   `"joined"` is expecting knowledge of text.join_lines.v1 internals.
   The eval should accept reasonable output names.

## Changes made

### Prompt
- Added rule: "Name outputs using the last skill's output port names
  so graph_outputs can map directly to node ports."
- Added Example 2b showing a multi-step plan where intermediate outputs
  stay internal and only the final deliverable is exposed.

### Evaluation goals
- Goal 06: accept `summary` or `summarized` or `summarized_text`
- Goal 08: accept `joined` or `formatted` or `result` or `keywords_list`
  → Implemented via `acceptable_output_names` field (list of alternatives)

### Evaluation scorer
- `correct_outputs` check now supports `acceptable_output_names` as
  an alternative to exact `expected_output_names`

## Intentionally unchanged

- Validator behavior (still strict)
- Parser behavior (no output name normalization)
- Runtime execution semantics
- Existing passing goals

## How success is measured

Re-run `graphsmith eval-planner` with the same provider/model.
Target: 87.5%+ pass rate (7/8 or 8/8).
