"""Composite alpha template — copy and fill the two functions.

Usage (mirrors the per-alpha _alpha_template.py workflow):

1. Copy this file to ``src/intraday/composites/<composite_id>.py``.
2. Set ``COMPOSITE_ID`` to ``<composite_id>`` and ``COMPOSITION_NOTE`` to a
   short human-readable label (e.g. ``"equal_weight_top20_is_sharpe"``).
3. Fill ``select_members`` to return the list of member ``alpha_id``\\s.
4. Fill ``member_weights`` to return ``{alpha_id: scalar}``.
5. Run::

       uv run python -m intraday.composites.<composite_id> --run-id run_2026_05_c

   This refreshes any member whose archive is stale (``--rerun-members
   auto``; ``always`` / ``never`` to force or skip), builds
   ``archive/<run_id>/composites/<composite_id>/{weights.parquet,
   manifest.json, members.csv}`` and replays IS + OS through the standard
   engine (``PrecomputedWeightsStrategy`` adapter) on the run's data path.

Look-ahead safeguards (enforced by the runner):

* The ``alpha_index`` DataFrame passed to your two functions has all ``os_*``
  columns stripped — referencing them raises ``KeyError``. Selection and
  weighting must use IS-only metrics.
* The selected list and coefficients are frozen in ``manifest.json``; the OS
  backtest replays the same ``weights.parquet``. Selection is never recomputed.
* If you load extra IS-derived stats yourself (e.g. per-alpha
  ``is/metrics.json``), confirm they come from the IS split only.
"""
from __future__ import annotations

import pandas as pd

from intraday.composites._runner import cli


COMPOSITE_ID = "_template_do_not_use"
COMPOSITION_NOTE = "describe_method_here"
# None clips each row's gross to 1; a number scales every row to that gross
# (a levered replay, run with --max-portfolio-weight set to match).
TARGET_GROSS: float | None = None


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    """Return the list of member ``alpha_id``\\s to combine.

    ``alpha_index`` is loaded from ``archive/<run_id>/alpha_index.csv`` with
    all ``os_*`` columns dropped. Available IS columns:
        ``alpha_id, status, strategy, is_sharpe, is_sharpe_daily, is_return,
         is_trades, is_dd, is_winrate, artifact_dir, notes``

    Example — top 20 IS-passing alphas by daily Sharpe::

        passed = alpha_index[alpha_index["status"] == "IS_PASS"]
        return passed.nlargest(20, "is_sharpe_daily")["alpha_id"].tolist()

    Parameter-sweep dedup: the zoo generator mass-produces cousin cells
    (same signal, different K / window). Stacking them double-counts the
    factor. ``family_dedup`` from ``_optim_helpers`` collapses each
    ``xs_factor_<signal>_<dir>`` family to its highest-IS-Sharpe member::

        from intraday.composites._optim_helpers import family_dedup
        passed = alpha_index[alpha_index["is_sharpe"] > 0]
        candidates = passed["alpha_id"].tolist()
        metric = dict(zip(passed["alpha_id"], passed["is_sharpe"]))
        return family_dedup(candidates, metric)  # default level='signal_dir'

    Pass ``level='signal_window_dir'`` to keep different windows of the
    same signal as independent. Hand-written ``ts_*`` / ``xs_volume_rank``
    alphas pass through untouched.
    """
    raise NotImplementedError("Fill select_members in your copy.")


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    """Return scalar coefficient per member: ``W_comp = Σ_a c_a · W_a``.

    Same OS-redaction applies. Coefficient magnitudes are relative — the
    runner row-wise normalizes so ``Σ_s |W_comp[t,s]| ≤ 1``.

    Example — 1/N equal weight::

        n = len(member_ids)
        return {a: 1.0 / n for a in member_ids}

    Example — IS-Sharpe-proportional::

        sub = alpha_index.set_index("alpha_id").loc[member_ids]
        s = sub["is_sharpe_daily"].clip(lower=0.0)
        total = s.sum() or 1.0
        return {a: float(s.loc[a]) / total for a in member_ids}
    """
    raise NotImplementedError("Fill member_weights in your copy.")


def main() -> None:
    cli(COMPOSITE_ID, select_members, member_weights, COMPOSITION_NOTE, TARGET_GROSS)


if __name__ == "__main__":
    main()
