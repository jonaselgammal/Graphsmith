# Sprint 39 — UI Scroll and IR-Oriented CLI Defaults

## Scope
- Fix the graph inspector so tall graphs can be viewed fully
- Start IR path consolidation at the CLI surface without breaking
  offline/mock workflows

## UI issue

The inspector rendered deeper graphs below the viewport but the
right-hand pane could not scroll. The graph SVG was effectively sized
to the visible viewport, and the canvas container hid overflow.

## UI changes

### Canvas scroll
- Make the graph canvas scrollable
- Keep the status bar visible with sticky positioning

### SVG sizing
- Compute SVG height from the rendered graph depth
- Set `height` and `viewBox` explicitly so lower nodes remain reachable

## CLI changes

### Default backend mode
- `plan`, `plan-and-run`, and `eval-planner` now default to
  `--backend auto` instead of `mock`

### Auto resolution
- `auto` resolves to `ir` when the user clearly intends model-backed
  planning:
  - `--mock-llm`
  - non-`echo` provider
  - explicit model
  - explicit base URL
- Otherwise `auto` resolves to `mock` to preserve current offline CLI
  behavior

## Why this scope is narrow

This does not remove the direct LLM backend or change planner internals.
It only moves the user-facing CLI one step closer to the repo's actual
center of gravity: IR planning as the preferred model-backed path.

## Validation
- Python compile check passed
- Focused pytest run could not be executed in the current shell because
  the active interpreter was not using the project environment and was
  missing package/test dependencies

## What remains unchanged
- Retrieval logic
- Planner prompts
- Runtime, validator, registry
- Public docs nav
- Release process
