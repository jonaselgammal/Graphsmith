# Cloudflare Remote Registry

This is the first hosted-service scaffold for the Graphsmith remote registry.

Code lives in:

- `cloudflare/remote-registry-worker/`

It is a Cloudflare Worker backed by D1 and implements the same API the current
`RemoteRegistryClient` already speaks:

- `GET /v1/manifest`
- `GET /v1/search`
- `GET /v1/skills/{skill_id}/versions/{version}`
- `POST /v1/skills`

## Why Cloudflare first

For a free prototype, Cloudflare is a good fit because:

- Workers Free currently allows `100,000/day` requests
- D1 Free currently includes `5 million/day` rows read, `100,000/day` rows
  written, and `5 GB` total storage

That is enough for an early registry API if the first version stays small and
metadata-heavy.

## Service shape

The current scaffold stores:

- search/index metadata in D1
- package file contents in D1 as text

That is not the long-term storage architecture, but it is enough for the first
free hosted version.

Longer term, package blobs should move to object storage and D1 should remain
the metadata/index layer.

## What you need to do

### 1. Create a Cloudflare account

If you do not already have one, create a Cloudflare account.

### 2. Install Node and Wrangler

From the worker directory:

```bash
cd cloudflare/remote-registry-worker
npm install
```

Then authenticate Wrangler:

```bash
npx wrangler login
```

### 3. Create the D1 database

```bash
npx wrangler d1 create graphsmith-remote-registry
```

Wrangler will print the `database_id`. Copy that into your Worker config.

### 4. Create your local Worker config

Copy:

- `wrangler.jsonc.example` -> `wrangler.jsonc`

Then edit:

- `database_id`
- `REGISTRY_ID`
- `REGISTRY_DISPLAY_NAME`
- `REGISTRY_OWNER`
- `REGISTRY_DESCRIPTION`
- optionally `REGISTRY_TRUST_SCORE`

### 5. Set the publish secret

```bash
npx wrangler secret put PUBLISH_TOKEN
```

Use a long random token. Graphsmith will send it as a bearer token when you run
`graphsmith remote-publish`.

### 6. Apply the schema

```bash
npx wrangler d1 migrations apply graphsmith-remote-registry --remote
```

### 7. Deploy

```bash
npx wrangler deploy
```

Wrangler will output your Worker URL, typically on `*.workers.dev`.

### 8. Point Graphsmith at it

Search or fetch:

```bash
graphsmith search summarize --remote-registry https://your-worker.workers.dev
```

Publish:

```bash
export GRAPHSMITH_REMOTE_TOKEN=your-token
graphsmith remote-publish examples/skills/text.word_count.v1 \
  --remote-registry https://your-worker.workers.dev
```

Bulk publish with duplicate-safe behavior:

```bash
for d in examples/skills/*/; do
  graphsmith remote-publish "$d" \
    --remote-registry https://your-worker.workers.dev \
    --skip-existing
done
```

## Current limitations

- no object storage yet
- no pagination yet
- publish validation is still bounded, but now checks basic skill/graph/example
  structure before indexing
- no moderation workflow yet
- no namespaces yet
- no trust-aware ranking yet

This is the free-hosted bootstrap, not the final architecture.
