# Funding-tail onset in xs_volume_rank shorts

> Annualization note (2026-09-12): every Sharpe and CAGR in this file uses the
> framework convention of 252 days. The daily series has 365 observations a
> year (crypto trades weekends), so multiply Sharpe by 1.20 and CAGR by 1.45
> for the 365-day figures. Ratios, t-stats, MDD, and %p of AUM are unaffected.

**Date** 2026-09-12 · **Status** exploratory — OS contaminated by selection (see Caveats); rule not in strategy code
**Scope** `xs_volume_rank` (reverse=true) on the 641-symbol PIT universe (`run_2026_08_pit641`)
**Artifacts** `data/funding_analysis/` — feature panel, daily funding, short-cell table, scripts

## What was found

Funding was never modeled in the backtest engine. Adding it to the live
forward window (2026-05-08..09-12) took Sharpe from 1.60 (fees + slippage) to
**0.29**. Funding cost −9.0%/yr against an 11% CAGR.

The cost is not a steady carry. It is a tail, and the tail has a specific
shape:

- Funding-rate skew is −26 to −30 in every period. Positive tail caps at
  +44..+66 bps/day; negative tail runs to −250..−600. Cause: cash-and-carry
  arbitrage caps positive funding; negative funding needs spot borrow, which
  does not exist for small alts.
- Binance moved most symbols from 8h to 4h funding starting 2023-12 (0% →
  77% of cells). More settlements per day = more chances to hit the ±2% cap.
  Extreme-funding days are 5.7x more frequent on 4h symbols. `LABUSDT`
  printed −28.8% in one day on hourly settlement.
- The strategy shorts the top-volume half. A short squeeze is a volume
  explosion, so the strategy shorts exactly the names entering deep negative
  funding.

### Onset vs continuation

Split funding-tail cells (daily funding < −100 bps) by whether yesterday was
also a tail day. OS, short positions:

| | n | funding | price (short) | net | model catches |
|---|---|---|---|---|---|
| **onset** (first day) | 1,430 | −245 | **−1,160** | **−1,404** | 22.6% |
| continuation | 1,588 | −327 | +57 | −270 | 89.3% |

Onset days are 47% of tail cells and **82% of tail loss**. Price damage is
100% intraday (open→close −611 median; overnight gap 0). The day's first
settlement is 2% of the day's funding; the extreme settlement lands at the
50% point. From T+1 the short is right on price again (+99) and only pays
funding.

Onset has a faint prior-day signature (volume 1.8x, accel +0.034) but no
specificity: onset classifier AUC 0.86 with 10% precision at 1% cutoff.
Acceleration features add nothing. Uncertainty models (heteroskedastic σ̂,
quantile bounds, ensemble disagreement, Mahalanobis) are well calibrated
(90% coverage) but the price-catastrophic onsets sit in the **lowest**
uncertainty tercile. They are confident-wrong, not uncertain. Clustering
predicts continuation, not initiation.

At the portfolio level onset is a drag, not a tail: −28.5%p over 2y OS
against +23.1%p total, but the worst 5 portfolio days contain 0–3 onset
cells each. 196 shorts at 0.25% each turn a −1,180 bps cell into a −3 bps
portfolio hit.

## What works

**Funding is predictable; price is not.** Ridge on 24 lagged/structural
features: funding R² 0.41 OS, price R² −0.005. Net P&L variance is 99.6%
price. Model funding only; treat expected price alpha as constant.

**Level cut beats rank cut.** Per-day objective Σ wᵢ(E[α]+E[funding]) has the
closed-form solution "short iff E[funding] > −k". A level cut is auto-dynamic
(blocks 0.5% when onset density is 0.19%, 4.6% when 1.20%) and does nothing
when there is nothing to block. A rank cut always blocks its quantile and
hurts in low-onset regimes (IS-late: 0.239 vs 0.333 baseline).

**Regime-split training.** `nset` (settlements/day) was 23 of 56,573 training
cells before 2023-03 and then 27% of IS-late. Ridge extrapolated a spurious
coefficient (5,436 cells predicted −50..−100, realized +6); XGB memorized the
23 cells into one leaf (min_child_weight=20) and sent 14% of shorts there.
Both fail. Fix: drop raw `nset`, train an 8h model and a 4h model separately,
and apply the 4h model only once ≥5,000 4h training cells exist.

**Hard gate fails.** Excluding 4h symbols from the short leg (42–71% of it)
gives OS Sharpe 0.558 vs 0.695 baseline. Most 4h cells are fine shorts.

**Going conservative fails.** Blocking >2% of shorts lowers CAGR *and*
worsens MDD/CVaR: survivors are the signature-less onsets (−1,180 →
−3,353/cell) and renormalization concentrates the leg (0.25% → 0.35%).

