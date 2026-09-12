# Pre-registration: funding_tail_filter_v1

> Annualization note (2026-09-12): every Sharpe and CAGR in this file uses the
> framework convention of 252 days. The daily series has 365 observations a
> year (crypto trades weekends), so multiply Sharpe by 1.20 and CAGR by 1.45
> for the 365-day figures. Ratios, t-stats, MDD, and %p of AUM are unaffected.

**Frozen** 2026-09-12 · **Applies to** `xs_volume_rank` (reverse=true), 641 PIT universe
**Artifacts** `data/funding_analysis/funding_tail_filter_v1.json`, `xgb_funding_8h.json`, `xgb_funding_4h.json`
**Background** `research/notes/funding_tail_onset.md`

This document fixes the rule before any forward data exists. Nothing below
may change once forward evaluation begins. If it changes, it is a new rule
with a new forward clock.

## Rule

At each daily rebalance, after the strategy forms its short basket:

1. For each short candidate, predict today's total funding (bps, sum of all
   settlements) with the XGB regressor matching its settlement regime —
   `xgb_funding_8h` if `fundingIntervalHours >= 8`, else `xgb_funding_4h`.
2. Drop the short if predicted funding < **−80 bps**.
3. Renormalize the remaining short leg to 0.5 gross. Long leg untouched.

## Model

- XGBRegressor, two instances (8h / 4h). Hyperparameters in the manifest.
- 23 features, all computable at the day's open from prior bars plus the
  day's 00:00 settlement. `nset` is explicitly excluded (see background note).
- Refit both models every 6 months on an expanding window. The 4h model is
  used only when its training set has ≥ 5,000 cells (satisfied since
  2024-04).

## Why these choices

Selection was made on IS-late (2023-03-02..2024-04-19) Sharpe only:

| k | Ridge | XGB |
|---|---|---|
| −50 | 0.321 | 0.407 |
| **−80** | 0.374 | **0.414** |
| −100 | 0.357 | 0.376 |

OS results exist and are contaminated by ~50 comparisons; they are not the
selection basis and are not to be cited as validation.

## Forward evaluation

- **Clock starts** at the first daily rebalance after this file is committed.
- **Control** is the identical strategy with no filter, same universe, same
  costs.
- **Costs** applied to both arms: 2/5 bps maker/taker, tiered half-spread by
  ADV, realized funding from settlement data.
- **Read at** 3 months (sanity) and 6 months (decision). No changes to the
  rule between reads.

## Pre-stated outcomes at 6 months

- **Supported**: filtered arm net Sharpe exceeds control by ≥ 0.20 and
  funding cost is reduced by ≥ 40%.
- **Not supported**: filtered arm Sharpe ≤ control, or funding reduction
  < 20%. The rule is retired; the analysis that produced it is treated as
  overfit.
- **Inconclusive**: anything between. Extend the clock 6 months once. No
  re-tuning.

## Known risks stated in advance

- Onset is exchange microstructure (4h/1h settlement). If Binance reverts
  intervals, both the cost and the filter's value shrink together.
- Slippage in the live numbers is modeled, not observed. 87% of short
  notional is in names with ADV < $5M.
- The 4h model has trained on 2024-04 onward only; any new interval class
  (e.g. 1h becoming common) is out of distribution and should trigger a
  third regime model, not a retune of this one.

## Implementation and clock start (2026-09-12)

- Code: `src/intraday/funding_filter.py` (predictor) and
  `src/intraday/strategies/multi/xs_volume_rank_ftf_strategy.py` (strategy).
  Models cache under `data/funding_filter_models/`.
- Costs are now charged by the engine (funding at every settlement, tiered
  slippage, fees), not overlaid; Sharpe on 365 days. Engine IS/OS with full
  costs: control 1.01 / 0.27, filtered 1.06 / 0.50; funding −3,370 → −1,849
  USD on 10,000 AUM over 2022-01..2026-05.
- Deviations from the research script: settlement-count features and the
  regime flag use the previous day's count (same-day count is not observable
  at the open); refits at 2023-03-02 then every Apr-20 / Oct-20 (expanding).
- Control and filtered arms both run on the 641 PIT universe
  (`archive/run_2026_08_pit641/alphas/xs_volume_rank{,_ftf}/forward`),
  daily under launchd. **Clock starts at the first tick after this commit.**
  Reads at 3 and 6 months per the outcomes above, Sharpe on 365 days.
