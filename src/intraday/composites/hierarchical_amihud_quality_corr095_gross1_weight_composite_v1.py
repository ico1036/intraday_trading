"""The live Amihud composite replayed at gross 1: same five members and
coefficients as the gross-5 module, unlevered, for the like-for-like
comparison against single alphas.

Run::

    uv run python -m intraday.composites.hierarchical_amihud_quality_corr095_gross1_weight_composite_v1 --run-id run_2026_08_pit641
"""
from __future__ import annotations

from intraday.composites._runner import cli
from intraday.composites.hierarchical_amihud_quality_corr095_gross5_weight_composite_v1 import (
    MEMBERS,
    member_weights,
    select_members,
)

COMPOSITE_ID = "hierarchical_amihud_quality_corr095_gross1_weight_composite_v1"
COMPOSITION_NOTE = "amihud60d_fwd c10..c50 equal weight, gross 1"
TARGET_GROSS: float | None = 1.0

__all__ = ["COMPOSITE_ID", "COMPOSITION_NOTE", "TARGET_GROSS", "MEMBERS", "select_members", "member_weights"]


def main() -> None:
    cli(COMPOSITE_ID, select_members, member_weights, COMPOSITION_NOTE, TARGET_GROSS)


if __name__ == "__main__":
    main()
