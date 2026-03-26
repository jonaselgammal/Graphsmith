# Sprint 64: Remote Cache And Auth

This sprint adds the next practical layer for the remote registry path:

- client-side remote cache
- authenticated remote publish
- CLI support for remote publishing

## What landed

- `RemoteRegistryClient` now caches:
  - manifests
  - exact search responses
  - fetched package files
- cached fetch/search data is used as a fallback when the remote request fails
- `graphsmith remote-publish` publishes to HTTP or file-backed remotes
- HTTP remote publish uses bearer-token auth
- CLI registry creation now reads:
  - `GRAPHSMITH_REMOTE_TOKEN`
  - `GRAPHSMITH_REMOTE_CACHE`

## Validation

Validated in the `graphsmith` conda env with:

- `conda run -n graphsmith pytest tests/test_registry.py tests/test_cli.py -q`
- `82 passed`
- `conda run -n graphsmith pytest tests/test_retrieval_diagnostics.py tests/test_frontier_eval.py -q`
- `23 passed`
- `conda run -n graphsmith python -m compileall graphsmith`

## Current boundary

The remote path now has:

- a file-backed remote mock
- an HTTP client boundary
- mock HTTP transport coverage
- authenticated publish
- offline-tolerant cached reads

It still does not have:

- a real hosted service
- persistent shared database/object-store backing
- stronger auth beyond bearer tokens
- trust-aware ranking or moderation workflows