### Walk-forward results (rolling 6-month blocks, nothing fit on OS)

| rule | IS-late Sh | OS Sh | OS blocked |
|---|---|---|---|
| no filter | 0.333 | 0.695 | — |
| single Ridge, level −80 | 0.349 | 0.952 | 1.6% |
| regime-split Ridge, −80 | 0.374 | 0.949 | 1.5% |
| **regime-split XGB, −80** | **0.414** | **1.011** | 2.2% |
| oracle (perfect foresight) | — | 2.40 | — |

Funding savings reach 91% of oracle. The remaining gap is oracle's price
gain (+2,265 OS), which requires predicting price and cannot be closed.

## Recommended rule

`nset`-free features · separate 8h / 4h XGB regressors · rolling refit ·
block a short when predicted daily funding < −80 bps · renormalize the short
leg to 0.5 gross.

## Caveats

- **OS was used for selection. Treat every OS number here as an optimistic
  bound, not a holdout result.** The onset phenomenon was discovered on the
  forward window and characterized on OS. Learner (XGB vs Ridge), threshold
  (−50..−150), rank vs level, regime-split, hard gate, conservatism sweep and
  uncertainty variants were all compared with OS Sharpe visible — on the
  order of 50 OS evaluations across IS-late / OS-1..4 / forward. The final
  rule is also what IS-late alone selects (XGB −80: 0.414, highest of all
  variants), so the *choice* does not depend on OS; but the reported OS
  1.011 is the max over many looks. No untouched holdout remains. The only
  clean test is a pre-registered forward run.
- IS has almost no onset (0.037% vs OS 0.117%) because 4h funding did not
  exist, so IS cannot confirm the effect even in principle.
- Onset is exchange microstructure, not a market regime. It persists while
  4h/1h settlement does. Binance can change it either way.
- Slippage in the live numbers is an assumption (tiered by ADV). 87% of
  short notional is in names with ADV < $5M.
- 127 days live. Standard error on an annualized Sharpe over 128 daily
  observations is about ±1.4 at one sigma (Lo 2002: sqrt((1+SR_d²/2)/n)
  annualized), not ±0.15 as first stated. Every live-window Sharpe in
  this note is inside one sigma of zero and of every other one.

## Open

- Intraday reaction rule ("exit when a settlement prints < −50 bps") targets
  the onset day directly. Needs alt intraday data; only 7 majors on disk.
- `fundingIntervalHours` from exchangeInfo replaces inferring `nset`.
- None of this is in strategy code. Live still runs the 273-symbol universe.

## Addendum 2026-09-12 — funding as a cross-sectional price signal (IS only)

Prompted by Presto Labs, *Can Funding Rate Predict Price Change?* Their
result: BTC funding→price R² ≈ 0 lagged, 12.5% contemporaneous; a
cross-sectional alpha `dl24 − dl6` on 5-min bars, top-50 liquid, no costs,
"extremely high" turnover. They do not examine persistence, asymmetry,
settlement interval, onset, or funding as a P&L cost.

Ported to the 641 daily universe and evaluated on IS only (2022-01..2024-04):

| signal | IC | IC t | LS Sh gross | +fees | **+fees +funding** |
|---|---|---|---|---|---|
| dl24 − dl6 (their form) | −0.001 | −0.3 | −0.17 | −0.31 | +0.71 |
| dl5 − dl1 | +0.004 | +1.0 | −1.57 | −1.91 | −1.13 |
| long high yesterday-funding | +0.008 | **+2.0** | **+1.70** | +1.48 | **−0.24** |
| long low 5d-avg funding | −0.010 | **−2.5** | −0.91 | −0.99 | +0.33 |

Their formula carries no information at daily frequency. The only
funding→price signals with |t| > 2 are the raw level, and both are fully
offset by the funding they collect or pay: long-high-funding earns +1.70 on
price and pays −1.94 in carry; long-low-funding loses −0.91 on price and
collects +1.24. **Funding predicts price only to the extent that it is the
price of the position.** Equilibrium, not alpha. This is the same fact as
"the short is right on price but pays it back in funding", seen from the
signal side, and it confirms treating funding as a cost to avoid rather
than a signal to trade.

## Addendum 2026-09-12 — full-cost walk-forward, no lookahead

Everything above priced fees and funding but not slippage, or priced slippage
on a window-median ADV. This table prices all three with trailing-30d ADV
tiers (no lookahead) and rolling regime-split XGB predictions (each block fit
only on data before it). Filter = level −80 bps. Units: Sharpe, %p of AUM.

