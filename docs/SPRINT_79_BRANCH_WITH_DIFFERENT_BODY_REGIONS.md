# Sprint 79: Branch With Different Body Regions

This sprint extends bounded branch fallback from simple conditional formatting
into a small branch-region family with distinct body skills on each arm.

What changed:

- Added a reusable sentiment-gated branch formatter builder in
  `graphsmith/skills/closed_loop.py`.
- The builder now supports:
  - no body skills on either arm (existing sentiment-prefix branch family)
  - different body skills on each arm before the shared formatter
- Added a new bounded branch-body fallback for:
  - positive branch: `text.summarize.v1`
  - negative branch: `text.extract_keywords.v1`
  - shared post-branch formatter: `text.prefix_lines.v1`
- Added a branch-region grounding check so approximate executable plans are not
  accepted if they omit required public inputs like `positive_prefix` and
  `negative_prefix`, or if they miss the canonical merge structure.

Why this matters:

- This is the first branch fallback that supports genuinely different region
  bodies rather than just conditional routing into the same formatter.
- It moves Graphsmith slightly closer to “region programming” instead of only
  linear pipelines plus local fixes.

Current scope:

- Still bounded and explicit.
- Still sentiment-gated and still single-level.
- No nested branches, no local branch synthesis, and no branch-local region
  regeneration yet.
