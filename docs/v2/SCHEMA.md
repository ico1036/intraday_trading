# v2 data schemas

All schemas are authoritative. Agents must not invent fields; scripts must
validate presence before proceeding.

---

## PLAN.md

Markdown file, opened in `$EDITOR` on `run_v2.py --prepare`. Parsed by a
lenient reader — headers are required, bullet content is free-form.

```markdown
# Run: <run_id>

## Targets
profit_factor: 1.3
max_drawdown: -0.15
total_return: 0.05
total_trades: 30
max_trials: 20
max_expressions_per_thesis: 8
max_theses_per_run: 5

## Strategy request
<free-form natural language: direction, inspiration, constraints>

## Universe
symbols: [BTCUSDT, ETHUSDT]

## IS / OS periods
is_start: 2025-03-01
is_end: 2025-09-30
os_start: 2025-10-01
os_end: 2026-01-31
```

`Targets` keys override `config/targets.yaml` defaults per-run. Missing keys
fall back to defaults.

---

## expression_log.jsonl

Append-only. One JSON object per line. Written by `execute_expression.py`
(Phase 2). Never edited in place.

```json
{
  "ts": "2026-04-23T15:00:00Z",
  "run_id": "v1_vpin_reversal_20260423",
  "thesis_id": "th_001",
  "expression_id": "exp_003",
  "expression_spec": {
    "bar_domain": "VOLUME",
    "bar_granularity": "medium",
    "signal_form": "z_score",
    "threshold_type": "adaptive_quantile",
    "aggregation": "ema",
    "regime_filter": "vol_regime",
    "exit_rule": "time_stop",
    "sizing": "fixed",
    "universe": "single_symbol"
  },
  "features_used": ["vpin", "volume_imbalance"],
  "addresses": "exp_002:SIGNAL_SPARSE",
  "result": {
    "profit_factor": 1.12,
    "max_drawdown": -0.18,
    "total_return": 0.03,
    "total_trades": 22,
    "win_rate": 0.28,
    "sharpe": 0.31,
    "os_is_return_ratio": null
  },
  "failure_mode": "SIGNAL_SPARSE",
  "verdict_after": "ACTIVE",
  "artifact_path": "archive/v1_.../theses/th_001/expressions/exp_003/"
}
```

### Field contract

| Field | Type | Notes |
|---|---|---|
| `ts` | ISO8601 UTC | Wall-clock when the expression finished. |
| `run_id` | string | Matches `archive/<run_id>/`. |
| `thesis_id` | string | `th_NNN`. Zero-padded 3 digits. |
| `expression_id` | string | `exp_NNN`. Zero-padded 3 digits. |
| `expression_spec` | object | Keys must be from `config/expression_axes.yaml`. Values must be from each axis's enum. |
| `features_used` | array | Each entry must be a key from `config/feature_vocab.yaml`. |
| `addresses` | string or null | `<prior_exp_id>:<failure_mode>` the current expression targets. First expression of a thesis is null. |
| `result` | object | Backtest metrics. Null values allowed when OS not yet run. |
| `failure_mode` | string | Key from `config/failure_modes.yaml`, or `APPROVED`. |
| `verdict_after` | string | Verdict emitted by `thesis_gate.py` after this entry. |
| `artifact_path` | string | Relative to repo root. |

---

## theses/<thesis_id>/thesis.md

```markdown
---
thesis_id: th_001
created: 2026-04-23T14:00:00Z
fingerprint: sha256:...
status: ACTIVE
features: [vpin, volume_imbalance]
direction: reversal
---

# Thesis: <short name>

## Claim
<single sentence>

## Economic reasoning
<2-4 sentences on why this should work>

## What would refute this
<concrete: "if SIGNAL_NOISY across 3+ expressions with different regime filters">
```

`status` values: `ACTIVE`, `EXHAUSTED`, `REFUTED`, `SCOPE_RESTRICTED`.
Updated only by `thesis_gate.py`.

---

## theses/<thesis_id>/verdict.md

Machine-written by `thesis_gate.py`. Human-readable but not human-edited.

```markdown
---
thesis_id: th_001
verdict: REFUTED
decided_at: 2026-04-23T16:30:00Z
trigger: "3 orthogonal expressions with SIGNAL_NOISY"
orthogonality_axes: [signal_form, threshold_type, regime_filter]
expressions_evaluated: [exp_001, exp_002, exp_003]
next_action: new_thesis
---

# Verdict for th_001

## Evidence
| exp | spec diff | failure_mode |
|---|---|---|
| exp_001 | baseline | SIGNAL_NOISY |
| exp_002 | signal_form: z_score | SIGNAL_NOISY |
| exp_003 | threshold_type: adaptive_quantile, regime_filter: vol_regime | SIGNAL_NOISY |

## Rule applied
3 expressions differing on 3+ axes, all with the same `implication: thesis`
failure mode → REFUTED.

## Implication for future runs
Append fingerprint to `wiki/cross_run/refuted_theses.md` on run end.
```

---

## theses/<thesis_id>/seen_failure_modes.jsonl

Append-only. One line per expression of this thesis.

```json
{"expression_id": "exp_001", "failure_mode": "SIGNAL_NOISY", "spec_hash": "ab12..."}
```

`spec_hash` is a deterministic hash of `expression_spec` after sorting keys.
Used by `thesis_gate.py` to measure orthogonality between expressions.

---

## expressions/exp_NNN/algorithm_prompt.txt

v2 format. Required fields at top as YAML frontmatter, body remains
free-form markdown as in v1.

```markdown
---
thesis_id: th_001
expression_id: exp_003
expression_spec:
  bar_domain: VOLUME
  bar_granularity: medium
  signal_form: z_score
  threshold_type: adaptive_quantile
  aggregation: ema
  regime_filter: vol_regime
  exit_rule: time_stop
  sizing: fixed
  universe: single_symbol
features_used: [vpin, volume_imbalance]
addresses: "exp_002:SIGNAL_SPARSE"
---

# Strategy: <Name>

<rest identical to v1 algorithm_prompt.txt body>
```

---

## thesis_fingerprint

Deterministic SHA-256 over a canonical form:

```python
canonical = json.dumps({
    "direction": thesis.direction,           # "momentum" | "reversal" | "carry" | "arb" | ...
    "features": sorted(thesis.features),     # from feature_vocab
    "trigger_schema": thesis.trigger_schema, # structured: {"when": "<feature> <op> <quantile>", ...}
}, sort_keys=True, separators=(",", ":"))
fingerprint = "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()
```

Two theses with identical fingerprint are considered duplicates even if
their English prose differs. `wiki/cross_run/refuted_theses.md` stores
fingerprints, not prose.

---

## failure_mode.txt

Single-line file written by Analyst. Must equal one of the keys in
`config/failure_modes.yaml`, or the literal string `APPROVED`.

```
SIGNAL_SPARSE
```

No other content. No explanation. Explanation goes in
`backtest_report.md`.
