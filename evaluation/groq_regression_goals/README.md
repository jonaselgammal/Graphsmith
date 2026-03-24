# Groq Regression Goals

This subset contains the non-pass cases from the latest live Groq
`llama-3.1-8b-instant` evaluation sweep run on 2026-03-24.

Source runs:
- evaluation/goals: 9/9 pass
- evaluation/holdout_goals: 12/15 pass
- evaluation/challenge_goals: 12/12 pass

Included goals:
- `partial` `planner`: Clean the text, write a summary, and list the keywords ([evaluation/holdout_goals/h08_clean_summarize_keywords.json](/Users/jeg/Documents/graphsmith-pack/evaluation/holdout_goals/h08_clean_summarize_keywords.json))
- `partial` `planner`: Clean this text, then get both a summary and keywords ([evaluation/holdout_goals/h12_clean_and_get_summary_and_keywords.json](/Users/jeg/Documents/graphsmith-pack/evaluation/holdout_goals/h12_clean_and_get_summary_and_keywords.json))
- `partial` `planner`: Take this text, clean it up, extract the important keywords, and format them as a readable list ([evaluation/holdout_goals/h15_full_pipeline.json](/Users/jeg/Documents/graphsmith-pack/evaluation/holdout_goals/h15_full_pipeline.json))

Reproduce:
```bash
conda run -n graphsmith graphsmith eval-planner --goals evaluation/groq_regression_goals \
  --registry "$REG" --backend ir --ir-candidates 3 --decompose \
  --provider openai --model llama-3.1-8b-instant \
  --base-url https://api.groq.com/openai/v1 --delay 5
```
