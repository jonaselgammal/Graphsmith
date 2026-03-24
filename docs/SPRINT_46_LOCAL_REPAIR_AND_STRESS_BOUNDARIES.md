# Sprint 46 — Local Repair and Stress Boundaries

## Summary

This sprint adds the first real structural repair step to the IR pipeline and
pairs it with crowded-registry live validation.

Two things landed:
- deterministic local repair for a narrow class of loop/branch block contract failures
- broader live stress checks against a registry containing all example skills

The goal is not “full self-healing” yet. The goal is to stop throwing away an
otherwise-good plan because one branch or loop block omitted a small piece of
locally inferable structure.

## What changed

### 1. `site/` is now ignored locally

The repo already tracks Markdown docs as source of truth and `site/` is a local
MkDocs build artifact. It is now ignored in `.gitignore` so local docs builds do
not keep showing up as unrelated untracked noise.

### 2. Deterministic local repair pass

Added `graphsmith/planner/repair.py`.

This pass runs after IR parse and before final compiler failure.
It is deterministic and local:
- no extra LLM call
- no whole-plan regeneration
- only patch the block that failed

Current supported repairs:
- infer missing `then_outputs` / `else_outputs` for branch blocks from how the
  parent plan references the branch outputs
- infer missing loop `final_outputs` from parent references plus the terminal
  body step
- infer a missing loop `$item` binding when the block has exactly one body input

### 3. IR backend integrates repair

`IRPlannerBackend` now:
- attempts local repair on compiler failure
- retries compile once on the repaired IR
- surfaces applied repairs in `PlanResult.repair_actions`

That makes repair inspectable instead of silent.

### 4. CLI and docs expose repair state

`graphsmith plan` text output now prints applied repairs when present.

`docs/PLANNING_IR_ARCHITECTURE.md` now describes the actual current repair state:
- what deterministic repair exists
- what it does not do yet
- what the next structural repair layer should cover

## Validation

Focused conda-env regression:

```bash
conda run -n graphsmith pytest \
  tests/test_planning_ir.py \
  tests/test_planner_parser.py \
  tests/test_registry.py \
  tests/test_retrieval_diagnostics.py -q

conda run -n graphsmith python -m compileall graphsmith
```

## Live stress results

Using a temp registry with all 15 example skills and Anthropic
`claude-sonnet-4-20250514`:

- challenge set: `11/12` pass
- average shortlist size: `3.9`
- retrieval remained targeted under distractor pressure

The single remaining challenge miss was:
- `"Clean up the text, pull out key topics, and format them with a header"`

Failure shape:
- retrieval was correct
- skill shortlist was correct
- planning failed on a formatting constant/input mistake
- specifically, the plan still treated the header/prefix as a missing graph input

That is an important boundary distinction: the remaining miss is not a retrieval
problem and not a control-flow problem. It is still a constant/config planning issue.

### Targeted live examples

1. Multi-stage deterministic composition
- Goal: normalize → title-case → count
- Result: planned and executed successfully

2. Branch-style goal
- Goal: “If enabled, title-case the cleaned text, otherwise just normalize it.”
- Before repair normalization: plan executed but returned `null`
- After branch input alias normalization: executed successfully and returned the expected value

3. Loop-style goal
- Goal: “For each string in the input list, normalize it and return all normalized strings.”
- Repair pass improved the failure shape by fixing shallow contract issues
- Remaining boundary: the planner still emits inconsistent loop-body contracts for this kind of goal
- In practice, this is not yet a reliable end-to-end planning capability

## Stress-testing approach

Built a temp registry containing all 15 example skills, including distractors:
- reverse
- sort_lines
- remove_duplicates
- pretty_print

Then ran live IR planning against that crowded registry with Anthropic.

This is the right shape of test because it checks:
- retrieval under distractor pressure
- multi-step composition
- whether control-flow-flavored prompts produce runnable graphs

## What to look for next

The important boundary questions are no longer only “did the model return JSON?”
They are:
- did it choose the right skills under registry noise?
- did it choose a runnable graph, not just a compilable one?
- did it use structural loop/branch constructs, or did it fall back to weaker
  value-level or primitive shortcuts?
- when it failed, was the failure local enough that we can patch it?

Current answer:
- branch-style value selection is now repairable in a bounded deterministic way
- loop-style collection planning is still not robust enough for reliable live execution
- crowded-registry retrieval is strong enough that it is no longer the main bottleneck on these cases

## Next step

Keep pushing along the same axis:
- structural repair from runtime traces
- branch/loop region patching instead of whole-plan replanning
- richer stress batteries with mixed successful and intentionally out-of-bound goals
- eventually include closed-loop skill generation in those stress runs when a
  missing deterministic capability is the real blocker
