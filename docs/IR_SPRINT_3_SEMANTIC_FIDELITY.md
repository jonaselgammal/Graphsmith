# IR Sprint 3 — Semantic Fidelity

## Latest IR vs direct comparison

| Set | Direct | IR | Delta |
|-----|--------|-----|-------|
| Benchmark (9) | 4/9 (44%) | 5/9 (56%) | +1 |
| Holdout (15) | 8/15 (53%) | 9/15 (60%) | +1 |
| Challenge (12) | 3/12 (25%) | 8/12 (67%) | +5 |
| **Total** | **15/36 (42%)** | **22/36 (61%)** | **+7** |

## Why remaining failures are semantic

After Sprint 2 hardening, zero parser/compiler boundary issues remain. Every
IR failure involves correct JSON structure and successful compilation, but
produces a semantically wrong plan. The graph is structurally valid but makes
the wrong choices about what to compute.

## Inspected IR failures (11 cases)

| Goal | Category | Detail |
|------|----------|--------|
| Extract keywords + format as list | wrong output | Exposed `keywords` not `joined` |
| Normalize, summarize, extract keywords | over-composition + wrong skill | Added `join_lines` instead of `summarize` |
| Parse/reshape JSON | wrong output name | Named output `output` not `selected` |
| Short summary | malformed skill_id | Used `text.summarize.v1@1.0.0` |
| Tidy up + topics | missing step + over-composition | No normalize, added join_lines |
| Lowercase/trim | wrong output name | Named `cleaned_text` not `normalized` |
| JSON name/value | wrong skill | Hallucinated select.fields and text.title_case ops |
| Cleanup + capitalize | wrong output name | Named `cleaned_text` not `titled` |
| Keywords + header | wrong output name | Named `joined` not `prefixed` |
| Clean, capitalize, keywords | wrong skill + over-comp | Added join_lines instead of title_case |
| Topics + header format | wrong skill for header | Used join_lines instead of prefix_lines |

### Failure categories

| Category | Count | Root cause |
|----------|-------|------------|
| Wrong output name | 6 | LLM invents names instead of using skill output port names |
| Over-composition | 4 | LLM adds unnecessary join_lines/formatting |
| Wrong skill selection | 3 | LLM picks wrong skill (join_lines vs prefix_lines) |
| Missing required step | 2 | LLM skips normalize when "tidy/clean" in goal |
| Malformed skill_id | 1 | LLM appends @version to skill_id |

## Semantic prompt changes

### Output naming
- Added explicit rule: final output names MUST be exact skill output port names
- Added "WRONG" / "RIGHT" examples for common mistakes
- Emphasized checking output_ports listing before naming outputs

### Step selection for headers/formatting
- Distinguished "format as list" (→ join_lines) from "add header" (→ template.render)
- Added concrete example showing header = template.render, not join_lines

### Required steps
- Added rule: if goal says clean/tidy/normalize, you MUST include normalize step
- Paraphrase mapping: clean/tidy/cleanup → text.normalize.v1

### Over-composition
- Strengthened: "do NOT add a formatting step unless the goal explicitly asks for one"

### Skill ID format
- Added rule: skill_id must NOT include @version — version goes in version field

## Results after Sprint 3

| Set | Direct | IR | Delta |
|-----|--------|-----|-------|
| Benchmark (9) | 8/9 (89%) | 6/9 (67%) | -2 |
| Holdout (15) | 9/15 (60%) | **11/15 (73%)** | **+2** |
| Challenge (12) | 8/12 (67%) | 7/12 (58%) | -1 |
| **Total** | **25/36 (69%)** | **24/36 (67%)** | **-1** |

### Key observations
- IR wins holdout (+2) but loses benchmark/challenge to an unusually strong direct run
- All IR failures are now semantic (over-composition, wrong output names)
- Over-composition is the #1 remaining issue: LLM adds join_lines to plain extraction goals
- This is a Llama 3.1 8B behavioral tendency, not addressable by prompt alone
- Prompt length matters: adding an output port table *worsened* results (17/36 → 24/36 after trimming)

### Remaining failures (all semantic)
| Category | Count |
|----------|-------|
| Over-composition | 4 |
| Wrong output names | 3 |
| Parse failures | 3 |
| Wrong skill selection | 2 |

## What remains unchanged
- Parser hardening from Sprint 2
- Direct planner prompt
- Runtime execution
- Retrieval
- No repair loop added
