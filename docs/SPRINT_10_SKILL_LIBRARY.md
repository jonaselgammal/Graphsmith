# Sprint 10 — Skill Library and Multi-Skill Composition

## New example skills

| Skill ID | Role | Ops used | Input | Output |
|----------|------|----------|-------|--------|
| `text.normalize.v1` | Text cleanup (lowercase, strip) | `template.render` | `text` | `normalized` |
| `text.extract_keywords.v1` | Keyword extraction via LLM | `template.render` → `llm.generate` | `text` | `keywords` |
| `json.reshape.v1` | Select and rename JSON fields | `json.parse` → `select.fields` | `raw_json`, `fields` | `selected` |
| `text.join_lines.v1` | Join array of strings into text | `template.render` | `lines`, `separator` | `joined` |

## Why these skills

- **text.normalize.v1** — pure, deterministic, no LLM. Tests the
  simplest composable unit. Good first step in a pipeline.
- **text.extract_keywords.v1** — uses `llm.generate`. Requires mock
  LLM for testing. Natural second step after normalization.
- **json.reshape.v1** — pure, uses `json.parse` + `select.fields`.
  Exercises the data-transformation path. Different shape from text skills.
- **text.join_lines.v1** — pure, takes an array + separator. Tests
  array-to-string conversion. Useful as a final formatting step.

## Composition roles

```
normalize → extract_keywords    (text cleanup → LLM extraction)
json.reshape → text.join_lines  (data selection → formatting)
normalize → summarize           (text cleanup → LLM summarization)
```

These chains require different input/output wiring patterns, exercising
the binding semantics across varied shapes.

## Multi-skill workflows now possible

1. **Normalize-then-summarize**: `text.normalize.v1` → `text.summarize.v1`
2. **Normalize-then-extract**: `text.normalize.v1` → `text.extract_keywords.v1`
3. **Reshape-then-join**: `json.reshape.v1` → `text.join_lines.v1`

## Publish-time dependency warnings

`LocalRegistry.publish()` now emits warnings (returned as a list)
when a skill declares dependencies that are not present in the
registry. This is advisory only — publish still succeeds.

## Explicit limitations

- New skills are deliberately simple (1–2 nodes each)
- text.normalize.v1 uses template.render for normalization, not
  a real NLP normalizer
- text.join_lines.v1 expects a pre-serialized separator string
- No skill versioning beyond v1/1.0.0 in examples
- Multi-skill tests use mock LLM provider throughout
