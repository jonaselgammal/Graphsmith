"""Automatic skill generation for simple deterministic ops.

Generates a complete skill (YAML + Python op) from a structured spec.
Uses template families to support a broad set of deterministic single-step ops
without per-operation hardcoding.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


# ── Skill spec ─────────────────────────────────────────────────────


class SkillSpec(BaseModel):
    """Structured specification for a generated skill."""

    skill_id: str
    op_name: str
    category: str
    short_name: str
    human_name: str
    description: str
    template_key: str
    family: str = ""
    inputs: list[dict[str, str]]
    outputs: list[dict[str, str]]
    config: dict[str, str] = Field(default_factory=dict)
    examples: list[dict[str, Any]] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


# ── Template families ──────────────────────────────────────────────
# Each family defines a code pattern. Individual ops only specify
# the operation-specific expression, not the full function body.

_TEXT_UNARY_INPUT = [{"name": "text", "type": "string"}]
_MATH_BINARY_INPUT = [{"name": "a", "type": "string"}, {"name": "b", "type": "string"}]
_MATH_LIST_INPUT = [{"name": "values", "type": "string"}]
_JSON_INPUT = [{"name": "raw_json", "type": "string"}]
_JSON_KEY_INPUT = [{"name": "raw_json", "type": "string"}, {"name": "key", "type": "string"}]


def _text_unary_code(expr: str, out_name: str) -> str:
    """Code body for a unary text transform: text → result."""
    return f'return {{"{out_name}": {expr}}}'


def _math_binary_code(operator: str, out_name: str = "result") -> str:
    """Code body for a binary math op: a, b → result."""
    return (
        f'a_val = float(inputs.get("a", 0))\n'
        f'    b_val = float(inputs.get("b", 0))\n'
        f'    r = a_val {operator} b_val\n'
        f'    return {{"{out_name}": str(int(r) if r == int(r) else r)}}'
    )


def _math_list_code(func: str, out_name: str = "result") -> str:
    """Code body for a list-of-numbers math op."""
    return (
        f'parts = [p.strip() for p in str(inputs.get("values", "")).split("\\n") if p.strip()]\n'
        f'    nums = [float(p) for p in parts]\n'
        f'    if not nums:\n'
        f'        from graphsmith.exceptions import OpError\n'
        f'        raise OpError("math.{func}: no numbers")\n'
        f'    r = {func}(nums)\n'
        f'    return {{"{out_name}": str(int(r) if r == int(r) else r)}}'
    )


# ── Template catalog ──────────────────────────────────────────────
# Each entry has: keywords, category, description, family, inputs,
# outputs, code_body, examples. Families reduce repetition.

_TEMPLATES: dict[str, dict[str, Any]] = {
    # ── Text unary transforms ─────────────────────────────────────
    "uppercase": {
        "keywords": ["uppercase", "upper case", "to upper", "all caps"],
        "category": "text", "family": "text_unary",
        "description": "Convert text to uppercase.",
        "inputs": _TEXT_UNARY_INPUT,
        "outputs": [{"name": "uppercased", "type": "string"}],
        "code_body": _text_unary_code("str(text).upper()", "uppercased"),
        "examples": [
            {"input": {"text": "hello world"}, "output": {"uppercased": "HELLO WORLD"}},
            {"input": {"text": "Foo Bar"}, "output": {"uppercased": "FOO BAR"}},
            {"input": {"text": ""}, "output": {"uppercased": ""}},
        ],
    },
    "lowercase": {
        "keywords": ["lowercase", "lower case", "to lower"],
        "category": "text", "family": "text_unary",
        "description": "Convert text to lowercase.",
        "inputs": _TEXT_UNARY_INPUT,
        "outputs": [{"name": "lowercased", "type": "string"}],
        "code_body": _text_unary_code("str(text).lower()", "lowercased"),
        "examples": [
            {"input": {"text": "HELLO WORLD"}, "output": {"lowercased": "hello world"}},
            {"input": {"text": "Foo"}, "output": {"lowercased": "foo"}},
        ],
    },
    "trim": {
        "keywords": ["trim", "strip whitespace", "strip text"],
        "category": "text", "family": "text_unary",
        "description": "Strip leading and trailing whitespace.",
        "inputs": _TEXT_UNARY_INPUT,
        "outputs": [{"name": "trimmed", "type": "string"}],
        "code_body": _text_unary_code("str(text).strip()", "trimmed"),
        "examples": [
            {"input": {"text": "  hello  "}, "output": {"trimmed": "hello"}},
            {"input": {"text": "no spaces"}, "output": {"trimmed": "no spaces"}},
        ],
    },
    "char_count": {
        "keywords": ["char count", "character count", "length", "string length", "count characters"],
        "category": "text", "family": "text_unary",
        "description": "Count the number of characters in text.",
        "inputs": _TEXT_UNARY_INPUT,
        "outputs": [{"name": "count", "type": "string"}],
        "code_body": _text_unary_code("str(len(str(text)))", "count"),
        "examples": [
            {"input": {"text": "hello"}, "output": {"count": "5"}},
            {"input": {"text": ""}, "output": {"count": "0"}},
        ],
    },
    "line_count": {
        "keywords": ["line count", "count lines", "number of lines"],
        "category": "text", "family": "text_unary",
        "description": "Count the number of lines in text.",
        "inputs": _TEXT_UNARY_INPUT,
        "outputs": [{"name": "count", "type": "string"}],
        "code_body": _text_unary_code('str(len(str(text).splitlines())) if text else "0"', "count"),
        "examples": [
            {"input": {"text": "a\nb\nc"}, "output": {"count": "3"}},
            {"input": {"text": "single"}, "output": {"count": "1"}},
        ],
    },
    "join": {
        "keywords": ["join lines", "join text", "concatenate lines"],
        "category": "text", "family": "text_unary",
        "description": "Join lines into a single space-separated string.",
        "inputs": _TEXT_UNARY_INPUT,
        "outputs": [{"name": "joined", "type": "string"}],
        "code_body": _text_unary_code('" ".join(str(text).splitlines())', "joined"),
        "examples": [
            {"input": {"text": "hello\nworld"}, "output": {"joined": "hello world"}},
        ],
    },
    # ── Text predicates ───────────────────────────────────────────
    "starts_with": {
        "keywords": ["starts with", "begins with", "start with"],
        "category": "text", "family": "text_config_predicate",
        "description": "Check if text starts with a prefix.",
        "inputs": _TEXT_UNARY_INPUT,
        "outputs": [{"name": "result", "type": "string"}],
        "config": {"prefix": ""},
        "code_body": 'prefix = config.get("prefix", "")\n    return {"result": str(str(text).startswith(prefix)).lower()}',
        "examples": [
            {"input": {"text": "hello world"}, "output": {"result": "true"}},
        ],
    },
    "ends_with": {
        "keywords": ["ends with", "end with"],
        "category": "text", "family": "text_config_predicate",
        "description": "Check if text ends with a suffix.",
        "inputs": _TEXT_UNARY_INPUT,
        "outputs": [{"name": "result", "type": "string"}],
        "config": {"suffix": ""},
        "code_body": 'suffix = config.get("suffix", "")\n    return {"result": str(str(text).endswith(suffix)).lower()}',
        "examples": [
            {"input": {"text": "hello world"}, "output": {"result": "true"}},
        ],
    },
    "contains": {
        "keywords": ["contains", "includes", "has substring"],
        "category": "text", "family": "text_config_predicate",
        "description": "Check if text contains a substring.",
        "inputs": _TEXT_UNARY_INPUT,
        "outputs": [{"name": "result", "type": "string"}],
        "config": {"substring": ""},
        "code_body": 'sub = config.get("substring", "")\n    return {"result": str(sub in str(text)).lower()}',
        "examples": [
            {"input": {"text": "hello world"}, "output": {"result": "true"}},
        ],
    },
    # ── Text with config ──────────────────────────────────────────
    "replace": {
        "keywords": ["replace", "substitute"],
        "category": "text", "family": "text_config_transform",
        "description": "Replace occurrences of a substring.",
        "inputs": _TEXT_UNARY_INPUT,
        "outputs": [{"name": "replaced", "type": "string"}],
        "config": {"old": "", "new": ""},
        "code_body": 'old = config.get("old", "")\n    new = config.get("new", "")\n    return {"replaced": str(text).replace(old, new)}',
        "examples": [
            {"input": {"text": "hello world"}, "output": {"replaced": "hello world"}},
        ],
    },
    "strip_prefix": {
        "keywords": ["strip prefix", "remove prefix", "trim prefix"],
        "category": "text", "family": "text_config_transform",
        "description": "Remove a prefix from text if present.",
        "inputs": _TEXT_UNARY_INPUT,
        "outputs": [{"name": "stripped", "type": "string"}],
        "config": {"prefix": ""},
        "code_body": 'prefix = config.get("prefix", "")\n    t = str(text)\n    return {"stripped": t[len(prefix):] if t.startswith(prefix) else t}',
        "examples": [
            {"input": {"text": "prefix_hello"}, "output": {"stripped": "prefix_hello"}},
        ],
    },
    "strip_suffix": {
        "keywords": ["strip suffix", "remove suffix", "trim suffix"],
        "category": "text", "family": "text_config_transform",
        "description": "Remove a suffix from text if present.",
        "inputs": _TEXT_UNARY_INPUT,
        "outputs": [{"name": "stripped", "type": "string"}],
        "config": {"suffix": ""},
        "code_body": 'suffix = config.get("suffix", "")\n    t = str(text)\n    return {"stripped": t[:-len(suffix)] if suffix and t.endswith(suffix) else t}',
        "examples": [
            {"input": {"text": "hello_suffix"}, "output": {"stripped": "hello_suffix"}},
        ],
    },
    # ── Math binary ───────────────────────────────────────────────
    "subtract": {
        "keywords": ["subtract", "minus", "difference"],
        "category": "math", "family": "math_binary",
        "description": "Subtract two numbers (a - b).",
        "inputs": _MATH_BINARY_INPUT,
        "outputs": [{"name": "result", "type": "string"}],
        "code_body": _math_binary_code("-"),
        "examples": [
            {"input": {"a": "10", "b": "3"}, "output": {"result": "7"}},
            {"input": {"a": "5", "b": "8"}, "output": {"result": "-3"}},
        ],
    },
    "divide": {
        "keywords": ["divide", "division", "quotient"],
        "category": "math", "family": "math_binary",
        "description": "Divide two numbers (a / b).",
        "inputs": _MATH_BINARY_INPUT,
        "outputs": [{"name": "result", "type": "string"}],
        "code_body": (
            'a_val = float(inputs.get("a", 0))\n'
            '    b_val = float(inputs.get("b", 0))\n'
            '    if b_val == 0:\n'
            '        from graphsmith.exceptions import OpError\n'
            '        raise OpError("division by zero")\n'
            '    r = a_val / b_val\n'
            '    return {"result": str(int(r) if r == int(r) else r)}'
        ),
        "examples": [
            {"input": {"a": "10", "b": "2"}, "output": {"result": "5"}},
            {"input": {"a": "7", "b": "2"}, "output": {"result": "3.5"}},
        ],
    },
    # ── Math list ─────────────────────────────────────────────────
    "min": {
        "keywords": ["minimum", "min of", "smallest"],
        "category": "math", "family": "math_list",
        "description": "Find the minimum of newline-separated numbers.",
        "inputs": _MATH_LIST_INPUT,
        "outputs": [{"name": "result", "type": "string"}],
        "code_body": _math_list_code("min"),
        "examples": [
            {"input": {"values": "3\n1\n2"}, "output": {"result": "1"}},
        ],
    },
    "max": {
        "keywords": ["maximum", "max of", "largest"],
        "category": "math", "family": "math_list",
        "description": "Find the maximum of newline-separated numbers.",
        "inputs": _MATH_LIST_INPUT,
        "outputs": [{"name": "result", "type": "string"}],
        "code_body": _math_list_code("max"),
        "examples": [
            {"input": {"values": "3\n1\n2"}, "output": {"result": "3"}},
        ],
    },
    "median": {
        "keywords": ["median", "middle value", "middle number"],
        "category": "math", "family": "math_list",
        "description": "Find the median of newline-separated numbers.",
        "inputs": _MATH_LIST_INPUT,
        "outputs": [{"name": "result", "type": "string"}],
        "code_body": (
            'parts = [p.strip() for p in str(inputs.get("values", "")).split("\\n") if p.strip()]\n'
            '    nums = sorted(float(p) for p in parts)\n'
            '    if not nums:\n'
            '        from graphsmith.exceptions import OpError\n'
            '        raise OpError("math.median: no numbers")\n'
            '    n = len(nums)\n'
            '    r = nums[n // 2] if n % 2 else (nums[n // 2 - 1] + nums[n // 2]) / 2\n'
            '    return {"result": str(int(r) if r == int(r) else r)}'
        ),
        "examples": [
            {"input": {"values": "3\n1\n2"}, "output": {"result": "2"}},
            {"input": {"values": "1\n2\n3\n4"}, "output": {"result": "2.5"}},
        ],
    },
    # ── JSON ──────────────────────────────────────────────────────
    "get_key": {
        "keywords": ["get key", "json key", "json get", "get field", "access key"],
        "category": "json", "family": "json_accessor",
        "description": "Get a specific key from a JSON string.",
        "inputs": _JSON_KEY_INPUT,
        "outputs": [{"name": "value", "type": "string"}],
        "code_body": (
            'import json as _json\n'
            '    key = str(inputs.get("key", ""))\n'
            '    data = _json.loads(str(inputs.get("raw_json", "{}")))\n'
            '    return {"value": str(data.get(key, ""))}'
        ),
        "examples": [
            {"input": {"raw_json": '{"name": "alice"}', "key": "name"}, "output": {"value": "alice"}},
        ],
    },
    "has_key": {
        "keywords": ["has key", "key exists", "json has", "check key"],
        "category": "json", "family": "json_predicate",
        "description": "Check if a JSON object contains a key.",
        "inputs": _JSON_KEY_INPUT,
        "outputs": [{"name": "result", "type": "string"}],
        "code_body": (
            'import json as _json\n'
            '    key = str(inputs.get("key", ""))\n'
            '    data = _json.loads(str(inputs.get("raw_json", "{}")))\n'
            '    return {"result": str(key in data).lower()}'
        ),
        "examples": [
            {"input": {"raw_json": '{"name": "alice"}', "key": "name"}, "output": {"result": "true"}},
            {"input": {"raw_json": '{"name": "alice"}', "key": "age"}, "output": {"result": "false"}},
        ],
    },
    "keys": {
        "keywords": ["json keys", "list keys", "get keys", "object keys"],
        "category": "json", "family": "json_accessor",
        "description": "List all keys in a JSON object.",
        "inputs": _JSON_INPUT,
        "outputs": [{"name": "keys", "type": "string"}],
        "code_body": (
            'import json as _json\n'
            '    data = _json.loads(str(inputs.get("raw_json", "{}")))\n'
            '    return {"keys": "\\n".join(str(k) for k in data.keys())}'
        ),
        "examples": [
            {"input": {"raw_json": '{"a": 1, "b": 2}'}, "output": {"keys": "a\nb"}},
        ],
    },
    "pretty": {
        "keywords": ["pretty print json", "format json", "json pretty", "beautify json"],
        "category": "json", "family": "json_accessor",
        "description": "Pretty-print a JSON string.",
        "inputs": _JSON_INPUT,
        "outputs": [{"name": "formatted", "type": "string"}],
        "code_body": (
            'import json as _json\n'
            '    data = _json.loads(str(inputs.get("raw_json", "{}")))\n'
            '    return {"formatted": _json.dumps(data, indent=2)}'
        ),
        "examples": [
            {"input": {"raw_json": '{"a":1}'}, "output": {"formatted": '{\n  "a": 1\n}'}},
        ],
    },
}

# ── Safety: out-of-scope checks ──────────────────────────────────

_OUT_OF_SCOPE_PHRASES = [
    "read file", "write file", "delete file", "remove file",
    "http request", "api call", "fetch url", "download",
    "shell command", "exec command", "subprocess",
    "multi-step", "autonomous agent", "recursive loop",
]
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

    # Check out-of-scope phrases
    for phrase in _OUT_OF_SCOPE_PHRASES:
        if phrase in goal_lower:
            raise AutogenError(
                f"Out of scope: '{phrase}' is not supported for automatic skill creation. "
                f"This prototype supports simple deterministic text/math/JSON ops only."
            )

    # Match against template catalog (longest keyword wins)
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
        goal_words = set(re.findall(r"[a-z]+", goal_lower))
        blocked = goal_words & _OUT_OF_SCOPE_WORDS
        if blocked:
            raise AutogenError(
                f"Out of scope: '{', '.join(sorted(blocked))}' is not supported. "
                f"This prototype supports simple deterministic text/math/JSON ops only."
            )
        families = sorted(set(t.get("family", "") for t in _TEMPLATES.values()) - {""})
        raise AutogenError(
            f"Could not match goal '{goal}' to a known template. "
            f"Supported families: {', '.join(families)}. "
            f"Supported ops: {', '.join(sorted(_TEMPLATES.keys()))}"
        )

    return _spec_from_template(best_key, goal)


def _spec_from_template(template_key: str, goal: str) -> SkillSpec:
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
        family=tmpl.get("family", ""),
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
    input_names = [inp["name"] for inp in spec.inputs]
    func_name = spec.op_name.replace(".", "_")

    lines = [
        f'def {func_name}(config: dict, inputs: dict) -> dict:',
        f'    """{spec.description}"""',
    ]
    if len(input_names) == 1 and input_names[0] == "text":
        lines.append('    text = inputs.get("text", "")')
    lines.append(f'    {code_body}')

    return "\n".join(lines)


# ── File generation ───────────────────────────────────────────────


def generate_skill_files(spec: SkillSpec, output_dir: str | Path) -> Path:
    """Generate complete skill package files from a spec."""
    skill_dir = Path(output_dir) / spec.skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)

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
        f"id: {spec.skill_id}\nname: {spec.human_name}\nversion: 1.0.0\n"
        f"description: {spec.description}\n\n"
        f"inputs:\n{inputs_yaml}\n\noutputs:\n{outputs_yaml}\n\n"
        f"effects:\n  - pure\n\ntags:\n{tags_yaml}\n"
    )

    output_name = spec.outputs[0]["name"]
    edges_yaml = "\n".join(
        f"  - from: input.{inp['name']}\n    to: run.{inp['name']}"
        for inp in spec.inputs
    )

    (skill_dir / "graph.yaml").write_text(
        f"version: 1\n\nnodes:\n  - id: run\n    op: {spec.op_name}\n\n"
        f"edges:\n{edges_yaml}\n\noutputs:\n  {output_name}: run.{output_name}\n"
    )

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
    """Register the generated op in the runtime op registry."""
    from graphsmith.constants import PRIMITIVE_OPS
    from graphsmith.ops.registry import _PURE_OPS

    if spec.op_name in _PURE_OPS:
        return  # already registered

    tmpl = _TEMPLATES[spec.template_key]
    code_body = tmpl["code_body"]
    input_names = [inp["name"] for inp in spec.inputs]
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
    _PURE_OPS[spec.op_name] = namespace[func_name]
    PRIMITIVE_OPS.add(spec.op_name)


# ── Validation + test execution ───────────────────────────────────


def validate_and_test(spec: SkillSpec, skill_dir: Path) -> dict[str, Any]:
    """Validate the generated skill and run example tests."""
    from graphsmith.exceptions import ValidationError
    from graphsmith.ops.registry import execute_op
    from graphsmith.parser import load_skill_package
    from graphsmith.validator import validate_skill_package

    result: dict[str, Any] = {
        "skill_id": spec.skill_id, "validation": "FAIL",
        "examples_total": 0, "examples_passed": 0, "errors": [],
        "failure_stage": "", "passed": False,
    }

    try:
        register_generated_op(spec)
    except Exception as exc:
        result["failure_stage"] = "registration"
        result["errors"].append(f"Op registration failed: {exc}")
        return result

    try:
        pkg = load_skill_package(str(skill_dir))
        validate_skill_package(pkg)
        result["validation"] = "PASS"
    except (ValidationError, Exception) as exc:
        result["failure_stage"] = "validation"
        result["errors"].append(f"Validation: {exc}")
        return result

    result["examples_total"] = len(spec.examples)
    for i, ex in enumerate(spec.examples):
        try:
            output = execute_op(spec.op_name, spec.config, ex["input"])
            if output == ex["output"]:
                result["examples_passed"] += 1
            else:
                result["failure_stage"] = "examples"
                result["errors"].append(f"Example {i+1}: expected {ex['output']}, got {output}")
        except Exception as exc:
            result["failure_stage"] = "examples"
            result["errors"].append(f"Example {i+1}: {exc}")

    result["passed"] = (
        result["validation"] == "PASS"
        and result["examples_passed"] == result["examples_total"]
    )
    return result


def format_result(result: dict[str, Any], skill_dir: Path) -> str:
    """Format validation/test result as human-readable text."""
    lines = [f"  Created: {skill_dir}", f"  Validation: {result['validation']}"]
    if result["examples_total"] > 0:
        lines.append(f"  Examples: {result['examples_passed']}/{result['examples_total']} PASS")
    if result.get("failure_stage"):
        lines.append(f"  Failure stage: {result['failure_stage']}")
    if result["errors"]:
        lines.append("  Issues:")
        for err in result["errors"][:5]:
            lines.append(f"    - {err}")
    return "\n".join(lines)


# ── Bulk test harness ─────────────────────────────────────────────


def run_generation_suite() -> dict[str, Any]:
    """Run all templates through generate → validate → test.

    Returns a summary dict with per-template results.
    """
    import tempfile

    results: list[dict[str, Any]] = []
    tmpdir = Path(tempfile.mkdtemp())

    for key in sorted(_TEMPLATES.keys()):
        spec = _spec_from_template(key, f"test {key}")
        skill_dir = generate_skill_files(spec, tmpdir)
        result = validate_and_test(spec, skill_dir)
        result["template_key"] = key
        result["family"] = spec.family
        results.append(result)

    total = len(results)
    passed = sum(1 for r in results if r["validation"] == "PASS" and r["examples_passed"] == r["examples_total"])
    val_fail = sum(1 for r in results if r["validation"] != "PASS")
    ex_fail = sum(1 for r in results if r["validation"] == "PASS" and r["examples_passed"] < r["examples_total"])

    return {
        "total": total,
        "passed": passed,
        "validation_failures": val_fail,
        "example_failures": ex_fail,
        "results": results,
    }
