# Closed-Loop Skill Generation

Graphsmith can recover from a missing simple skill by generating it,
validating it, and replanning — all in one bounded loop.

## How it works

```
1. Plan with current skills
2. Plan fails → detect missing skill
3. Generate candidate skill (deterministic template)
4. Validate + run examples
5. Ask user to confirm
6. Publish to temporary registry
7. Replan with new skill available
```

## Supported scope

This prototype handles **one missing deterministic single-step skill** per task.

Supported families:
- Text: uppercase, lowercase, trim, char_count, line_count, join, starts_with, ends_with, contains, replace, strip_prefix, strip_suffix
- Math: subtract, divide, min, max, median
- JSON: get_key, has_key, keys, pretty

## Usage

### CLI command

```bash
graphsmith solve "compute the median of numbers"
```

With auto-approve (skip confirmation):
```bash
graphsmith solve "compute the median of numbers" --auto-approve
```

### Example output

```
  Solving: compute the median of numbers

  Closed-Loop Result
  ----------------------------------------
  Initial plan: failure
  Missing skill detected: No candidate used math.median.v1 and goal matches template 'median'
  Generated: math.median.v1 (math_list)
  Validation: PASS
  Examples: 2/2 PASS
  Replan: success

  Plan delta:
    Before: (no valid plan)
    After: median
    Outputs: result

  ✔ SUCCESS
```

## Missing-skill detection

Detection is narrow and explicit:

1. Initial planning must fail (no valid plan produced)
2. Goal must match an autogen template keyword
3. The matching skill must not already be in candidate plans

If any condition is not met, no generation is attempted.

## Safety constraints

- Only **one** generated skill per attempt
- Only **deterministic single-step** skills (from template catalog)
- No auto-publish to permanent registry by default
- **User confirmation required** unless `--auto-approve` is passed
- Generated skill files are kept for review
- Out-of-scope requests are refused
- If validation or examples fail, the loop aborts

## Why a loop stops

Closed-loop generation is intentionally bounded, so every exit is
explicit. Common stop reasons are:

- initial plan already succeeded
- no missing skill was detected
- generated skill failed validation
- generated skill failed example tests
- waiting for user confirmation
- user declined confirmation
- publish failed
- replan failed after publication

## Limitations

- Detection relies on keyword matching, not deep semantic analysis
- Only covers the 21 template families in the autogen catalog
- Cannot generate multi-step or LLM-dependent skills
- Cannot handle cases where multiple skills are missing
- Does not learn from failures

## Files

| Module | Purpose |
|--------|---------|
| `graphsmith/skills/closed_loop.py` | Orchestrator + detection + display |
| `graphsmith/skills/autogen.py` | Template catalog + generation + validation |
| `graphsmith/cli/main.py` | `graphsmith solve` command |
