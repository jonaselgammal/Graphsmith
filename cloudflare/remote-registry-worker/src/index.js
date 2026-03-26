import YAML from "yaml";

function jsonResponse(payload, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(payload, null, 2), {
    status,
    headers: {
      "content-type": "application/json",
      "access-control-allow-origin": "*",
      "access-control-allow-methods": "GET,POST,OPTIONS",
      "access-control-allow-headers": "content-type,authorization",
      ...extraHeaders,
    },
  });
}

function errorResponse(message, status = 400) {
  return jsonResponse({ error: message }, status);
}

function envManifest(env, requestUrl) {
  return {
    registry_id: env.REGISTRY_ID,
    display_name: env.REGISTRY_DISPLAY_NAME || env.REGISTRY_ID,
    registry_url: requestUrl.origin,
    description: env.REGISTRY_DESCRIPTION || "",
    owner: env.REGISTRY_OWNER || "",
    trust_score: parseFloat(env.REGISTRY_TRUST_SCORE || "0.5"),
    manifest_version: "1",
  };
}

function parseJsonArray(text) {
  try {
    const value = JSON.parse(text || "[]");
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
}

function makeEntry(row) {
  return {
    id: row.skill_id,
    name: row.name,
    version: row.version,
    description: row.description,
    tags: parseJsonArray(row.tags_json),
    effects: parseJsonArray(row.effects_json),
    input_names: parseJsonArray(row.input_names_json),
    required_input_names: parseJsonArray(row.required_input_names_json),
    optional_input_names: parseJsonArray(row.optional_input_names_json),
    output_names: parseJsonArray(row.output_names_json),
    published_at: row.published_at,
    source_kind: row.source_kind,
    registry_id: row.registry_id,
    registry_url: row.registry_url,
    publisher: row.publisher,
    trust_score: row.trust_score,
    manifest_version: row.manifest_version,
    remote_ref: row.remote_ref,
  };
}

async function hashFiles(files) {
  const data = new TextEncoder().encode(
    `${files.skill_yaml}\n---\n${files.graph_yaml}\n---\n${files.examples_yaml}`,
  );
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

function validatePublishToken(request, env) {
  const expected = env.PUBLISH_TOKEN || "";
  if (!expected) {
    return "PUBLISH_TOKEN secret is not configured";
  }
  const auth = request.headers.get("authorization") || "";
  if (auth !== `Bearer ${expected}`) {
    return "missing or invalid bearer token";
  }
  return "";
}

function buildSearchText(entry) {
  return [
    entry.id,
    entry.name,
    entry.description,
    ...(entry.tags || []),
    ...(entry.input_names || []),
    ...(entry.output_names || []),
  ].join(" ").toLowerCase();
}

async function handleManifest(request, env) {
  return jsonResponse(envManifest(env, new URL(request.url)));
}

async function handleSearch(request, env) {
  const url = new URL(request.url);
  const q = (url.searchParams.get("q") || "").toLowerCase();
  const effect = url.searchParams.get("effect") || "";
  const tag = url.searchParams.get("tag") || "";
  const inputName = url.searchParams.get("input_name") || "";
  const outputName = url.searchParams.get("output_name") || "";

  const { results } = await env.DB.prepare(
    `SELECT * FROM skills
     WHERE (?1 = '' OR search_text LIKE ?2)
       AND (?3 = '' OR effects_json LIKE ?4)
       AND (?5 = '' OR tags_json LIKE ?6)
       AND (?7 = '' OR input_names_json LIKE ?8)
       AND (?9 = '' OR output_names_json LIKE ?10)
     ORDER BY skill_id, version`,
  )
    .bind(
      q,
      `%${q}%`,
      effect,
      `%\"${effect}\"%`,
      tag,
      `%\"${tag}\"%`,
      inputName,
      `%\"${inputName}\"%`,
      outputName,
      `%\"${outputName}\"%`,
    )
    .all();

  const entries = (results || []).map(makeEntry);
  return jsonResponse({
    results: entries,
    next_cursor: "",
    total_estimate: entries.length,
  });
}

async function handleFetch(request, env, skillId, version) {
  const row = await env.DB.prepare(
    "SELECT * FROM skills WHERE skill_id = ?1 AND version = ?2",
  ).bind(skillId, version).first();
  if (!row) {
    return errorResponse(`Skill '${skillId}' version '${version}' not found`, 404);
  }
  return jsonResponse({
    manifest: envManifest(env, new URL(request.url)),
    entry: makeEntry(row),
    files: {
      skill_yaml: row.skill_yaml,
      graph_yaml: row.graph_yaml,
      examples_yaml: row.examples_yaml,
    },
    content_hash: row.content_hash,
  });
}

async function handlePublish(request, env) {
  const authError = validatePublishToken(request, env);
  if (authError) {
    return errorResponse(authError, 401);
  }

  let payload;
  try {
    payload = await request.json();
  } catch {
    return errorResponse("invalid JSON payload", 400);
  }

  const files = payload.files || {};
  if (!files.skill_yaml || !files.graph_yaml || !files.examples_yaml) {
    return errorResponse("publish payload must include skill_yaml, graph_yaml, and examples_yaml", 400);
  }

  let skill;
  try {
    skill = YAML.parse(files.skill_yaml) || {};
  } catch {
    return errorResponse("could not parse skill metadata", 400);
  }

  if (!skill.id || !skill.version || !skill.name) {
    return errorResponse("skill.yaml must contain id, name, and version", 400);
  }

  const existing = await env.DB.prepare(
    "SELECT 1 FROM skills WHERE skill_id = ?1 AND version = ?2",
  ).bind(skill.id, skill.version).first();
  if (existing) {
    return errorResponse(`Skill '${skill.id}' version '${skill.version}' is already published`, 409);
  }

  const manifest = envManifest(env, new URL(request.url));
  const contentHash = await hashFiles(files);
  const tags = Array.isArray(skill.tags) ? skill.tags : [];
  const effects = Array.isArray(skill.effects) ? skill.effects : [];
  const inputNames = Array.isArray(skill.inputs)
    ? skill.inputs.map((field) => field?.name).filter(Boolean)
    : [];
  const requiredInputNames = Array.isArray(skill.inputs)
    ? skill.inputs.filter((field) => field?.required !== false).map((field) => field?.name).filter(Boolean)
    : [];
  const optionalInputNames = Array.isArray(skill.inputs)
    ? skill.inputs.filter((field) => field?.required === false).map((field) => field?.name).filter(Boolean)
    : [];
  const outputNames = Array.isArray(skill.outputs)
    ? skill.outputs.map((field) => field?.name).filter(Boolean)
    : [];
  const publishedAt = new Date().toISOString();
  const entry = {
    id: skill.id,
    name: skill.name,
    version: skill.version,
    description: skill.description || "",
    tags,
    effects,
    input_names: inputNames,
    required_input_names: requiredInputNames,
    optional_input_names: optionalInputNames,
    output_names: outputNames,
    published_at: publishedAt,
    source_kind: "remote",
    registry_id: manifest.registry_id,
    registry_url: manifest.registry_url,
    publisher: manifest.owner,
    trust_score: manifest.trust_score,
    manifest_version: manifest.manifest_version,
    remote_ref: `${manifest.registry_id}:${skill.id}@${skill.version}`,
  };

  await env.DB.prepare(
    `INSERT INTO skills (
      skill_id, version, name, description,
      tags_json, effects_json, input_names_json, required_input_names_json,
      optional_input_names_json, output_names_json, published_at, source_kind,
      registry_id, registry_url, publisher, trust_score, manifest_version,
      remote_ref, content_hash, search_text, skill_yaml, graph_yaml, examples_yaml
    ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16, ?17, ?18, ?19, ?20, ?21, ?22, ?23)`,
  ).bind(
    entry.id,
    entry.version,
    entry.name,
    entry.description,
    JSON.stringify(entry.tags),
    JSON.stringify(entry.effects),
    JSON.stringify(entry.input_names),
    JSON.stringify(entry.required_input_names),
    JSON.stringify(entry.optional_input_names),
    JSON.stringify(entry.output_names),
    entry.published_at,
    entry.source_kind,
    entry.registry_id,
    entry.registry_url,
    entry.publisher,
    entry.trust_score,
    entry.manifest_version,
    entry.remote_ref,
    contentHash,
    buildSearchText(entry),
    files.skill_yaml,
    files.graph_yaml,
    files.examples_yaml,
  ).run();

  return jsonResponse({
    entry,
    warnings: [],
    content_hash: contentHash,
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") {
      return jsonResponse({}, 204);
    }
    if (request.method === "GET" && url.pathname === "/v1/manifest") {
      return handleManifest(request, env);
    }
    if (request.method === "GET" && url.pathname === "/v1/search") {
      return handleSearch(request, env);
    }
    if (request.method === "POST" && url.pathname === "/v1/skills") {
      return handlePublish(request, env);
    }

    const match = url.pathname.match(/^\/v1\/skills\/(.+)\/versions\/([^/]+)$/);
    if (request.method === "GET" && match) {
      return handleFetch(request, env, decodeURIComponent(match[1]), decodeURIComponent(match[2]));
    }

    if (request.method === "GET" && url.pathname === "/health") {
      return jsonResponse({ ok: true });
    }

    return errorResponse(`Unknown route: ${url.pathname}`, 404);
  },
};
