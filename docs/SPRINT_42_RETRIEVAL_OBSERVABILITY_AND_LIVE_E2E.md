# Sprint 42 — Retrieval Observability and Live E2E Checks

## Summary

This sprint hardens the real planning pipeline around candidate retrieval:

- retrieval diagnostics now distinguish an empty registry from lexical-match fallback
- CLI retrieval output now shows registry population directly
- live-provider tests assert that published skills are actually retrieved, not just that planning happens to succeed
- registry publishes are now serialized so concurrent publishers cannot clobber `index.json`

The immediate goal was to avoid a bad failure mode during live validation: mistaking an empty or stale registry path for a retrieval-quality problem.

## Why this matters

The long-term architecture depends on the planner being able to:
- inspect the available skill surface
- reason over retrieved candidates
- rewire plans around those candidates

If the diagnostics do not clearly tell us whether the registry is empty, whether retrieval matched positively, or whether the system fell back to “return something,” then live end-to-end runs are hard to trust.

That becomes more important once the skill library is larger and more dynamic.

## What changed

### 1. Retrieval diagnostics report registry state

`RetrievalDiagnostics` now includes:
- `registry_size`
- `empty_registry`
- `fallback_used`

This makes the retrieval result explain:
- whether the planner had any published skills to work with
- whether the shortlist came from actual lexical overlap
- or whether the ranked retriever returned the registry fallback set

### 2. CLI text output surfaces those diagnostics

`graphsmith plan --show-retrieval` now prints:
- registry size
- an explicit empty-registry note
- an explicit fallback note when no positive lexical matches were found

This turns a previously ambiguous live run into something that is inspectable from the CLI alone.

### 3. Live provider tests now verify retrieved candidates

The live-provider suite already validated that a real provider could produce a plan.
This sprint makes that stricter by also asserting that:
- retrieval metadata is present
- the registry is non-empty
- at least one candidate was shortlisted
- the expected published skill appears in that shortlist

That closes the gap between “the model produced a graph” and “the retrieval layer was actually functioning.”

### 4. Registry publish is now safe under concurrent writers

During live verification, publishing multiple skills to the same temp registry via parallel CLI commands exposed a real bug:
- each publisher loaded the old `index.json`
- each appended its own entry
- the last writer won, dropping earlier entries

`LocalRegistry.publish()` now takes a filesystem lock around the load/copy/save sequence so separate CLI processes serialize correctly.

There is also a regression test that forces concurrent publishes and asserts that all entries survive.

## Validation

Validated in the `graphsmith` conda env with:

```bash
conda run -n graphsmith pytest tests/test_retrieval_diagnostics.py tests/test_planner_parser.py tests/test_live_providers.py -q
conda run -n graphsmith python -m compileall graphsmith
```

Also rerun through the real CLI/live-provider path after publishing example skills to a temp registry:

```bash
conda run -n graphsmith graphsmith publish examples/skills/text.normalize.v1 --registry /tmp/graphsmith-live-reg-real
conda run -n graphsmith graphsmith publish examples/skills/text.title_case.v1 --registry /tmp/graphsmith-live-reg-real
conda run -n graphsmith graphsmith publish examples/skills/text.word_count.v1 --registry /tmp/graphsmith-live-reg-real
conda run -n graphsmith graphsmith plan "Clean up this text and capitalize each word" --backend ir --provider anthropic --model claude-sonnet-4-20250514 --registry /tmp/graphsmith-live-reg-real --show-retrieval
conda run -n graphsmith graphsmith plan-and-run "Clean up this text and capitalize each word" --backend ir --provider anthropic --model claude-sonnet-4-20250514 --registry /tmp/graphsmith-live-reg-real --input '{"text":"   hello WORLD   "}' --output-format json
```

## Result

The retrieval subsystem itself did not need a ranking rewrite.
The live issue was diagnostic ambiguity.

After this sprint:
- empty registries are visible
- fallback retrieval is visible
- live pipeline tests now verify that retrieval participates in successful planning
- concurrent skill publishing no longer corrupts the registry index

## Next step

The next useful step is still structural repair/local replanning:
- classify failures at the block/subgraph level
- patch only the failing branch or loop body
- reuse retrieval and trace evidence to repair locally instead of regenerating the whole graph
