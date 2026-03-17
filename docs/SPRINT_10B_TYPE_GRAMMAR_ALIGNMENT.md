# Sprint 10B — Type Grammar Alignment

## Problem

A real Anthropic-planned graph used `"type": "array"` for a keywords
output field. The validator rejected it because bare `array` is not
a base type — the spec requires `array<T>` (e.g. `array<string>`).

The LLM had no way to know this because the planner prompt never
mentioned the parameterised type syntax.

## Type grammar reminder added to prompt

A new section is added to the output contract:

```
## Type grammar
Base types: string, integer, number, boolean, bytes, object
Parameterised: array<T> (e.g. array<string>), optional<T>
IMPORTANT: bare "array" is invalid — always use array<T>.
```

## How array types must be represented

- `array<string>` — valid
- `array<integer>` — valid
- `array<object>` — valid
- `array` — **invalid**, rejected by validator
- `optional<string>` — valid
- `optional<array<string>>` — valid

## Example added to prompt

The valid example now includes an output with `array<string>` type
to demonstrate the syntax by example.

## Validation error improvement

The validator error message for bare `array` or `optional` now
specifically suggests the parameterised form:

> Unknown type 'array' in field 'keywords'.
> Did you mean 'array<string>'? Array and optional types require
> a type parameter: array<T>, optional<T>.

## Regression test added

A test simulates an LLM returning `"type": "array"` in an output
field and verifies:
1. The parsed glue graph is structurally valid (parser succeeds)
2. Validation catches the bare `array` and returns a partial result
3. The validation error message mentions `array<string>`

A positive test uses `array<string>` for the same pattern and
verifies it passes validation.

## No parser-side handling

The parser does not attempt to fix `array` → `array<string>`.
That would be silent type invention. The fix is prompt-side:
teach the LLM the correct syntax so it emits valid types.

## Why minimal and safe

- Prompt change: adds ~4 lines of type grammar reference
- Validator change: improves one error message (no logic change)
- No new concepts, no architecture changes
- Regression test covers the exact real-world failure
