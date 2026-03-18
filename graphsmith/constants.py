"""Shared constants for Graphsmith."""

PRIMITIVE_OPS = {
    "template.render",
    "json.parse",
    "select.fields",
    "array.map",
    "array.filter",
    "branch.if",
    "fallback.try",
    "parallel.map",
    "assert.check",
    "llm.generate",
    "llm.extract",
    "skill.invoke",
    "text.normalize",
    "text.word_count",
    "text.reverse",
    "text.sort_lines",
    "text.remove_duplicates",
    "text.title_case",
}

ALLOWED_TYPES: set[str] = {
    "string",
    "integer",
    "number",
    "boolean",
    "bytes",
    "object",
}

ALLOWED_EFFECTS = {
    "pure",
    "llm_inference",
    "network_read",
    "network_write",
    "filesystem_read",
    "filesystem_write",
    "memory_read",
    "memory_write",
}
