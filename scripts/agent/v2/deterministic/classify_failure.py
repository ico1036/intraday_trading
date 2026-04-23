"""Classify a backtest outcome into exactly one failure mode.

Analyst calls this with (metrics, targets). The return value is a key from
``config/failure_modes.yaml`` or the literal ``"APPROVED"`` when all primary
gates pass.

This module is deterministic and side-effect free. Never touches disk except
for loading the enum whitelist at import time.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml


_FAILURE_MODES_PATH = (
    Path(__file__).resolve().parents[4] / "config" / "failure_modes.yaml"
)


def _load_enum() -> frozenset[str]:
    data = yaml.safe_load(_FAILURE_MODES_PATH.read_text())
    return frozenset(data["modes"].keys())


FAILURE_MODES: frozenset[str] = _load_enum()


# ---------------------------------------------------------------------------
# Small helpers.
# ---------------------------------------------------------------------------


def _cmp(value: float, spec: Mapping[str, Any]) -> bool:
    """Evaluate ``value <op> spec.value`` per targets.yaml schema."""
    op = spec["op"]
    threshold = spec["value"]
    if op == ">=":
        return value >= threshold
    if op == "<=":
        return value <= threshold
    if op == ">":
        return value > threshold
    if op == "<":
        return value < threshold
    if op == "==":
        return value == threshold
    raise ValueError(f"unknown op {op!r}")


def _primary_all_pass(metrics: Mapping[str, Any], primary: Mapping[str, Any]) -> bool:
    for key, spec in primary.items():
        if key not in metrics:
            return False
        if not _cmp(metrics[key], spec):
            return False
    return True


# ---------------------------------------------------------------------------
# Classification.
# ---------------------------------------------------------------------------


def classify(metrics: Mapping[str, Any], targets: Mapping[str, Any]) -> str:
    """Return a failure mode key or ``"APPROVED"``.

    The decision tree goes from most disqualifying to most specific:

    1. Too few trades → SIGNAL_SPARSE (can't conclude anything).
    2. All primary gates pass → APPROVED.
    3. Catastrophic outcome (win_rate or sharpe under auto_reject) →
       THESIS_INVERTED.
    4. Still under primary trade count → SIGNAL_SPARSE.
    5. Specific signatures (fees, symbol concentration, regime concentration,
       late entry, edge decay).
    6. Coin-flip → SIGNAL_NOISY.
    7. Fallback → OTHER.
    """
    primary = targets["primary"]
    auto_reject = targets["auto_reject"]

    # 1. Clearly too few trades to say anything.
    if _cmp(metrics["total_trades"], auto_reject["total_trades"]):
        return "SIGNAL_SPARSE"

    # 2. Catastrophic outcome — implicate the thesis. Must run BEFORE the
    #    APPROVED gate so a strategy that passes primary but has auto-reject
    #    signals is not rubber-stamped.
    if "win_rate" in auto_reject and _cmp(metrics["win_rate"], auto_reject["win_rate"]):
        return "THESIS_INVERTED"
    if "sharpe" in auto_reject and _cmp(metrics["sharpe"], auto_reject["sharpe"]):
        return "THESIS_INVERTED"

    # 3. Everything works.
    if _primary_all_pass(metrics, primary):
        return "APPROVED"

    # 4. Not enough trades to diagnose further — still sparse.
    if metrics["total_trades"] < primary["total_trades"]["value"]:
        return "SIGNAL_SPARSE"

    # 5a. Fees eating gross alpha.
    gross = metrics.get("gross_return")
    net = metrics.get("net_return")
    if gross is not None and net is not None and gross > 0 and net < 0:
        return "FEE_DOMINATED"

    # 5b. One symbol carries.
    per_sym = metrics.get("per_symbol_return") or {}
    if len(per_sym) >= 2:
        positives = [r for r in per_sym.values() if r > 0]
        negatives = [r for r in per_sym.values() if r < 0]
        if len(positives) == 1 and len(negatives) >= len(per_sym) - 1:
            return "OVERFIT_SYMBOL"

    # 5c. One regime carries.
    per_reg = metrics.get("per_regime_return") or {}
    if len(per_reg) >= 2:
        pos_sum = sum(v for v in per_reg.values() if v > 0)
        neg_sum = sum(v for v in per_reg.values() if v < 0)
        pos_count = sum(1 for v in per_reg.values() if v > 0)
        if pos_count == 1 and pos_sum > abs(neg_sum):
            return "REGIME_DEPENDENT"

    # 5d. Captured a small fraction of the move — entering late.
    entry_to_peak = metrics.get("entry_to_peak_ratio")
    if entry_to_peak is not None and entry_to_peak < 0.3:
        return "LATE_ENTRY"

    # 5e. Peak arrived early relative to hold — edge decayed before exit.
    peak_bar = metrics.get("median_bar_to_peak")
    held_bars = metrics.get("median_bars_held")
    if peak_bar is not None and held_bars is not None and held_bars > 0:
        if peak_bar / held_bars < 0.25:
            return "EDGE_DECAY"

    # 6. Coin-flip signature.
    win_rate = metrics.get("win_rate", 0.0)
    profit_factor = metrics.get("profit_factor", 1.0)
    if abs(win_rate - 0.5) < 0.05 and 0.9 < profit_factor < 1.1:
        return "SIGNAL_NOISY"

    # 7. Nothing matched.
    return "OTHER"
