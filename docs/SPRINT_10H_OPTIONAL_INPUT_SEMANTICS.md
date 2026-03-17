# Sprint 10H — Optional Input Semantics

## Exact failure observed

```
FAIL: Execution failed at node 'call': Execution failed at node 'prompt':
Address 'input.max_sentences' has no value. Available: ['input.text']
```

`text.summarize.v1` declares `max_sentences` as `required: false`,
but its graph wires `input.max_sentences → prompt.max_sentences`
unconditionally. When the skill is invoked without `max_sentences`,
the runtime crashes trying to resolve the absent address.

## How optional inputs should behave

1. **Required inputs**: must be provided. Missing → fail early with
   a clear error (the pre-check from Sprint 10G).

2. **Optional inputs**: may be omitted. If an edge sources from
   `input.<name>` where `<name>` is an optional input that was not
   provided, the binding is **skipped** — the port is not included
   in `resolved_inputs` for that node.

3. **Ops handle absent ports**: `template.render` renders `{{var}}`
   as empty string if `var` is not in inputs. Other ops that require
   specific ports will fail with their own clear error if a needed
   port is missing.

## Where the fix lives

**Runtime executor** (`_execute_node`): when resolving port bindings,
check whether each address exists in the store. If absent AND the
address is `input.<name>` where `<name>` is an optional skill input,
skip the binding instead of crashing.

**Template op**: already handles absent vars by raising OpError.
Update to render absent optional vars as empty string if the
variable is simply not provided (i.e. not in `inputs` dict) —
the template still works, just with that variable blank.

**Example skill**: `text.summarize.v1`'s graph is correct as-is —
it wires the optional input, which is fine. The runtime now
handles the absent case gracefully.

## Why strict and safe

- Required inputs still fail hard
- No default values are invented
- Optional inputs are simply absent from `resolved_inputs`
- Ops decide how to handle absent ports (template renders blank,
  others may fail with their own error)
- The behavior is explicit and documented in BINDING_SEMANTICS.md
