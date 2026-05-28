"""Anti-selection-bias composite: middle-quintile IS-Sharpe member selection
(rank 35-65% of SUBMITTABLE pool) with correlation dedup and equal-weight,
IC-signed combination. Motivated by Bailey & Lopez de Prado (2014),
'Pseudo-Mathematics and Financial Charlatanism: the Effects of Backtest
Overfitting on Out-of-Sample Performance,' and the CSCV / PBO literature:
top-ranked IS-Sharpe alphas are dominated by lucky overfits; middle ranks
have demonstrably lower PBO and cleaner OS generalization. No optimization
is performed -- this isolates *selection* as the OS lever, since prior
attempts (HRP, NCO, HERC, BL, DRP, Max-Div, mean-CVaR, fractional Kelly,
James-Stein, Neumann, CSCV-bootstrap) all top-ranked IS-Sharpe and all
collapsed OS->0."""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    correlation_dedup,
    member_signs_ic,
    apply_signs,
    select_is_submittable,
    select_all_alphas,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_012_antibias_middle_quintile_dedup085_equal"
COMPOSITION_NOTE = "antibias_middle_quintile_dedup085_equal_weight_l1_065"

RUN_ID = "run_2026_05_c"
DEDUP_THRESHOLD = 0.85
GROSS_TARGET = 0.65
LOW_PCT = 0.35
HIGH_PCT = 0.65
WIDE_LOW_PCT = 0.25
WIDE_HIGH_PCT = 0.75
MIN_MEMBERS = 8
MAX_MEMBERS = 40


def _is_returns_signed() -> tuple[pd.DataFrame, dict[str, int]]:
    ids = select_is_submittable(RUN_ID)
    if len(ids) < MIN_MEMBERS:
        ids = select_all_alphas(RUN_ID)
    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    return R, signs


def _sharpe_series(R: pd.DataFrame) -> pd.Series:
    mu = R.mean(axis=0)
    sd = R.std(axis=0).replace(0.0, np.nan)
    sh = (mu / sd) * np.sqrt(252.0)
    return sh.fillna(-np.inf)


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    R, _ = _is_returns_signed()
    n = R.shape[1]
    if n < 2:
        return list(R.columns)
    if n < MIN_MEMBERS:
        return list(R.columns)

    sharpe = _sharpe_series(R)

    # Anti-bias band: rank percentile in [LOW_PCT, HIGH_PCT].
    ranks = sharpe.rank(pct=True, method="average")
    band_mask = (ranks >= LOW_PCT) & (ranks <= HIGH_PCT)
    band_ids = list(sharpe.index[band_mask])

    # Fallback: widen the band if too thin (small pools).
    if len(band_ids) < MIN_MEMBERS:
        band_mask = (ranks >= WIDE_LOW_PCT) & (ranks <= WIDE_HIGH_PCT)
        band_ids = list(sharpe.index[band_mask])

    if len(band_ids) < 2:
        return list(R.columns)[: max(MIN_MEMBERS, 2)]

    R_band = R[band_ids]

    # Correlation dedup *within* the band; keep-metric = Sharpe so within
    # a clone-cluster we keep the higher one. Dedup is only removing
    # quasi-duplicates -- the anti-bias selection already happened upstream.
    keep_metric = {a: float(sharpe.get(a, 0.0)) for a in band_ids}
    try:
        kept = correlation_dedup(
            R_band, threshold=DEDUP_THRESHOLD, keep_metric=keep_metric
        )
    except Exception:
        kept = band_ids

    if len(kept) < 2:
        return band_ids[: min(len(band_ids), MAX_MEMBERS)]

    # Cap at MAX_MEMBERS via *even spacing* across the band's Sharpe ranking
    # (preserves the middle-quintile spread instead of biasing toward one end).
    if len(kept) > MAX_MEMBERS:
        kept_sorted = sorted(kept, key=lambda a: float(sharpe.get(a, 0.0)))
        idxs = np.linspace(0, len(kept_sorted) - 1, MAX_MEMBERS).astype(int)
        # unique preserving order
        seen: set[int] = set()
        picked: list[str] = []
        for i in idxs:
            ii = int(i)
            if ii in seen:
                continue
            seen.add(ii)
            picked.append(kept_sorted[ii])
        kept = picked

    if len(kept) < 2:
        return list(R.columns)[: max(MIN_MEMBERS, 2)]
    return kept


def member_weights(
    member_ids: list[str], alpha_index: pd.DataFrame
) -> dict[str, float]:
    if not member_ids:
        return {}

    # Equal-weight is the debiased baseline. We do NOT tilt by IS Sharpe --
    # tilting is what caused selection-bias collapse in iters 001-011.
    base = {a: 1.0 for a in member_ids}
    base = normalize_coefficients(base, "l1")  # sum(|c|) == 1

    # Scale so mean row L1 of composite W lands in [0.4, 0.8]. Per-member
    # W_a is row-L1<=1, so sum_s |W_comp[t,s]| <= GROSS_TARGET (tighter when
    # members share symbols).
    scaled = {a: float(v) * GROSS_TARGET for a, v in base.items()}

    # Re-fetch IC signs scoped to actually-selected members.
    signs = member_signs_ic(RUN_ID, member_ids)
    final = apply_signs(scaled, signs)

    # Belt-and-braces: ensure every requested id is present (apply_signs
    # returns a new dict but should preserve keys; missing sign defaults
    # are handled inside the helper).
    for a in member_ids:
        if a not in final:
            final[a] = scaled[a]
    return final


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--no-os", action="store_true")
    args = parser.parse_args()
    build_and_backtest(
        composite_id=COMPOSITE_ID,
        run_id=args.run_id,
        select_members=select_members,
        member_weights=member_weights,
        composition_note=COMPOSITION_NOTE,
        include_os=not args.no_os,
    )


if __name__ == "__main__":
    main()