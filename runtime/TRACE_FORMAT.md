# Trace Format

```yaml
trace_id: uuid
graph_id: literature.quick_review.glue.001
root_skill_id: literature.quick_review.v1
start_time: 2026-03-16T10:00:00Z
end_time: 2026-03-16T10:00:03Z
status: success

node_runs:
  - node_id: search
    op: skill.invoke
    skill_id: search.arxiv.v1
    status: success
    started_at: 2026-03-16T10:00:00Z
    ended_at: 2026-03-16T10:00:01Z
    input_summary:
      query: graph memory agents
    output_summary:
      result_count: 3

  - node_id: summarize
    op: parallel.map
    status: success

outputs:
  summary: "..."
```

## Required properties
- graph identity
- timing
- node-level status
- op names
- summarized IO
- final outputs
