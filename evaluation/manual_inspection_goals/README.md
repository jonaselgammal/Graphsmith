# Manual Inspection Goals

This directory contains deliberately hard goals intended for manual inspection in
the Graphsmith UI rather than for automated pass/fail scoring.

Suggested workflow:

```bash
conda run -n graphsmith graphsmith solve \
  "$(jq -r .goal evaluation/manual_inspection_goals/hard_programming_probe.json)" \
  --remote-registry https://graphsmith-remote-registry.graphsmith.workers.dev \
  --provider openai \
  --model llama-3.1-8b-instant \
  --base-url https://api.groq.com/openai/v1 \
  --save-plan /tmp/hard_programming_probe.plan.json

conda run -n graphsmith graphsmith ui
```

Then load `/tmp/hard_programming_probe.plan.json` into the inspector.
