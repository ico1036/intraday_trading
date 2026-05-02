# intraday_trading v2 — Agent harness redesign

This directory documents v2 of the research harness. v1 remains in place;
v2 is developed alongside under `scripts/agent/v2/` and consumed through a
new `run_v2.py` entry point.

## Intent

v1 collapses "parameter tuning" and "algorithm redesign" into one feedback
loop driven by agent judgment. This produces two known failure modes:

1. Parameter-space exhaustion gets misrouted as algorithm redesign.
2. Hypothesis is abandoned before representation space has been explored.

v2 uses one SDK agent, driven by the Python orchestrator through explicit
phase prompts. It separates three axes:

- **Parameter** — numeric knobs within an expression. The development phase handles.
- **Expression** — a point in `config/expression_axes.yaml`. Same thesis,
  different representation.
- **Thesis** — the underlying economic claim. Changes only via a
  deterministic gate.

Routing between these is a **script decision**, not an agent decision.

## Vocabulary

| Term | Definition |
|---|---|
| Run | One invocation of the loop with a fixed `PLAN.md`. |
| Thesis | A natural-language economic claim the run is testing. |
| Expression | A concrete strategy instance testing that thesis. |
| Failure mode | Classified outcome of a failed expression (enum). |
| Verdict | Deterministic label on a thesis: ACTIVE / EXHAUSTED / REFUTED / SCOPE_RESTRICTED. |

## Directory layout (target)

```
intraday_trading/
├── config/
│   ├── failure_modes.yaml        # 9 enum values (incl. OTHER)
│   ├── feature_vocab.yaml        # bounded ≤ 15 features
│   ├── expression_axes.yaml      # 9 axes, enum per axis
│   └── targets.yaml              # default APPROVED criteria
│
├── archive/<run_id>/             # run-scoped artifacts
│   ├── PLAN.md                   # user-edited goal + targets + strategy_request
│   ├── expression_log.jsonl      # SoT, append-only
│   ├── research_map.md           # within-run digest (regenerated each iter)
│   ├── theses/<thesis_id>/
│   │   ├── thesis.md
│   │   ├── verdict.md
│   │   ├── seen_failure_modes.jsonl
│   │   └── expressions/exp_NNN/
│   │       ├── spec.md                 # axis choices + param values
│   │       ├── algorithm_prompt.txt    # v2 schema
│   │       ├── backtest_report.md
│   │       ├── failure_mode.txt        # enum tag (analysis output)
│   │       └── addresses.txt           # "this exp targets prior failure X"
│   └── DONE                      # sentinel, written by exit_check
│
├── wiki/                         # cross-run belief (rebuildable)
│   ├── facts/{features,combinations,failure_modes,regimes}/*.md
│   └── cross_run/{best_recipes,refuted_theses,strategy_correlations}.md
│
└── scripts/agent/
    ├── run.py                    # v1 (kept, deprecated)
    ├── run_v2.py                 # v2 entry
    ├── v2/
    │   ├── scaffold.py           # archive<run_id> bootstrap
    │   ├── plan_template.md      # PLAN.md template
    │   └── deterministic/        # scripts only, no agent calls
    │       ├── classify_failure.py
    │       ├── thesis_fingerprint.py
    │       ├── thesis_gate.py
    │       ├── within_run_digest.py
    │       ├── exit_check.py
    │       ├── oos_clamp.py
    │       ├── integrity_test.py
    │       └── build_wiki.py
    └── agents/                   # single-agent identity + phase prompts
```

## Flow (Phase 2 complete view)

```
user → PLAN.md (editor)
         │
         ▼
Orchestrator loop, one SDK agent:
   ┌────────────────────────────────────────────────┐
   │ Research phase: compose_expression OR thesis   │
   │   - new_thesis path runs thesis_fingerprint    │
   │     and blocks on wiki/refuted_theses.md match │
   ├────────────────────────────────────────────────┤
   │ Development phase → strategy code + tests      │
   ├────────────────────────────────────────────────┤
   │ Analysis phase → backtest, artifacts, tag      │
   │   (enum ONLY, no verdict language)             │
   ├────────────────────────────────────────────────┤
   │ ★ thesis_gate.py reads seen_failure_modes      │
   │   Emits verdict.md:                            │
   │     ACTIVE → compose_expression                │
   │     EXHAUSTED → compose_expression, new axis   │
   │     SCOPE_RESTRICTED → compose_expression +    │
   │                        regime/universe filter  │
   │     REFUTED → new_thesis                       │
   ├────────────────────────────────────────────────┤
   │ exit_check.py → targets met? budget gone?      │
   │   yes → write DONE, break                      │
   └────────────────────────────────────────────────┘
         │
         ▼ (on run end)
   build_wiki.py rebuilds wiki/ from archive/ (idempotent)
```

## Phase status

| Phase | Scope | Status |
|---|---|---|
| 0 | Plumbing: configs, PLAN.md, archive scaffolding, run_v2 skeleton | in progress |
| 1 | Thesis/expression split in agent prompts + orchestrator | pending |
| 2 | Deterministic gates (classify_failure, thesis_gate, OOS clamp) | pending |
| 3 | Integrity test + guardrails | pending |
| 4 | Cross-run wiki (build_wiki.py) | pending |
| 5 | Cleanup, deprecate v1 | pending |

## Invariants (enforced as we go)

1. **Agents never write `verdict.md`.** Only `thesis_gate.py` writes it.
2. **Agents never read `expression_log.jsonl` directly.** Only `research_map.md` summary.
3. **Failure modes are enum, not prose.** Analysis phase output is a single key from `config/failure_modes.yaml`.
4. **`wiki/` is rebuildable.** Deleting `wiki/` and re-running `build_wiki.py` must reproduce byte-for-byte.
5. **One thesis, many expressions.** A redesign that keeps `thesis_id` is an expression change; a new `thesis_id` is a thesis change.
