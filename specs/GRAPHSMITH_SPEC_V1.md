# Graphsmith Spec v1

## Package format

A skill package is a directory containing:
- `skill.yaml`
- `graph.yaml`
- `examples.yaml`
- optional `README.md`

## `skill.yaml`

Required fields:
- `id`
- `name`
- `version`
- `description`
- `inputs`
- `outputs`
- `effects`

Optional fields:
- `preconditions`
- `postconditions`
- `dependencies`
- `tags`
- `quality`
- `authors`
- `license`
- `homepage`

### Example

```yaml
id: text.summarize.v1
name: Summarize Text
version: 1.0.0
description: Summarize a text into a short paragraph.

inputs:
  - name: text
    type: string
    required: true
  - name: max_sentences
    type: integer
    required: false

outputs:
  - name: summary
    type: string

effects:
  - llm_inference

preconditions:
  - "len(text) > 0"

postconditions:
  - "isinstance(summary, str)"

dependencies:
  - llm.generate

tags:
  - text
  - summarization
```

## `graph.yaml`

Fields:
- `version`
- `nodes`
- `edges`
- `outputs`

### Nodes

Each node has:
- `id`
- `op`
- optional `inputs`
- optional `config`
- optional `when`
- optional `retry`
- optional `timeout_ms`

### Edges

Each edge has:
- `from`
- `to`

Addressing form:
- `input.<name>`
- `<node_id>.<port>`
- `output.<name>` only in final output mapping

### Outputs

A map from output names to source addresses.

### Example

```yaml
version: 1

nodes:
  - id: prompt
    op: template.render
    config:
      template: "Summarize the following text in {{max_sentences}} sentences:\n{{text}}"

  - id: summarize
    op: llm.generate
    inputs:
      prompt: prompt.rendered

edges:
  - from: input.text
    to: prompt.text
  - from: input.max_sentences
    to: prompt.max_sentences

outputs:
  summary: summarize.text
```

## `examples.yaml`

Contains input/output examples and optional benchmark cases.

```yaml
examples:
  - name: simple
    input:
      text: "Long text here"
      max_sentences: 2
    expected_output:
      summary: "Expected style only; exact text may vary"
```

## Primitive ops in v1

- `template.render`
- `json.parse`
- `select.fields`
- `array.map`
- `array.filter`
- `branch.if`
- `fallback.try`
- `parallel.map`
- `assert.check`
- `llm.generate`
- `llm.extract`
- `skill.invoke`

## Type grammar

Base:
- string
- integer
- number
- boolean
- bytes
- object
- array<T>
- optional<T>

Structured object form:
```yaml
type: object
schema:
  title: string
  url: string
  score: number
```

## Effect semantics

Effects are declarative and used for:
- compatibility
- scheduling
- cacheability
- policy checks

Declared vocabulary:
- pure
- llm_inference
- network_read
- network_write
- filesystem_read
- filesystem_write
- memory_read
- memory_write

## Constraints

- graphs must be DAGs in v1
- no unbounded loops
- all node IDs unique
- all edges must reference valid addresses
- all required skill inputs must be satisfiable
- all outputs must be mapped
