"""Shared helpers for IS-statistics-based composite builders.

Selection: every alpha whose ``is/metrics.json`` passes the IS-only mirror
of the SUBMITTABLE classifier (``classify_alpha(is_m, os_m=None)``).

Member daily returns: loaded from ``is/equity_curve.parquet`` and downsampled
to a per-date series via last-of-day equity, then converted to simple returns.
A members-aligned returns matrix ``R`` (T × N) is built for covariance /
mean / PCA estimation.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from intraday.composites._runner import ARCHIVE_ROOT


_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "scripts" / "tools"))
from alpha_dashboard_lib import classify_alpha  # noqa: E402


def member_is_sharpe(run_id: str, alpha_ids: list[str]) -> dict[str, float]:
    """Return ``{alpha_id: is_sharpe}`` for the given members."""
    out: dict[str, float] = {}
    for aid in alpha_ids:
        p = ARCHIVE_ROOT / run_id / "alphas" / aid / "is" / "metrics.json"
        if not p.exists():
            continue
        try:
            m = json.loads(p.read_text())
        except Exception:
            continue
        sh = m.get("sharpe")
        if sh is not None:
            out[aid] = float(sh)
    return out


def member_signs(run_id: str, alpha_ids: list[str],
                 dead_band: float = 0.0) -> dict[str, int]:
    """Return ``{alpha_id: ±1}`` — −1 when IS Sharpe < −dead_band, else +1.

    A symmetric dead-band keeps near-zero-Sharpe members un-flipped so
    we don't chase noise. Members missing IS Sharpe stay +1.
    """
    sh = member_is_sharpe(run_id, alpha_ids)
    signs: dict[str, int] = {}
    for aid in alpha_ids:
        s = sh.get(aid)
        if s is None or abs(s) <= dead_band:
            signs[aid] = 1
        else:
            signs[aid] = -1 if s < 0 else 1
    return signs


def member_ic(run_id: str, alpha_ids: list[str]) -> dict[str, float]:
    """Return ``{alpha_id: ic_mean}`` from each member's IS metrics.json."""
    out: dict[str, float] = {}
    for aid in alpha_ids:
        p = ARCHIVE_ROOT / run_id / "alphas" / aid / "is" / "metrics.json"
        if not p.exists():
            continue
        try:
            m = json.loads(p.read_text())
        except Exception:
            continue
        ic = m.get("ic_mean")
        if ic is not None:
            out[aid] = float(ic)
    return out


def member_signs_ic(run_id: str, alpha_ids: list[str],
                    dead_band: float = 0.005) -> dict[str, int]:
    """Return ``{alpha_id: ±1}`` by IC mean sign. IC is fee-agnostic and
    measures the raw signal direction, unlike Sharpe (which fee impact
    can drive negative on a real positive signal). ``dead_band`` keeps
    near-zero-IC members un-flipped to avoid chasing noise.
    """
    ic = member_ic(run_id, alpha_ids)
    signs: dict[str, int] = {}
    for aid in alpha_ids:
        v = ic.get(aid)
        if v is None or abs(v) <= dead_band:
            signs[aid] = 1
        else:
            signs[aid] = -1 if v < 0 else 1
    return signs


_ZOO_TAIL_RE = re.compile(r"_(fwd|rev)_c\d+$")


def family_key(alpha_id: str, level: str = "signal_dir") -> tuple[str, ...]:
    """Return a tuple identifying the parameter-sweep family of ``alpha_id``.

    The zoo generator (``scripts/tools/generate_factor_zoo.py``) mass-produces
    ``xs_factor_<signal>_<dir>_c<K>`` and ``xs_reg_<...>_<dir>_c<K>`` modules
    — same signal in many K (concentration) and window variants. For
    composite selection these cousins are not independent alphas; the
    correlation between them is high by construction. ``family_key`` groups
    them so a downstream dedup keeps one representative per family.

    ``level``:
        - ``"signal_window_dir"`` — collapse only K. ``atrproxy14d_rev_c40``
          and ``atrproxy14d_rev_c50`` share a key; ``atrproxy7d_rev`` does
          NOT (different window).
        - ``"signal_dir"`` (default) — also collapse window/alpha-numerics.
          All of ``atrproxy7d_rev_*``, ``atrproxy14d_rev_*``,
          ``atrproxy21d_rev_*`` share a single key.

    Non-zoo alphas (``xs_volume_rank``, hand-written ``ts_*`` strategies,
    etc.) do not match the pattern — they return a unique singleton key so
    they are never deduped against anything.
    """
    m = _ZOO_TAIL_RE.search(alpha_id)
    if not m:
        return ("__individual__", alpha_id)
    prefix = alpha_id[: m.start()]
    direction = m.group(1)
    if level == "signal_window_dir":
        return (prefix, direction)
    if level == "signal_dir":
        signal = re.sub(r"\d+d?$", "", prefix)
        signal = signal.rstrip("_") or prefix
        return (signal, direction)
    raise ValueError(f"unknown family_key level: {level!r}")


def family_dedup(alpha_ids: list[str], keep_metric: dict[str, float],
                 level: str = "signal_dir") -> list[str]:
    """Keep one representative per parameter-sweep family.

    Within each family (as identified by ``family_key``) keep the alpha
    with the highest ``keep_metric`` value. Alphas missing from the
    metric default to ``-inf`` (lose every tie). Non-zoo alphas always
    pass through — each has its own singleton family.

    Default ``level='signal_dir'`` is the most aggressive: a robust factor
    that produced 6 cousin-cell winners collapses to 1. Use
    ``level='signal_window_dir'`` to preserve different windows of the
    same signal as independent.
    """
    best: dict[tuple[str, ...], tuple[float, str]] = {}
    order: dict[tuple[str, ...], int] = {}
    for i, aid in enumerate(alpha_ids):
        key = family_key(aid, level=level)
        score = float(keep_metric.get(aid, float("-inf")))
        prev = best.get(key)
        if prev is None or score > prev[0]:
            best[key] = (score, aid)
            order.setdefault(key, i)
    return [best[k][1] for k in sorted(order.keys(), key=lambda k: order[k])]


