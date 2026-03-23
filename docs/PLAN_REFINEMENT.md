# Plan Refinement

Graphsmith supports interactive plan refinement through semantic deltas.
After generating a plan, you can request changes in natural language and
see the updated plan with a clear diff.

## How it works

1. Plan a goal normally
2. Inspect the plan (`:nodes`, `:candidates`, `:graph`)
3. Request a change with `:refine`
4. Graphsmith extracts a structured delta
5. Builds a refined goal incorporating the constraint
6. Replans and shows the diff

## Delta types

| Delta | Description | Example request |
|-------|-------------|-----------------|
| `add_output` | Expose an additional output | "also keep the normalized text" |
| `forbid_skill` | Remove/prevent a skill | "don't summarize" |
| `require_skill` | Ensure a skill is used | "use text.normalize.v1" |
| `add_step` | Add a processing step | "also uppercase the result" |
| `replace_presentation` | Change output formatting | "replace the list with a header" |

## Interactive commands

| Command | Description |
|---------|-------------|
| `:refine <request>` | Apply a refinement to the current plan |
| `:delta` | Show the last parsed delta |
| `:diff` | Compare previous and current plan versions |
| `:plans` | List all plan versions in this session |
| `:revert` | Go back to the previous plan version |

## Example session

```
  > normalize this text and extract keywords

  Plan Summary
  ----------------------------------------
  Flow: normalize → extract
  Steps:
    1. normalize (text.normalize.v1)
    2. extract (text.extract_keywords.v1)
  Outputs:
    - keywords ← extract.keywords

  > :refine also keep the normalized text

  Delta: add_output(normalized)

  Refined goal: normalize this text and extract keywords. Also output the normalized
  Replanning...

  Plan Summary
  ----------------------------------------
  Flow: normalize → extract
  Steps:
    1. normalize (text.normalize.v1)
    2. extract (text.extract_keywords.v1)
  Outputs:
    - keywords ← extract.keywords
    - normalized ← normalize.normalized

  Plan Diff
  ----------------------------------------
  Added outputs: normalized

  > :refine don't summarize, just extract keywords

  Delta: forbid_skill(text.summarize.v1)
  ...
```

## Plan versioning

Each plan is saved as a version within the session:

```
  > :plans

  Plan versions:
    1. v1: normalize this text and extract keyw (current)
    2. v2: normalize this text and extract keyw...

  > :revert
  Reverted to: v1: normalize this text and extract keyw
```

## Limitations

- Delta extraction uses keyword matching, not deep NLU
- One delta per refinement request
- Refinement replans from scratch (does not patch the graph directly)
- Complex multi-constraint refinements may not parse correctly
- Plan versions are session-local only
