# Research Wiki

This wiki is a lightweight memory layer for alpha research loops. It is not a
winner recommender. Its job is to keep goals, post-analysis reports, and compact
search indexes available without forcing agents to read the whole archive.

## Files

- `alpha_memory.jsonl` - append/upsert index, one alpha per line.
- `family_memory.jsonl` - compact family-level summaries, no best-parameter
  recommendations.
- `goals/<run_id>.md` - user goal and hard constraints for a run.
- `reflections/<run_id>.md` - soft, goal-conditioned reflection before/inside
  a loop.
- `post_analysis/<run_id>/<alpha_id>.md` - post-backtest strategy/result
  explanation.
- `snapshots/<run_id>_start_alpha_memory.jsonl` - frozen memory visible at run
  start.

## Policy

- Before a loop: read the goal, the alpha memory snapshot, and only the linked
  post-analysis files relevant to the goal.
- After every backtest: write post-analysis and upsert `alpha_memory.jsonl`.
- Success and failure use the same post-analysis template.
- Do not store "best params" or direct clone instructions.
- Use past memory as mechanism-level context, not as permission to chase a
  local maximum.
- OS/full-period artifacts remain sealed during generation. Use IS data for
  post-analysis unless the user explicitly opens validation.

