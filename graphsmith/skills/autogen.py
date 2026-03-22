"""Automatic skill generation for simple deterministic ops.

Generates a complete skill (YAML + Python op) from a structured spec.
Supports a narrow catalog of deterministic single-step operations.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


# ── Skill spec ─────────────────────────────────────────────────────


class SkillSpec(BaseModel):
    """Structured specification for a generated skill."""

    skill_id: str              # e.g. "text.uppercase.v1"
    op_name: str               # e.g. "text.uppercase"
    category: str              # e.g. "text", "math", "json"
    short_name: str            # e.g. "uppercase"
    human_name: str            # e.g. "Uppercase Text"
    description: str
    template_key: str          # key into _TEMPLATES catalog
    inputs: list[dict[str, str]]   # [{"name": "text", "type": "string"}]
    outputs: list[dict[str, str]]  # [{"name": "uppercased", "type": "string"}]
    config: dict[str, str] = Field(default_factory=dict)
    examples: list[dict[str, Any]] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


# ── Template catalog ───────────────────────────────────────────────

# Each template defines:
#   - keywords: phrases that match this template
#   - inputs/outputs: port definitions
#   - code: Python function body (just the return expression)
#   - examples: test cases

_TEMPLATES: dict[str, dict[str, Any]] = {
    "uppercase": {
        "keywords": ["uppercase", "upper case", "to upper", "capitalize all", "all caps"],
        "category": "text",
        "description": "Convert text to uppercase.",
        "inputs": [{"name": "text", "type": "string"}],
        "outputs": [{"name": "uppercased", "type": "string"}],
        "code_body": 'return {"uppercased": str(text).upper()}',
        "examples": [
            {"input": {"text": "hello world"}, "output": {"uppercased": "HELLO WORLD"}},
            {"input": {"text": "Foo Bar"}, "output": {"uppercased": "FOO BAR"}},
            {"input": {"text": ""}, "output": {"uppercased": ""}},
        ],
    },
    "lowercase": {
        "keywords": ["lowercase", "lower case", "to lower"],
        "category": "text",
        "description": "Convert text to lowercase.",
        "inputs": [{"name": "text", "type": "string"}],
        "outputs": [{"name": "lowercased", "type": "string"}],
        "code_body": 'return {"lowercased": str(text).lower()}',
        "examples": [
            {"input": {"text": "HELLO WORLD"}, "output": {"lowercased": "hello world"}},
            {"input": {"text": "Foo"}, "output": {"lowercased": "foo"}},
        ],
    },
    "replace": {
        "keywords": ["replace", "substitute", "swap"],
        "category": "text",
        "description": "Replace occurrences of a substring.",
        "inputs": [{"name": "text", "type": "string"}],
        "outputs": [{"name": "replaced", "type": "string"}],
        "config": {"old": "", "new": ""},
        "code_body": '''old = config.get("old", "")\n    new = config.get("new", "")\n    return {"replaced": str(text).replace(old, new)}''',
        "examples": [
            {"input": {"text": "hello world"}, "output": {"replaced": "hello world"}},
        ],
    },
    "strip_prefix": {
        "keywords": ["strip prefix", "remove prefix", "trim prefix"],
        "category": "text",
        "description": "Remove a prefix from text if present.",
        "inputs": [{"name": "text", "type": "string"}],
        "outputs": [{"name": "stripped", "type": "string"}],
        "config": {"prefix": ""},
        "code_body": '''prefix = config.get("prefix", "")\n    t = str(text)\n    return {"stripped": t[len(prefix):] if t.startswith(prefix) else t}''',
        "examples": [
            {"input": {"text": "prefix_hello"}, "output": {"stripped": "prefix_hello"}},
        ],
    },
    "strip_suffix": {
        "keywords": ["strip suffix", "remove suffix", "trim suffix"],
        "category": "text",
        "description": "Remove a suffix from text if present.",
        "inputs": [{"name": "text", "type": "string"}],
        "outputs": [{"name": "stripped", "type": "string"}],
        "config": {"suffix": ""},
        "code_body": '''suffix = config.get("suffix", "")\n    t = str(text)\n    return {"stripped": t[:-len(suffix)] if suffix and t.endswith(suffix) else t}''',
        "examples": [
            {"input": {"text": "hello_suffix"}, "output": {"stripped": "hello_suffix"}},
        ],
    },
    "contains": {
        "keywords": ["contains", "includes", "has substring", "check if"],
        "category": "text",
        "description": "Check if text contains a substring.",
        "inputs": [{"name": "text", "type": "string"}],
        "outputs": [{"name": "result", "type": "string"}],
        "config": {"substring": ""},
        "code_body": '''sub = config.get("substring", "")\n    return {"result": str(sub in str(text)).lower()}''',
        "examples": [
            {"input": {"text": "hello world"}, "output": {"result": "true"}},
        ],
    },
    "char_count": {
        "keywords": ["char count", "character count", "length", "string length", "count characters"],
        "category": "text",
        "description": "Count the number of characters in text.",
        "inputs": [{"name": "text", "type": "string"}],
        "outputs": [{"name": "count", "type": "string"}],
        "code_body": 'return {"count": str(len(str(text)))}',
        "examples": [
            {"input": {"text": "hello"}, "output": {"count": "5"}},
            {"input": {"text": ""}, "output": {"count": "0"}},
        ],
    },
    "subtract": {
        "keywords": ["subtract", "minus", "difference"],
        "category": "math",
        "description": "Subtract two numbers (a - b).",
        "inputs": [{"name": "a", "type": "string"}, {"name": "b", "type": "string"}],
        "outputs": [{"name": "result", "type": "string"}],
        "code_body": '''a_val = float(inputs.get("a", 0))\n    b_val = float(inputs.get("b", 0))\n    r = a_val - b_val\n    return {"result": str(int(r) if r == int(r) else r)}''',
        "examples": [
            {"input": {"a": "10", "b": "3"}, "output": {"result": "7"}},
            {"input": {"a": "5", "b": "8"}, "output": {"result": "-3"}},
        ],
    },
    "divide": {
        "keywords": ["divide", "division", "quotient"],
        "category": "math",
        "description": "Divide two numbers (a / b).",
        "inputs": [{"name": "a", "type": "string"}, {"name": "b", "type": "string"}],
        "outputs": [{"name": "result", "type": "string"}],
        "code_body": '''a_val = float(inputs.get("a", 0))\n    b_val = float(inputs.get("b", 0))\n    if b_val == 0:\n        from graphsmith.exceptions import OpError\n        raise OpError("math.divide: division by zero")\n    r = a_val / b_val\n    return {"result": str(int(r) if r == int(r) else r)}''',
        "examples": [
            {"input": {"a": "10", "b": "2"}, "output": {"result": "5"}},
            {"input": {"a": "7", "b": "2"}, "output": {"result": "3.5"}},
        ],
    },
    "get_key": {
        "keywords": ["get key", "json key", "json get", "get field", "access key"],
        "category": "json",
        "description": "Get a specific key from a JSON string.",
        "inputs": [{"name": "raw_json", "type": "string"}, {"name": "key", "type": "string"}],
        "outputs": [{"name": "value", "type": "string"}],
        "code_body": '''import json as _json\n    key = str(inputs.get("key", ""))\n    data = _json.loads(str(inputs.get("raw_json", "{}")))\n    return {"value": str(data.get(key, ""))}''',
        "examples": [
            {"input": {"raw_json": '{"name": "alice"}', "key": "name"}, "output": {"value": "alice"}},
        ],
    },
}

# Operations NOT supported — refuse explicitly
# Out-of-scope PHRASES (checked before template matching)
_OUT_OF_SCOPE_PHRASES = [
    "read file", "write file", "delete file", "remove file",
    "http request", "api call", "fetch url", "download",
    "shell command", "exec command", "subprocess",
    "multi-step", "autonomous agent", "recursive loop",
]
# Out-of-scope WORDS (only checked if no template matched first)
_OUT_OF_SCOPE_WORDS = {
    "network", "http", "fetch", "upload", "api",
    "install", "pip", "npm", "exec", "shell", "subprocess",
    "database", "sql", "query",
    "autonomous", "recursive",
}


# ── Intent extraction ──────────────────────────────────────────────


class AutogenError(Exception):
    """Error during automatic skill generation."""
    pass


def extract_spec(goal: str) -> SkillSpec:
    """Extract a SkillSpec from a natural language goal.

    Uses deterministic keyword matching against the template catalog.
    Raises AutogenError for out-of-scope or unrecognized requests.
    """
    goal_lower = goal.lower().strip()

    # Check out-of-scope phrases first
    for phrase in _OUT_OF_SCOPE_PHRASES:
        if phrase in goal_lower:
            raise AutogenError(
                f"Out of scope: '{phrase}' is not supported for automatic skill creation. "
                f"This prototype only supports simple deterministic text/math/JSON ops."
            )

    # Match against template catalog
    best_key: str | None = None
    best_score = 0
    for key, tmpl in _TEMPLATES.items():
        for kw in tmpl["keywords"]:
            if kw in goal_lower:
                score = len(kw)
                if score > best_score:
                    best_key = key
                    best_score = score

    if best_key is None:
        # Check out-of-scope words only when no template matched
        goal_words = set(re.findall(r"[a-z]+", goal_lower))
        blocked = goal_words & _OUT_OF_SCOPE_WORDS
        if blocked:
            raise AutogenError(
                f"Out of scope: '{', '.join(sorted(blocked))}' is not supported. "
                f"This prototype only supports simple deterministic text/math/JSON ops."
            )
        available = sorted(_TEMPLATES.keys())
        raise AutogenError(
            f"Could not match goal '{goal}' to a known template. "
            f"Supported operations: {', '.join(available)}"
        )

    return _spec_from_template(best_key, goal)


def _spec_from_template(template_key: str, goal: str) -> SkillSpec:
    """Build a SkillSpec from a matched template."""
    tmpl = _TEMPLATES[template_key]
    category = tmpl["category"]
    short_name = template_key
    op_name = f"{category}.{short_name}"
    skill_id = f"{op_name}.v1"

    return SkillSpec(
        skill_id=skill_id,
        op_name=op_name,
        category=category,
        short_name=short_name,
        human_name=short_name.replace("_", " ").title(),
        description=tmpl["description"],
        template_key=template_key,
        inputs=tmpl["inputs"],
        outputs=tmpl["outputs"],
        config=tmpl.get("config", {}),
        examples=tmpl["examples"],
        tags=[category, short_name],
    )


# ── Code generation ───────────────────────────────────────────────


def generate_op_code(spec: SkillSpec) -> str:
    """Generate Python op function code from a spec."""
    tmpl = _TEMPLATES[spec.template_key]
    code_body = tmpl["code_body"]

    # Determine input extraction
    input_names = [inp["name"] for inp in spec.inputs]
    if len(input_names) == 1 and input_names[0] == "text":
        input_extract = f'    text = inputs.get("text", "")'
    else:
        input_extract = "\n".join(
            f'    # inputs: {", ".join(input_names)}'
            for _ in [None]
        )

    func_name = spec.op_name.replace(".", "_")

    lines = [
        f'def {func_name}(config: dict, inputs: dict) -> dict:',
        f'    """{spec.description}"""',
    ]
    if len(input_names) == 1 and input_names[0] == "text":
        lines.append(f'    text = inputs.get("text", "")')
    lines.append(f'    {code_body}')

    return "\n".join(lines)


# ── File generation ───────────────────────────────────────────────


def generate_skill_files(spec: SkillSpec, output_dir: str | Path) -> Path:
    """Generate complete skill package files from a spec."""
    skill_dir = Path(output_dir) / spec.skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)

    # skill.yaml
    inputs_yaml = "\n".join(
        f"  - name: {inp['name']}\n    type: {inp['type']}\n    required: true"
        for inp in spec.inputs
    )
    outputs_yaml = "\n".join(
        f"  - name: {out['name']}\n    type: {out['type']}"
        for out in spec.outputs
    )
    tags_yaml = "\n".join(f"  - {t}" for t in spec.tags)

    (skill_dir / "skill.yaml").write_text(
        f"id: {spec.skill_id}\n"
        f"name: {spec.human_name}\n"
        f"version: 1.0.0\n"
        f"description: {spec.description}\n"
        f"\n"
        f"inputs:\n{inputs_yaml}\n"
        f"\n"
        f"outputs:\n{outputs_yaml}\n"
        f"\n"
        f"effects:\n  - pure\n"
        f"\n"
        f"tags:\n{tags_yaml}\n"
    )

    # graph.yaml
    input_name = spec.inputs[0]["name"]
    output_name = spec.outputs[0]["name"]
    edges_yaml = "\n".join(
        f"  - from: input.{inp['name']}\n    to: run.{inp['name']}"
        for inp in spec.inputs
    )

    (skill_dir / "graph.yaml").write_text(
        f"version: 1\n"
        f"\n"
        f"nodes:\n"
        f"  - id: run\n"
        f"    op: {spec.op_name}\n"
        f"\n"
        f"edges:\n{edges_yaml}\n"
        f"\n"
        f"outputs:\n"
        f"  {output_name}: run.{output_name}\n"
    )

    # examples.yaml — use yaml.dump for safe quoting
    import yaml
    examples_data = {"examples": []}
    for i, ex in enumerate(spec.examples):
        examples_data["examples"].append({
            "name": f"example_{i+1}",
            "input": {k: str(v) for k, v in ex["input"].items()},
            "expected_output": {k: str(v) for k, v in ex["output"].items()},
        })

    (skill_dir / "examples.yaml").write_text(
        yaml.dump(examples_data, default_flow_style=False, sort_keys=False)
    )

    return skill_dir


# ── Op registration (runtime) ─────────────────────────────────────


def register_generated_op(spec: SkillSpec) -> None:
    """Register the generated op in the runtime op registry.

    This makes the op available for execution without restarting.
    """
    from graphsmith.constants import PRIMITIVE_OPS
    from graphsmith.ops.registry import _PURE_OPS

    tmpl = _TEMPLATES[spec.template_key]
    code_body = tmpl["code_body"]
    input_names = [inp["name"] for inp in spec.inputs]

    # Build the function dynamically
    func_name = spec.op_name.replace(".", "_")

    if len(input_names) == 1 and input_names[0] == "text":
        exec_code = (
            f"def {func_name}(config, inputs):\n"
            f'    text = inputs.get("text", "")\n'
            f"    {code_body}\n"
        )
    else:
        exec_code = (
            f"def {func_name}(config, inputs):\n"
            f"    {code_body}\n"
        )

    namespace: dict[str, Any] = {}
    exec(exec_code, namespace)  # noqa: S102 — controlled template code only
    fn = namespace[func_name]

    _PURE_OPS[spec.op_name] = fn
    PRIMITIVE_OPS.add(spec.op_name)


# ── Validation + test execution ───────────────────────────────────


def validate_and_test(spec: SkillSpec, skill_dir: Path) -> dict[str, Any]:
    """Validate the generated skill and run example tests.

    Returns a result dict with validation/test status.
    """
    from graphsmith.exceptions import ValidationError
    from graphsmith.ops.registry import execute_op
    from graphsmith.parser import load_skill_package
    from graphsmith.validator import validate_skill_package

    result: dict[str, Any] = {
        "skill_id": spec.skill_id,
        "validation": "FAIL",
        "examples_total": 0,
        "examples_passed": 0,
        "errors": [],
    }

    # Register the op first
    try:
        register_generated_op(spec)
    except Exception as exc:
        result["errors"].append(f"Op registration failed: {exc}")
        return result

    # Validate
    try:
        pkg = load_skill_package(str(skill_dir))
        validate_skill_package(pkg)
        result["validation"] = "PASS"
    except (ValidationError, Exception) as exc:
        result["errors"].append(f"Validation: {exc}")
        return result

    # Run examples
    result["examples_total"] = len(spec.examples)
    for i, ex in enumerate(spec.examples):
        try:
            output = execute_op(spec.op_name, spec.config, ex["input"])
            if output == ex["output"]:
                result["examples_passed"] += 1
            else:
                result["errors"].append(
                    f"Example {i+1}: expected {ex['output']}, got {output}"
                )
        except Exception as exc:
            result["errors"].append(f"Example {i+1}: {exc}")

    return result


def format_result(result: dict[str, Any], skill_dir: Path) -> str:
    """Format validation/test result as human-readable text."""
    lines = [
        f"  Created: {skill_dir}",
        f"  Validation: {result['validation']}",
    ]
    if result["examples_total"] > 0:
        lines.append(
            f"  Examples: {result['examples_passed']}/{result['examples_total']} PASS"
        )
    if result["errors"]:
        lines.append("  Issues:")
        for err in result["errors"][:5]:
            lines.append(f"    - {err}")
    return "\n".join(lines)
