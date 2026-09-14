"""Live Amihud composite: xs_factor_amihud60d_fwd at five concentrations, equal weight, gross 5.

The five members are one signal (60-day Amihud illiquidity, forward-return
sorted) at concentrations 10% to 50%, so this composite is the parameter
average of one factor rather than a pool search. ``TARGET_GROSS = 5`` scales
every row to five times capital; the gross-1 sibling replays the same book
unlevered.

Run::

    uv run python -m intraday.composites.hierarchical_amihud_quality_corr095_gross5_weight_composite_v1 --run-id run_2026_08_pit641
"""
from __future__ import annotations

import pandas as pd

from intraday.composites._runner import cli

COMPOSITE_ID = "hierarchical_amihud_quality_corr095_gross5_weight_composite_v1"
COMPOSITION_NOTE = "amihud60d_fwd c10..c50 equal weight, gross 5"
TARGET_GROSS: float | None = 5.0
MEMBERS: tuple[str, ...] = (
    "xs_factor_amihud60d_fwd_c10",
    "xs_factor_amihud60d_fwd_c20",
    "xs_factor_amihud60d_fwd_c30",
    "xs_factor_amihud60d_fwd_c40",
    "xs_factor_amihud60d_fwd_c50",
)


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    known = set(alpha_index["alpha_id"])
    missing = [m for m in MEMBERS if m not in known]
    if missing:
        raise ValueError(f"members missing from alpha_index: {missing}")
    return list(MEMBERS)


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    return {a: 1.0 / len(member_ids) for a in member_ids}


def main() -> None:
    cli(COMPOSITE_ID, select_members, member_weights, COMPOSITION_NOTE, TARGET_GROSS)


if __name__ == "__main__":
    main()