| period | | Sharpe | CAGR | MDD | price | funding | fees | slippage |
|---|---|---|---|---|---|---|---|---|
| 2022-01..2023-03 (seed, no filter) | base | **1.35** | 11.4 | −5.9 | +30.2 | −5.3 | −4.0 | −1.8 |
| 2023-03..2024-04 | base | 0.17 | 1.2 | −8.2 | +14.1 | −6.2 | −4.1 | −1.9 |
| | filter | 0.25 | 1.7 | −7.7 | +13.3 | −4.4 | −4.2 | −1.9 |
| 2024-04..2026-05 (OS) | base | 0.43 | 3.4 | −6.7 | +45.1 | −22.1 | −7.1 | −6.0 |
| | filter | **0.73** | 5.6 | −7.1 | +38.7 | −8.3 | −7.5 | −6.3 |
| 2026-05..2026-09 (live) | base | **−0.06** | −0.4 | −5.6 | +8.4 | −4.6 | −1.7 | −2.4 |
| | filter | −0.14 | −0.9 | −5.7 | +5.3 | −1.5 | −1.8 | −2.5 |

Three things this changes:

1. **The strategy is at breakeven after costs since the 4h rollout.** It
   earned 1.35 in the seed window when funding cost ~4.5%/yr. Since 2023
   funding runs 6–13%/yr, fees ~5%/yr, slippage ~4–7%/yr, and price alpha
   of 10–24%/yr gross does not cover the sum. Earlier "fees-only" Sharpes
   (2.0 live) and "fees+funding" Sharpes (0.6 live) were partial.
2. **Slippage was understated earlier by ~1.7x.** The per-fill estimate used
   row notional (204k) where fee-implied notional was 377k. At ~7 bps per
   unit notional either way, the live-window cost is ~2.4%p / 128d, not 1.4.
3. **The filter's value is confined to OS.** It gains +0.30 on OS (the
   selection window), +0.08 on IS-late, and loses −0.07 on the live window,
   where it cut funding by 3.1%p and price by 3.1%p. Outside the window it
   was chosen on, it has not shown a net benefit.

Turnover is ~33x AUM per 128 days (~95x/yr). Fees plus slippage at ~12%/yr
is the largest controllable cost and has not been examined. A lower-frequency
rebalance is the most obvious untested change.

## Addendum 2026-09-12 — structural short-leg redefinitions (IS-selected, OS one-shot)

Overlays on predicted funding trade price for funding ~1:1 outside their
selection window. Tested instead whether redefining the short leg with an
observable state variable (no model) changes the structure. IS only, full
costs:

| rule | Sharpe | CAGR | price | funding | cost | blocked |
|---|---|---|---|---|---|---|
| base | 0.82 | 6.3 | +44.3 | −11.4 | −11.8 | — |
| **S1: short only if yesterday's funding ≥ 0** | **1.21** | **11.7** | **+57.1** | **+2.0** | −20.2 | 24.7% |
| S1b: ≥ −20 bps | 0.97 | 7.2 | +40.7 | −3.8 | −12.8 | 2.9% |
| S2: exclude names up >5% yesterday | 0.39 | 3.2 | +39.7 | −7.8 | −21.2 | 16.0% |
| S3: S1 and S2 | 0.68 | 7.4 | +47.9 | +2.4 | −25.8 | 36.4% |

S1 was the only variant where price alpha *rose*. Frozen on IS, evaluated
once on OS and the live window:

| period | base | S1 | price base→S1 | funding base→S1 |
|---|---|---|---|---|
| IS | 0.82 | 1.21 | +44.3 → +57.1 | −11.4 → +2.0 |
| **OS** | 0.43 | **0.47** | +45.1 → **+29.6** | −22.1 → +4.6 |
| **live** | −0.06 | **−0.30** | +8.4 → +4.2 | −4.6 → +0.2 |
| OS-1 / -2 / -3 / -4 | −0.81 / 1.24 / 0.31 / 0.65 | −0.93 / **1.78** / 0.07 / 0.45 | | |

The mechanism inverts across the 4h rollout. Pre-rollout, negative-funding
names were 25% of shorts and shorting them was a net loss; excluding them
raised price alpha. Post-rollout they are 31% of shorts and carry a large
share of the price alpha: excluding them flips funding positive (+26.7%p on
OS) but loses 15.5%p of price and adds 8.7%p of concentration cost. Net
+0.8%p CAGR on OS, −1.9%p on live. Only OS-2 benefits.

Two very different fixes (model overlay, state-variable redefinition) fail
the same way: the cost and the alpha come from the same names. At daily
resolution there is no observable that separates the squeeze-risk short
from the profitable crowded short.
