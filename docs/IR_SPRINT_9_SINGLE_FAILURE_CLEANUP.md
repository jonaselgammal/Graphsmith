# IR Sprint 9 — Single Failure Cleanup

## Latest Claude Haiku result

| Set | Result |
|-----|--------|
| Benchmark (9) | 9/9 (100%) |
| Holdout (15) | 15/15 (100%) |
| Challenge (12) | 11/12 (92%) |
| **Total** | **35/36 (97%)** |

## The single remaining failure

**Goal**: "Parse this JSON and extract the value field"

### Artifact evidence

- **Shortlisted skills**: json.extract_field.v1, json.reshape.v1, json.pretty_print.v1, text.extract_keywords.v1
- **Decomposition**: `content_transforms: ["reshape_json"], final_output_names: ["selected"]`
- **All 3 IR candidates**: json.reshape.v1 with output `selected`
- **Expected**: json.extract_field.v1 with output `value`
- **Failed checks**: correct_skills, correct_outputs

### Root cause: decomposition maps "extract the value field" → reshape_json

The `_KEYWORD_TRANSFORMS` mapping has `{"json", "reshape", "parse json"} → "reshape_json"`
but no mapping for `extract_field`. The word "json" in the goal triggers `reshape_json`.
The decomposition prompt examples also only show `reshape_json`, not `extract_field`.

The decomposition then says `final_output_names: ["selected"]` and all 3 IR candidates
follow it — using `json.reshape.v1` instead of `json.extract_field.v1`.

### Classification: DECOMPOSITION ERROR

The decomposition lacks a transform for `extract_field` and conflates
"extract a field from JSON" with "reshape JSON". These are two distinct skills:
- `json.extract_field.v1`: extract one field → output `value` (string)
- `json.reshape.v1`: select/reshape fields → output `selected` (object)

## Fix

1. Add `extract_field` transform to decomposition keyword mapping
2. Add `extract_field` to transform→output port mapping
3. Add `extract_field` to scorer's transform→skill mapping
4. Add decomposition prompt example for extract_field
5. Make `extract_field` match more specifically than `reshape_json` for "extract field" goals

## Result after fix

| Set | Before | After |
|-----|--------|-------|
| Benchmark | 9/9 | 9/9 |
| Holdout | 15/15 | 15/15 |
| Challenge | 11/12 | **12/12** |
| **Total** | **35/36 (97%)** | **36/36 (100%)** |

**36/36 on Claude Haiku.** The extract_field decomposition fix resolved the last failure.

## What remains unchanged
- Compiler, IR prompt, runtime, retrieval, all other eval specs
