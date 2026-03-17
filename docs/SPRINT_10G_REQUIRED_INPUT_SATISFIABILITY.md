# Sprint 10G — Required Input Satisfiability

## Exact failure observed

```
FAIL: Execution failed at node 'call': Address 'input.max_sentences'
has no value. Available: ['input.text']
```

The LLM-generated plan invoked `text.summarize.v1` and wired
`input.max_sentences` as a graph-level input, but the user only
provided `{"text": "..."}`. The runtime failed at value resolution.

## Root cause analysis

Three contributing factors:

1. **Prompt Example 1** uses `text.summarize.v1` with `max_sentences`,
   teaching the LLM to include it even when the user's goal doesn't
   mention sentence counts.

2. **Candidate listing** doesn't distinguish required vs optional
   inputs — the LLM can't tell which inputs it must wire.

3. **Executor** doesn't check that user-provided inputs cover all
   required graph inputs before starting execution. The error only
   surfaces deep in the value store.

## Fix layers

### Prompt
- Example 1: use a single-input skill or make the example match
  the common single-input case. Remove `max_sentences` from
  Example 1 to avoid teaching the LLM to add unnecessary inputs.
- Add instruction: "Only declare inputs the user would provide.
  Do not add optional skill inputs unless the goal requires them."

### Candidate rendering
- Show required/optional annotations in candidate input lists:
  `inputs: [text (required), max_sentences (optional)]`
- Store `required_input_names` and `optional_input_names` in
  `IndexEntry` (backward-compatible: old entries without these
  fields fall back to treating all inputs as listed).

### Executor pre-check
- Before executing, check that every required graph input has a
  value in the user-provided inputs dict. Fail early with a clear
  message naming the missing inputs.

## Why strict and safe

- No auto-filling of missing inputs
- No silent dropping of unresolvable edges
- Prompt reduces the likelihood of the issue
- Executor pre-check catches it before node execution begins
- Candidate annotations help the LLM make informed decisions
