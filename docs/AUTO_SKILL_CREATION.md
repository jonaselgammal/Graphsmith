# Automatic Skill Creation

Graphsmith can automatically generate simple skills from natural language
descriptions, including the implementation, validation, and example tests.

## Supported skill types

Supports **deterministic, single-step** skills across 7 template families:

| Family | Templates | Description |
|--------|-----------|-------------|
| text_unary | uppercase, lowercase, trim, char_count, line_count, join | Single-input text transforms |
| text_config_predicate | starts_with, ends_with, contains | Text checks with config |
| text_config_transform | replace, strip_prefix, strip_suffix | Text transforms with config |
| math_binary | subtract, divide | Two-number arithmetic |
| math_list | min, max, median | Aggregate over number lists |
| json_accessor | get_key, keys, pretty | JSON data access |
| json_predicate | has_key | JSON property checks |

## Usage

```bash
graphsmith create-skill-from-goal "uppercase text"
```

Output:

```
  Skill: text.uppercase.v1
  Op: text.uppercase
  Description: Convert text to uppercase.
  Template: uppercase

  Created: examples/skills/text.uppercase.v1
  Validation: PASS
  Examples: 3/3 PASS

  Ready to use.
  Publish: graphsmith publish examples/skills/text.uppercase.v1 --registry $REG
```

### Dry run

Preview without generating files:

```bash
graphsmith create-skill-from-goal "subtract numbers" --dry-run
```

## What it generates

For each skill, three files are created:

- **skill.yaml** — metadata, inputs, outputs, effects, tags
- **graph.yaml** — execution graph referencing the primitive op
- **examples.yaml** — test cases with expected outputs

The primitive op implementation is registered at runtime for immediate testing.

## What it does NOT support

- Multi-step or chained skills
- Network/filesystem operations
- LLM-dependent skills
- Arbitrary code generation
- Self-modifying or autonomous behavior

Out-of-scope requests are refused with a clear message.

## How it works

1. **Intent extraction** — keyword matching against a catalog of templates
2. **Spec generation** — structured SkillSpec with inputs, outputs, examples
3. **File generation** — YAML files from the spec
4. **Op registration** — function generated from a code template, registered at runtime
5. **Validation** — standard Graphsmith validation (types, DAG, bindings)
6. **Example testing** — each example is executed and compared to expected output

## Reviewing generated skills

Generated skills are NOT auto-published. To use them:

```bash
# Review the generated files
cat examples/skills/text.uppercase.v1/skill.yaml

# Validate manually
graphsmith validate examples/skills/text.uppercase.v1

# Publish when satisfied
graphsmith publish examples/skills/text.uppercase.v1 --registry "$REG"
```

## Failure stages

When generation does not fully pass, Graphsmith now reports the stage
that failed:

- `registration` — runtime op registration failed
- `validation` — generated package failed Graphsmith validation
- `examples` — package validated, but one or more examples failed

This is intended to make battle-testing easier: failures are still
bounded, but easier to classify and debug.

## Smoke battery

For a small end-to-end regression check of the CLI flow, run:

```bash
python scripts/run_autogen_battery.py
```

See [Autogen Battery](AUTOGEN_BATTERY.md) for details.

For the bounded closed-loop CLI surface, also run:

```bash
./scripts/autogen_closed_loop_smoke.sh
```