def correlation_dedup(R: pd.DataFrame, threshold: float = 0.9,
                      keep_metric: dict[str, float] | None = None) -> list[str]:
    """Greedy correlation dedup.

    Order candidate members by ``keep_metric`` (descending). Walk the
    ranked list keeping each whose absolute Pearson correlation with
    every already-kept member is < ``threshold``. The result is a
    smaller orthogonal-ish subset that the precision matrix can invert.

    When ``keep_metric`` is missing entries, defaults the metric to 0
    for those members (they get ranked last).
    """
    if R.empty:
        return []
    members = list(R.columns)
    metric = {m: float((keep_metric or {}).get(m, 0.0)) for m in members}
    ranked = sorted(members, key=lambda m: metric[m], reverse=True)
    kept: list[str] = []
    corr = R.corr().abs()
    for m in ranked:
        if all(corr.at[m, k] < threshold for k in kept):
            kept.append(m)
    return kept


def apply_signs(coef: dict[str, float], signs: dict[str, int]) -> dict[str, float]:
    """Element-wise multiply coefficients by ±1 signs from ``member_signs``."""
    return {a: float(v) * int(signs.get(a, 1)) for a, v in coef.items()}


def select_all_alphas(run_id: str) -> list[str]:
    """Return every alpha dir that has ``is/metrics.json`` — SUBMITTABLE
    gate intentionally skipped. Use for EDA-driven composite building
    where the gate has been shown to filter out fee-impacted but
    flippable raw signals.
    """
    out: list[str] = []
    alphas_dir = ARCHIVE_ROOT / run_id / "alphas"
    for d in sorted(alphas_dir.iterdir()):
        if not d.is_dir():
            continue
        if (d / "is" / "metrics.json").exists():
            out.append(d.name)
    return out


def select_is_submittable(run_id: str) -> list[str]:
    out: list[str] = []
    alphas_dir = ARCHIVE_ROOT / run_id / "alphas"
    for d in sorted(alphas_dir.iterdir()):
        if not d.is_dir():
            continue
        p = d / "is" / "metrics.json"
        if not p.exists():
            continue
        try:
            is_m = json.loads(p.read_text())
        except Exception:
            continue
        label, _ = classify_alpha(is_m, os_m=None)
        if label == "SUBMITTABLE":
            out.append(d.name)
    return out


def load_member_is_returns(run_id: str, alpha_ids: list[str],
                           signs: dict[str, int] | None = None) -> pd.DataFrame:
    """Return a per-date returns matrix ``(T × N)`` indexed by date.

    Reads ``is/equity_curve.parquet`` for each alpha, downsamples to daily
    last equity, computes simple returns, and aligns on the common
    date index. Members with empty or missing curves are dropped.

    When ``signs`` is supplied, negative-sign members have their returns
    series multiplied by ``-1`` so the resulting matrix is sign-aligned
    (μ̂ flips from negative to positive for those members; Σ entries also
    flip sign — covariance with positive-sign neighbours becomes
    interpretable in the deployed direction).
    """
    series: dict[str, pd.Series] = {}
    for aid in alpha_ids:
        p = ARCHIVE_ROOT / run_id / "alphas" / aid / "is" / "equity_curve.parquet"
        if not p.exists():
            continue
        df = pd.read_parquet(p, columns=["timestamp", "equity"])
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        eod = (
            df.sort_values("timestamp")
            .assign(date=df["timestamp"].dt.normalize())
            .groupby("date")["equity"]
            .last()
        )
        if eod.empty or len(eod) < 2:
            continue
        ret = eod.pct_change().dropna()
        if ret.empty:
            continue
        series[aid] = ret
    if not series:
        return pd.DataFrame()
    R = pd.DataFrame(series).sort_index()
    # forward-fill missing returns to 0 (member not active yet)
    R = R.fillna(0.0)
    if signs:
        for aid, s in signs.items():
            if aid in R.columns and s == -1:
                R[aid] = -R[aid]
    return R


def shrink_cov(R: pd.DataFrame, shrinkage: float = 0.1) -> np.ndarray:
    """Ledoit-Wolf–style linear shrinkage toward diagonal.

    ``shrinkage`` ∈ [0, 1]. 0 = sample cov, 1 = pure diagonal of sample
    variances. 0.1 is a mild stabiliser that prevents near-singular Σ
    when N approaches T or members are highly collinear.
    """
    S = R.cov().values
    var_diag = np.diag(np.diag(S))
    return (1.0 - shrinkage) * S + shrinkage * var_diag


def normalize_coefficients(c: dict[str, float], scheme: str = "l1") -> dict[str, float]:
    """Scale coefficients so that the composite's gross-exposure budget is
    reasonable. ``scheme='l1'``: sum |c| = 1. ``scheme='sum'``: sum c = 1.

    Note: the composite runner re-normalizes weights row-wise so |W| ≤ 1
    at every timestamp regardless — coefficient scaling here is mostly
    cosmetic (preserves relative weights for `members.csv`).
    """
    if scheme == "l1":
        s = sum(abs(v) for v in c.values()) or 1.0
    elif scheme == "sum":
        s = sum(c.values()) or 1.0
    else:
        raise ValueError(f"unknown normalize scheme: {scheme}")
    return {k: float(v) / s for k, v in c.items()}
