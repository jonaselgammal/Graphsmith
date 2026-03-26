CREATE TABLE IF NOT EXISTS skills (
  skill_id TEXT NOT NULL,
  version TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT NOT NULL,
  tags_json TEXT NOT NULL,
  effects_json TEXT NOT NULL,
  input_names_json TEXT NOT NULL,
  required_input_names_json TEXT NOT NULL,
  optional_input_names_json TEXT NOT NULL,
  output_names_json TEXT NOT NULL,
  published_at TEXT NOT NULL,
  source_kind TEXT NOT NULL,
  registry_id TEXT NOT NULL,
  registry_url TEXT NOT NULL,
  publisher TEXT NOT NULL,
  trust_score REAL,
  manifest_version TEXT NOT NULL,
  remote_ref TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  search_text TEXT NOT NULL,
  skill_yaml TEXT NOT NULL,
  graph_yaml TEXT NOT NULL,
  examples_yaml TEXT NOT NULL,
  PRIMARY KEY (skill_id, version)
);

CREATE INDEX IF NOT EXISTS idx_skills_search_text ON skills(search_text);
CREATE INDEX IF NOT EXISTS idx_skills_publisher ON skills(publisher);
