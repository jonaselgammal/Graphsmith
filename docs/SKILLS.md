# Skills

A skill is a reusable, typed, executable graph component. It declares inputs,
outputs, effects, and an internal execution graph built from primitive ops.

## Built-in skills

### Text
| Skill | Description | Effects |
|-------|-------------|---------|
| `text.normalize.v1` | Lowercase, trim, collapse whitespace | pure |
| `text.extract_keywords.v1` | Extract keywords via LLM | llm_inference |
| `text.summarize.v1` | Summarize text via LLM | llm_inference |
| `text.title_case.v1` | Capitalize each word | pure |
| `text.word_count.v1` | Count words | pure |
| `text.join_lines.v1` | Join lines with separator | pure |
| `text.prefix_lines.v1` | Add a prefix to each line | pure |
| `text.classify_sentiment.v1` | Classify sentiment via LLM | llm_inference |
| `text.reverse.v1` | Reverse a string | pure |
| `text.sort_lines.v1` | Sort lines alphabetically | pure |
| `text.remove_duplicates.v1` | Remove duplicate lines | pure |
| `text.split.v1` | Split text by delimiter | pure |
| `text.filter_lines.v1` | Filter lines containing a substring | pure |
| `text.regex_extract.v1` | Extract regex matches | pure |

### Math
| Skill | Description | Effects |
|-------|-------------|---------|
| `math.add.v1` | Add two numbers | pure |
| `math.multiply.v1` | Multiply two numbers | pure |
| `math.mean.v1` | Arithmetic mean of numbers | pure |

### JSON
| Skill | Description | Effects |
|-------|-------------|---------|
| `json.reshape.v1` | Select fields from JSON | pure |
| `json.extract_field.v1` | Extract a single field | pure |
| `json.pretty_print.v1` | Pretty-print JSON | pure |

## Creating a new skill

### 1. Generate scaffold

```bash
graphsmith create-skill my_domain.my_skill.v1
```

This creates:
```
examples/skills/my_domain.my_skill.v1/
  skill.yaml       # Metadata: id, inputs, outputs, effects
  graph.yaml       # Execution graph using primitive ops
  examples.yaml    # Test examples
```

### 2. Define the skill spec (`skill.yaml`)

```yaml
id: text.uppercase.v1
name: Uppercase Text
version: 1.0.0
description: Convert text to uppercase.

inputs:
  - name: text
    type: string
    required: true

outputs:
  - name: uppercased
    type: string

effects:
  - pure

tags:
  - text
```

### 3. Define the graph (`graph.yaml`)

For skills using existing primitive ops:

```yaml
version: 1

nodes:
  - id: upper
    op: text.uppercase

edges:
  - from: input.text
    to: upper.text

outputs:
  uppercased: upper.uppercased
```

### 4. Add the primitive op (if new)

If your skill needs a new op, add it in `graphsmith/ops/`:

```python
# graphsmith/ops/text_ops.py
def text_uppercase(config, inputs):
    text = inputs.get("text", "")
    return {"uppercased": str(text).upper()}
```

Register it in `graphsmith/ops/registry.py`:
```python
_PURE_OPS["text.uppercase"] = text_uppercase
```

And add to `graphsmith/constants.py`:
```python
PRIMITIVE_OPS.add("text.uppercase")
```

### 5. Validate and publish

```bash
graphsmith validate examples/skills/text.uppercase.v1
graphsmith publish examples/skills/text.uppercase.v1 --registry "$REG"
```

### 6. Use it

The planner will automatically discover published skills via the registry.

## Skill rules

- **Inputs/outputs are typed**: string, integer, number, boolean, bytes, object
- **Effects declare side effects**: pure, llm_inference, network_read, etc.
- **Graphs must be DAGs**: no cycles allowed
- **Each output must be wired**: every declared output needs a source in the graph
- **Tags help retrieval**: the planner uses tags + description for skill matching
