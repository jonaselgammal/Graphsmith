# Registry API Draft

## Local-first endpoints

### Publish skill
`POST /skills`
- body: skill package or extracted JSON representation

### Get skill
`GET /skills/{id}/{version}`

### Search skills
`GET /skills/search?q=...&effects=...&input=...&output=...`

### Record trace
`POST /traces`

### List traces
`GET /traces?skill_id=...`

## Notes
v1 can begin as CLI-only.
The API exists here to stabilize eventual public registry semantics.
