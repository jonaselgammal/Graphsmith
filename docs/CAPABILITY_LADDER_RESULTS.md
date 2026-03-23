# Capability Ladder Results

Staged evaluation of Graphsmith's current capability envelope, from simple
single-skill tasks to multi-step compositions with generated skills.

## Setup

- **Evaluation mode**: deterministic (mock planner, template-based skill generation)
- **Tasks**: 18 across 5 levels
- **Closed-loop generation**: enabled for levels 3-5

## Results by level

| Level | Description | Tasks | Passed | Rate |
|-------|-------------|-------|--------|------|
| 1 | Single existing skill | 4 | 4 | 100% |
| 2 | Multi-skill composition | 4 | 4 | 100% |
| 3 | One missing skill (closed-loop) | 6 | 6 | 100% |
| 4 | Multi-step with generated skill | 2 | 2 | 100% |
| 5 | Numeric stress tests | 2 | 2 | 100% |
| **Total** | | **18** | **18** | **100%** |

## Closed-loop skill generation

| Metric | Value |
|--------|-------|
| Tasks requiring generation | 10 |
| Successful generations | 10 |
| Generation failures | 0 |
| Validation failures | 0 |
| Example test failures | 0 |

### Generated skills used

| Skill | Tasks |
|-------|-------|
| math.median.v1 | L3-01, L4-02 |
| text.uppercase.v1 | L3-02, L4-01 |
| text.trim.v1 | L3-03 |
| math.min.v1 | L3-04 |
| math.max.v1 | L3-05 |
| math.subtract.v1 | L3-06, L5-02 |
| math.divide.v1 | L5-01 |

## Example: successful closed-loop recovery

**Task L3-01**: "Compute the median of these numbers"

1. Input: `values = "3\n1\n2"`
2. No `math.median.v1` in skill registry
3. Closed loop detects missing skill via template matching
4. Generates `math.median.v1` (math_list family)
5. Validation: PASS, Examples: 2/2 PASS
6. Publishes to temporary registry
7. Output: `{"result": "2"}`

## Example: multi-step with generated skill

**Task L4-01**: "Normalize this text and then uppercase it"

1. Input: `text = "  Hello   World  "`
2. `text.normalize.v1` exists, `text.uppercase.v1` does not
3. Generates `text.uppercase.v1` (text_unary family)
4. Two-step plan: normalize → uppercase
5. Expected output names: `["uppercased"]`

## Current capability envelope

### What works reliably

- Single-step tasks with existing skills (text, math, JSON)
- Multi-skill compositions up to 3-4 steps
- Closed-loop generation for deterministic single-step skills
- Numeric operations: add, subtract, multiply, divide, mean, median, min, max
- Text transforms: normalize, word count, title case, keyword extraction
- Generated skills integrate into multi-step plans

### What the system cannot do yet

- **Multi-step skill generation**: cannot generate a skill that itself requires
  multiple nodes or other skills
- **LLM-dependent skill generation**: cannot auto-generate skills that call LLMs
- **Open-ended tasks**: goals that don't map to a known template family
- **Repair from partial failures**: if a generated skill is wrong, no retry loop
- **Learned planning**: all generation uses deterministic templates, not learned models

## Failure categories observed

None in this campaign. The deterministic harness validates all templates before use.

In live LLM-based planning (not measured here), expected failures would include:
- `wrong_output_names`: LLM uses non-standard port names
- `wrong_skills`: LLM picks wrong skill for the goal
- `parse_error`: LLM output cannot be parsed as IR

## Conclusion

Graphsmith's current deterministic pipeline + closed-loop generation covers a
useful range of simple to moderate tasks. The template-based skill generation
is 100% reliable within its scope. The bottleneck for broader usefulness is:

1. **Template catalog coverage** — only 21 templates exist
2. **LLM planning quality** — not measured in this deterministic campaign
3. **Composition depth** — untested beyond 3-4 steps
4. **Non-template skills** — anything outside the catalog requires manual creation

Next steps would be:
- Run the ladder with live LLM planning (Claude Haiku + Llama 3.1 8B)
- Extend the template catalog for common operations
- Add composition stress tests beyond 4 steps
