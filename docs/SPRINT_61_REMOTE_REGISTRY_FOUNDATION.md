# Sprint 61: Remote Registry Foundation

This sprint adds the contract and integration layer for a future shared
Graphsmith skill repository.

## What landed

- `RegistryBackend` protocol for local, remote, and aggregate registries
- `FileRemoteRegistry` as a file-backed mock remote implementation
- `AggregatedRegistry` that merges local and remote registries
- provenance-bearing `IndexEntry` metadata
- CLI support for `--remote-registry`
- planner, eval, and closed-loop paths updated to accept registry backends
- frontier eval seeding changed to replay fetched packages instead of copying a
  local registry directory, so aggregated registries work correctly there too

## Validation

Validated in the `graphsmith` conda env with:

- `conda run -n graphsmith pytest tests/test_registry.py tests/test_cli.py tests/test_retrieval_diagnostics.py tests/test_frontier_eval.py -q`
- `95 passed`
- `conda run -n graphsmith python -m compileall graphsmith`

## What this enables next

- planner-visible provenance and trust-aware retrieval
- mock remote publishing/fetch flows in tests
- a future real remote registry implementation without another planner-wide
  refactor

## What it does not solve yet

- no network service
- no remote auth
- no trust-based ranking policy
- no conflict or cache invalidation strategy beyond local-preferred merge
