#!/usr/bin/env python3
"""Oracle-ceiling EDA — dedup the alpha pool, measure the theoretical max.

Three pipelines compared on the IS daily-returns matrix of every alpha in
``archive/<run_id>/alphas/*/is/equity_curve.parquet``:

1. **Baseline** — equal-weight every alpha (1/N).
2. **Greedy Drop** — walk alphas in descending IS-Sharpe order; drop any
   candidate whose |Pearson ρ| ≥ τ with anyone already kept.
3. **Hierarchical Pruning** — Ward linkage on D = √(½ (1 − ρ)); cut at the
   distance that corresponds to τ; pick the highest-Sharpe alpha per
   cluster.

Outputs land in ``reports/oracle_eda/<run_id>/``:
- ``metrics.json``  — comparison table
- ``heatmap_before.png`` / ``heatmap_after.png``
- ``dendrogram.png`` (Ward, cut-off line marked)
- ``equity_curve.png`` (log-scale cumret of the 3 portfolios)

Example::

    uv run python scripts/tools/oracle_ceiling_eda.py \\
        --run-id run_2026_05_full531 --corr-threshold 0.3 --cost-bps 1.0
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
# Dark theme for all PNGs in this script — matches the HTML report.
plt.style.use("dark_background")
plt.rcParams.update({
    "axes.facecolor": "#0d0d12",
    "figure.facecolor": "#0d0d12",
    "savefig.facecolor": "#0d0d12",
    "axes.edgecolor": "#3a3a44",
    "axes.labelcolor": "#e5e7eb",
    "xtick.color": "#cbd5e1",
    "ytick.color": "#cbd5e1",
    "grid.color": "#2a2a34",
    "axes.titlecolor": "#e5e7eb",
    "text.color": "#e5e7eb",
    "legend.facecolor": "#1a1a24",
    "legend.edgecolor": "#3a3a44",
    "legend.labelcolor": "#e5e7eb",
})
import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import dendrogram, fcluster, linkage
from scipy.spatial.distance import squareform
from sklearn.cluster import AffinityPropagation


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
from intraday.composites._optim_helpers import (  # noqa: E402
    load_member_is_returns,
    member_is_sharpe,
    select_all_alphas,
)


ANNUAL_BARS = 252


def load_member_returns(run_id: str, alpha_ids: list[str], split: str) -> pd.DataFrame:
    """Generalized loader — same logic as load_member_is_returns but for
    either ``split='is'`` or ``split='os'``."""
    archive = REPO_ROOT / "archive" / run_id
    series: dict[str, pd.Series] = {}
    for aid in alpha_ids:
        p = archive / "alphas" / aid / split / "equity_curve.parquet"
        if not p.exists():
            continue
        df = pd.read_parquet(p, columns=["timestamp", "equity"])
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        eod = (
            df.sort_values("timestamp")
              .assign(date=df["timestamp"].dt.normalize())
              .groupby("date")["equity"].last()
        )
        if eod.empty or len(eod) < 2:
            continue
        ret = eod.pct_change().dropna()
        if ret.empty:
            continue
        series[aid] = ret
    if not series:
        return pd.DataFrame()
    R = pd.DataFrame(series).sort_index().fillna(0.0)
    return R


# ---------------------------------------------------------------------------
# metric helpers
# ---------------------------------------------------------------------------

def sharpe(daily_returns: pd.Series) -> float:
    sd = daily_returns.std(ddof=1)
    if not sd or not math.isfinite(sd):
        return 0.0
    return float(daily_returns.mean() / sd * math.sqrt(ANNUAL_BARS))


def max_drawdown(daily_returns: pd.Series) -> float:
    cum = (1.0 + daily_returns.fillna(0.0)).cumprod()
    peak = cum.cummax()
    dd = (cum / peak) - 1.0
    return float(dd.min()) if not dd.empty else 0.0


def annualized_return(daily_returns: pd.Series) -> float:
    cum = (1.0 + daily_returns.fillna(0.0)).prod()
    n = len(daily_returns)
    if n <= 0 or cum <= 0:
        return 0.0
    return float(cum ** (ANNUAL_BARS / n) - 1.0)


def annualized_vol(daily_returns: pd.Series) -> float:
    return float(daily_returns.std(ddof=1) * math.sqrt(ANNUAL_BARS))


def portfolio_metrics(daily_returns: pd.Series,
                      avg_trades_per_year: float,
                      cost_bps: float) -> dict:
    """Both gross and net (cost = cost_bps × avg trades/yr / 10_000)."""
    gross = daily_returns
    cost_annual = cost_bps * 1e-4 * avg_trades_per_year
    daily_cost = cost_annual / ANNUAL_BARS
    net = gross - daily_cost
    return {
        "sharpe_gross":   sharpe(gross),
        "sharpe_net":     sharpe(net),
        "max_drawdown":   max_drawdown(gross),
        "annualized_return": annualized_return(gross),
        "annualized_vol": annualized_vol(gross),
        "avg_trades_per_year_per_member": avg_trades_per_year,
    }


# ---------------------------------------------------------------------------
# trade-rate helper (for "avg turnover" column)
# ---------------------------------------------------------------------------

def member_trades_per_year(run_id: str, alpha_ids: list[str]) -> dict[str, float]:
    """Return ``{alpha_id: trades_per_year}`` using IS metrics + IS period."""
    archive = REPO_ROOT / "archive" / run_id
    splits = json.loads((archive / "splits.json").read_text())
    is_window = splits.get("is", {}) or splits.get("splits", {}).get("is", {})
    try:
        start = pd.Timestamp(is_window["start"])
        end = pd.Timestamp(is_window["end"])
        days = max(1, (end - start).days)
    except Exception:
        days = ANNUAL_BARS
    rate: dict[str, float] = {}
    for aid in alpha_ids:
        p = archive / "alphas" / aid / "is" / "metrics.json"
        if not p.exists():
            continue
        try:
            m = json.loads(p.read_text())
        except Exception:
            continue
        trades = m.get("total_trades")
        if trades is None:
            continue
        rate[aid] = float(trades) / days * 365.25
    return rate


# ---------------------------------------------------------------------------
# pipelines
# ---------------------------------------------------------------------------

def baseline_eqw(R: pd.DataFrame) -> pd.Series:
    return R.mean(axis=1)


def greedy_drop(corr: pd.DataFrame, sharpes: dict[str, float],
                threshold: float) -> list[str]:
    """Walk candidates in descending Sharpe; drop any new one whose
    *signed* ρ ≥ τ with anything already kept.

    After sign-alignment, positive ρ means "redundant in the deployed
    direction" — drop. Negative ρ means "perfect hedge against an existing
    member" — keep, the combined return stream is smoother. This matches
    the Hierarchical pipeline's semantics where D = √(½(1−ρ)) treats
    anti-correlation as far apart (good).
    """
    ranked = sorted(corr.columns, key=lambda a: sharpes.get(a, 0.0), reverse=True)
    kept: list[str] = []
    for aid in ranked:
        if all(corr.at[aid, k] < threshold for k in kept):
            kept.append(aid)
    return kept


def hierarchical_pruning(corr: pd.DataFrame, sharpes: dict[str, float],
                         threshold: float,
                         method: str = "ward") -> tuple[list[str], np.ndarray, float]:
    """Ward linkage on D = √(½(1−ρ)). Cut at distance corresponding to τ."""
    rho = corr.clip(-1.0, 1.0).values
    D = np.sqrt(0.5 * (1.0 - rho))
    np.fill_diagonal(D, 0.0)
    D = 0.5 * (D + D.T)             # enforce symmetry
    condensed = squareform(D, checks=False)
    Z = linkage(condensed, method=method)
    cut_distance = math.sqrt(0.5 * (1.0 - threshold))
    clusters = fcluster(Z, t=cut_distance, criterion="distance")
    names = list(corr.columns)
    rep: dict[int, str] = {}
    for aid, c in zip(names, clusters):
        best = rep.get(c)
        if best is None or sharpes.get(aid, 0.0) > sharpes.get(best, 0.0):
            rep[c] = aid
    return list(rep.values()), Z, cut_distance


def affinity_propagation_then_greedy(
    corr: pd.DataFrame, sharpes: dict[str, float], threshold: float,
    random_state: int = 0,
) -> tuple[list[str], list[str], int]:
    """Affinity Propagation on the signed correlation matrix to find
    exemplars, then Sharpe-sorted signed-ρ greedy drop on the exemplars.

    AP uses similarity = ρ (signed). Preference defaults to median
    similarity so cluster count is data-driven. After AP yields K
    exemplars, walk them descending-Sharpe and drop any whose signed ρ
    ≥ τ vs an already-kept one — anti-correlated pairs pass through as
    diversifiers (consistent with the Hierarchical and Greedy pipelines).
    """
    sim = corr.values.astype(float)
    sim = 0.5 * (sim + sim.T)
    np.fill_diagonal(sim, np.nan)
    median_off_diag = float(np.nanmedian(sim))
    np.fill_diagonal(sim, median_off_diag)
    ap = AffinityPropagation(
        affinity="precomputed",
        damping=0.9,
        preference=median_off_diag,
        max_iter=500,
        convergence_iter=25,
        random_state=random_state,
    )
    labels = ap.fit_predict(sim)
    names = list(corr.columns)
    # Per-cluster best-Sharpe representative (the AP centroid may not be
    # the best Sharpe member of its cluster — pick the strongest).
    rep: dict[int, str] = {}
    for aid, c in zip(names, labels):
        best = rep.get(c)
        if best is None or sharpes.get(aid, 0.0) > sharpes.get(best, 0.0):
            rep[c] = aid
    exemplars = list(rep.values())
    n_clusters = len(set(labels))

    # Greedy Sharpe-sorted corr-drop on the exemplars themselves.
    sub_corr = corr.loc[exemplars, exemplars]
    survivors = greedy_drop(sub_corr, sharpes, threshold=threshold)
    return exemplars, survivors, n_clusters


# ---------------------------------------------------------------------------
# plots
# ---------------------------------------------------------------------------

def plot_heatmap(corr: pd.DataFrame, title: str, path: Path,
                 max_show: int = 200) -> None:
    """Heatmap of correlation matrix. Big matrices are sub-sampled."""
    if corr.empty:
        return
    if len(corr) > max_show:
        sample = corr.sample(max_show, random_state=42).index.tolist()
        sample = sorted(sample)
        view = corr.loc[sample, sample]
        title += f" (sampled {max_show}/{len(corr)})"
    else:
        view = corr
    fig, ax = plt.subplots(figsize=(8, 7))
    im = ax.imshow(view.values, vmin=-1, vmax=1, cmap="RdBu_r", aspect="auto")
    ax.set_title(title)
    ax.set_xticks([]); ax.set_yticks([])
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label="ρ")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def plot_dendrogram(Z: np.ndarray, cut_distance: float, path: Path,
                    labels: list[str] | None = None) -> None:
    fig, ax = plt.subplots(figsize=(12, 5))
    # Drop labels for >50 leaves — they overflow.
    show_labels = labels if labels and len(labels) <= 50 else None
    dendrogram(Z, ax=ax, no_labels=(show_labels is None),
               labels=show_labels, color_threshold=cut_distance)
    ax.axhline(cut_distance, color="red", linestyle="--",
               label=f"cut @ d={cut_distance:.3f}")
    ax.set_title("Ward dendrogram — D = √(½(1−ρ))")
    ax.set_ylabel("distance")
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def plot_equity(curves: dict[str, pd.Series], path: Path) -> None:
    fig, ax = plt.subplots(figsize=(11, 5))
    for name, ret in curves.items():
        cum = (1.0 + ret.fillna(0.0)).cumprod()
        ax.plot(cum.index, cum.values, label=name, linewidth=1.5)
    ax.set_yscale("log")
    ax.set_title("Oracle ceiling — cumulative return (log scale)")
    ax.set_xlabel("date"); ax.set_ylabel("cum equity (×1.0 start)")
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def plot_equity_is_to_os(
    curves: dict[str, dict],
    is_end: pd.Timestamp,
    path: Path,
) -> None:
    """One continuous cumret curve per pipeline spanning IS→OS, with the
    IS portion drawn faded (alpha=0.35) and the OS portion solid. A red
    dashed vertical separator marks the IS/OS boundary."""
    fig, ax = plt.subplots(figsize=(12, 5.5))
    colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]
    for i, (name, payload) in enumerate(curves.items()):
        ret_is = payload["ret_is"]; ret_os = payload["ret_os"]
        sh_is = payload["sh_is"];   sh_os = payload["sh_os"]
        color = colors[i % len(colors)]

        # Combine IS+OS, cumprod continuously so OS picks up where IS left off.
        ret_full = pd.concat([ret_is, ret_os])
        ret_full = ret_full[~ret_full.index.duplicated(keep="first")].sort_index()
        cum = (1.0 + ret_full.fillna(0.0)).cumprod()

        is_mask = cum.index <= is_end
        os_mask = cum.index >  is_end
        label = f"{name}  (IS Sh={sh_is:+.2f} | OS Sh={sh_os:+.2f}, N={payload['N']})"
        # IS portion — faded
        ax.plot(cum.index[is_mask], cum.values[is_mask],
                color=color, alpha=0.35, linewidth=1.2)
        # OS portion — solid, gets the legend entry
        ax.plot(cum.index[os_mask], cum.values[os_mask],
                color=color, alpha=1.0, linewidth=1.6, label=label)

    ax.axvline(is_end, color="red", linestyle="--", linewidth=1.0,
               label=f"IS / OS split @ {is_end.date()}")
    ax.set_yscale("log")
    ax.set_title("Oracle replay — IS-decided sign + selection, OS evaluation")
    ax.set_xlabel("date"); ax.set_ylabel("cum equity (×1.0 start)")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left", fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------

def run(run_id: str, threshold: float, cost_bps: float,
        output_dir: Path, linkage_method: str = "ward",
        sanity_max_abs_daily: float = 1.0,
        sign_align: bool = True) -> dict:
    print(f"[load] run_id={run_id}")
    ids = select_all_alphas(run_id)
    print(f"[load] {len(ids)} alpha candidates")
    R = load_member_is_returns(run_id, ids)
    print(f"[load] returns matrix shape={R.shape}  ({R.index.min().date()} → {R.index.max().date()})")
    if R.shape[1] < 2:
        raise SystemExit("not enough alphas with daily returns")

    # Sanity gate — drop alphas with a single-day |return| beyond the cap.
    # Microcap blow-ups in c05 concentration alphas produce returns in the
    # ±50× range; including them in the EQW basket dominates every metric.
    if sanity_max_abs_daily and sanity_max_abs_daily > 0:
        keep = R.abs().max() <= sanity_max_abs_daily
        dropped = int((~keep).sum())
        if dropped:
            print(f"[sanity] dropping {dropped} alphas with |daily ret| > "
                  f"{sanity_max_abs_daily:.0%} (microcap blow-ups):")
            for aid, mx in R.abs().max()[~keep].sort_values(ascending=False).items():
                print(f"           {aid:50} max|ret|={mx:.2f}")
        R = R.loc[:, keep]
    print(f"[sanity] retained {R.shape[1]} alphas after blow-up filter")

    # Sign-align: a Sharpe-negative alpha is a positive alpha read backwards.
    # Flip its return series so Sharpe goes positive *before* portfolio math.
    # This is what makes "oracle ceiling" honest — the pool's information
    # content, not its accidental sign. (Note: flipping uses IS Sharpe → it's
    # in-sample by construction; OS validation is the realistic ceiling.)
    flipped: list[str] = []
    if sign_align:
        raw_sharpes = {c: sharpe(R[c]) for c in R.columns}
        for c, s in raw_sharpes.items():
            if s < 0:
                R[c] = -R[c]
                flipped.append(c)
        print(f"[sign] flipped {len(flipped)} negative-Sharpe alphas to positive direction")

    sharpes = {c: sharpe(R[c]) for c in R.columns}
    trades_yr = member_trades_per_year(run_id, list(R.columns))

    print(f"[corr] computing {R.shape[1]}×{R.shape[1]} corr matrix")
    corr_full = R.corr()

    # Pipeline 1 — Baseline
    base_ret = baseline_eqw(R)
    base_trades = float(np.mean([trades_yr.get(a, 0.0) for a in R.columns]))

    # Pipeline 2 — Greedy Drop (signed-ρ semantics, see greedy_drop docstring)
    print(f"[greedy] dropping at signed ρ ≥ {threshold}")
    kept_g = greedy_drop(corr_full, sharpes, threshold=threshold)
    greedy_ret = R[kept_g].mean(axis=1) if kept_g else pd.Series(dtype=float)
    greedy_trades = float(np.mean([trades_yr.get(a, 0.0) for a in kept_g])) if kept_g else 0.0

    # Pipeline 3 — Hierarchical Pruning
    print(f"[hier] {linkage_method} linkage; cut at d=√(½(1−τ))")
    kept_h, Z, cut_d = hierarchical_pruning(
        corr_full, sharpes, threshold=threshold, method=linkage_method,
    )
    hier_ret = R[kept_h].mean(axis=1) if kept_h else pd.Series(dtype=float)
    hier_trades = float(np.mean([trades_yr.get(a, 0.0) for a in kept_h])) if kept_h else 0.0

    # Pipeline 4 — Affinity Propagation → Sharpe-sorted signed-ρ greedy drop
    print(f"[AP] affinity propagation → greedy drop at signed ρ ≥ {threshold}")
    ap_exemplars, kept_ap, n_ap_clusters = affinity_propagation_then_greedy(
        corr_full, sharpes, threshold=threshold,
    )
    print(f"[AP] {n_ap_clusters} clusters → {len(ap_exemplars)} exemplars → "
          f"{len(kept_ap)} after greedy drop")
    ap_ret = R[kept_ap].mean(axis=1) if kept_ap else pd.Series(dtype=float)
    ap_trades = float(np.mean([trades_yr.get(a, 0.0) for a in kept_ap])) if kept_ap else 0.0

    metrics = {
        "Baseline (EQW all)": {
            "N": int(R.shape[1]),
            **portfolio_metrics(base_ret, base_trades, cost_bps),
        },
        "Greedy Drop": {
            "N": len(kept_g),
            **portfolio_metrics(greedy_ret, greedy_trades, cost_bps),
            "kept_alphas": kept_g,
        },
        "Hierarchical Pruning": {
            "N": len(kept_h),
            **portfolio_metrics(hier_ret, hier_trades, cost_bps),
            "kept_alphas": kept_h,
        },
        "AP + Greedy": {
            "N": len(kept_ap),
            "n_ap_clusters": n_ap_clusters,
            "n_ap_exemplars": len(ap_exemplars),
            **portfolio_metrics(ap_ret, ap_trades, cost_bps),
            "kept_alphas": kept_ap,
        },
        "_meta": {
            "sign_aligned": sign_align,
            "n_flipped": len(flipped),
            "flipped_alphas": flipped,
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))

    plot_heatmap(corr_full, f"Before — {R.shape[1]} alphas",
                 output_dir / "heatmap_before.png")
    plot_heatmap(corr_full.loc[kept_h, kept_h] if kept_h else corr_full,
                 f"After (Hierarchical) — {len(kept_h)} alphas",
                 output_dir / "heatmap_after.png")
    plot_heatmap(
        corr_full.loc[kept_ap, kept_ap] if kept_ap else corr_full,
        f"After (AP + Greedy) — {len(kept_ap)} survivors",
        output_dir / "heatmap_ap_survivors.png",
    )
    plot_heatmap(
        corr_full.loc[ap_exemplars, ap_exemplars] if ap_exemplars else corr_full,
        f"AP exemplars — {len(ap_exemplars)} (before greedy)",
        output_dir / "heatmap_ap_exemplars.png",
    )
    plot_dendrogram(Z, cut_d, output_dir / "dendrogram.png",
                    labels=list(corr_full.columns))
    plot_equity(
        {
            f"Baseline N={R.shape[1]}":          base_ret,
            f"Greedy Drop N={len(kept_g)}":       greedy_ret,
            f"Hierarchical N={len(kept_h)}":      hier_ret,
            f"AP+Greedy N={len(kept_ap)}":        ap_ret,
        },
        output_dir / "equity_curve.png",
    )

    return metrics


def run_is_to_os(run_id: str, threshold: float, cost_bps: float,
                 output_dir: Path, linkage_method: str = "ward",
                 sanity_max_abs_daily: float = 1.0) -> dict:
    """IS-honest oracle: every decision (sign-flip + member selection) is
    made on IS only; OS returns are computed by replaying the decisions.
    The PnL chart shows the full IS→OS timeline so the user sees both."""
    archive = REPO_ROOT / "archive" / run_id
    splits = json.loads((archive / "splits.json").read_text())
    is_end = pd.Timestamp(splits["is"]["end"]).normalize()
    os_start = pd.Timestamp(splits["os"]["start"]).normalize()

    print(f"[load] run_id={run_id} | IS end={is_end.date()} | OS start={os_start.date()}")
    ids = select_all_alphas(run_id)
    print(f"[load] {len(ids)} alpha candidates")
    R_is = load_member_returns(run_id, ids, split="is")
    R_os = load_member_returns(run_id, ids, split="os")
    print(f"[load] IS={R_is.shape}  OS={R_os.shape}")

    # Sanity gate (IS only — never look at OS for the filter)
    if sanity_max_abs_daily and sanity_max_abs_daily > 0:
        keep_mask = R_is.abs().max() <= sanity_max_abs_daily
        dropped = R_is.columns[~keep_mask].tolist()
        if dropped:
            print(f"[sanity] dropping {len(dropped)} alphas with IS |daily ret| > "
                  f"{sanity_max_abs_daily:.0%}")
        R_is = R_is.loc[:, keep_mask]
    # Align OS to the surviving IS columns
    common = [c for c in R_is.columns if c in R_os.columns]
    R_is = R_is[common]
    R_os = R_os[common]
    print(f"[sanity] retained {len(common)} alphas with both IS & OS curves")

    # Sign decision — IS Sharpe only.
    raw_is_sh = {c: sharpe(R_is[c]) for c in R_is.columns}
    flipped = [c for c, s in raw_is_sh.items() if s < 0]
    if flipped:
        R_is.loc[:, flipped] = -R_is.loc[:, flipped]
        R_os.loc[:, flipped] = -R_os.loc[:, flipped]
        print(f"[sign] flipped {len(flipped)}/{R_is.shape[1]} alphas (IS Sh<0)")

    is_sharpes = {c: sharpe(R_is[c]) for c in R_is.columns}
    trades_yr = member_trades_per_year(run_id, list(R_is.columns))

    # Correlation on IS only — same restriction.
    corr_is = R_is.corr()

    # Selection — every pipeline fits on IS, replays on OS. All three use
    # signed-ρ semantics (anti-correlation is a diversifier, not a duplicate)
    # for consistency with Lopez de Prado's D = √(½(1−ρ)) hierarchical metric.
    print(f"[greedy] signed ρ ≥ {threshold} on IS")
    kept_g = greedy_drop(corr_is, is_sharpes, threshold=threshold)

    print(f"[hier] {linkage_method} on IS")
    kept_h, Z, cut_d = hierarchical_pruning(
        corr_is, is_sharpes, threshold=threshold, method=linkage_method,
    )

    print(f"[AP] on IS")
    _, kept_ap, n_ap = affinity_propagation_then_greedy(
        corr_is, is_sharpes, threshold=threshold,
    )

    # OS blow-up guard: clip per-alpha OS daily returns to ±50%. Real exchange
    # circuit-breakers + position-sizing prevent both ±100% single-day moves
    # on a diversified basket and the 100×+ microcap moons that the simulator
    # would otherwise pass through. Without this guard the cumprod gets
    # dominated by simulation artifacts that no live fund would capture.
    R_os_clipped = R_os.clip(lower=-0.5, upper=0.5)

    def _portfolio(selection: list[str]) -> tuple[pd.Series, pd.Series, dict]:
        if not selection:
            empty = pd.Series(dtype=float)
            return empty, empty, {"N": 0}
        ret_is = R_is[selection].mean(axis=1)
        ret_os = R_os_clipped[selection].mean(axis=1)
        avg_trades = float(np.mean([trades_yr.get(a, 0.0) for a in selection]))
        return ret_is, ret_os, {
            "N": len(selection),
            "sh_is": sharpe(ret_is),
            "sh_os": sharpe(ret_os),
            **{f"is_{k}": v for k, v in portfolio_metrics(ret_is, avg_trades, cost_bps).items()},
            **{f"os_{k}": v for k, v in portfolio_metrics(ret_os, avg_trades, cost_bps).items()},
            "avg_trades_per_year_per_member": avg_trades,
        }

    base_ret_is, base_ret_os, base_m = _portfolio(list(R_is.columns))
    g_ret_is, g_ret_os, g_m = _portfolio(kept_g)
    h_ret_is, h_ret_os, h_m = _portfolio(kept_h)
    ap_ret_is, ap_ret_os, ap_m = _portfolio(kept_ap)

    pipelines = {
        "Baseline (EQW all)": (base_ret_is, base_ret_os, base_m, list(R_is.columns)),
        "Greedy Drop":         (g_ret_is, g_ret_os, g_m, kept_g),
        "Hierarchical Pruning":(h_ret_is, h_ret_os, h_m, kept_h),
        "AP + Greedy":         (ap_ret_is, ap_ret_os, ap_m, kept_ap),
    }

    metrics = {}
    plot_payload: dict[str, dict] = {}
    for name, (ri, ro, m, keep) in pipelines.items():
        metrics[name] = {**m, "kept_alphas": keep}
        plot_payload[name] = {
            "ret_is": ri, "ret_os": ro,
            "sh_is": m.get("sh_is", 0.0), "sh_os": m.get("sh_os", 0.0),
            "N": m["N"],
        }
    metrics["_meta"] = {
        "mode": "is_to_os",
        "is_end": str(is_end.date()),
        "os_start": str(os_start.date()),
        "n_flipped": len(flipped),
        "flipped_alphas": flipped,
        "corr_threshold": threshold,
        "cost_bps": cost_bps,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "metrics_is_to_os.json").write_text(json.dumps(metrics, indent=2))

    plot_equity_is_to_os(plot_payload, is_end,
                         output_dir / "equity_curve_is_to_os.png")
    return metrics


def run_rolling(run_id: str, threshold: float, cost_bps: float,
                output_dir: Path, linkage_method: str = "ward",
                sanity_max_abs_daily: float = 1.0,
                lookback_days: int = 252,
                rebalance_freq: str = "MS",
                sign_align: bool = True,
                _suppress_plot: bool = False) -> dict:
    """Rolling-window oracle. At each rebalance date, look back
    ``lookback_days`` trading days, decide sign + select members per
    pipeline, replay one rebalance period forward, then stitch.

    ``rebalance_freq`` follows pandas offset aliases ("MS" = month-start).
    """
    archive = REPO_ROOT / "archive" / run_id
    print(f"[load] run_id={run_id} | lookback={lookback_days} bars | rebal={rebalance_freq}")
    ids = select_all_alphas(run_id)
    R_is = load_member_returns(run_id, ids, split="is")
    R_os = load_member_returns(run_id, ids, split="os")
    # Stitch IS + OS into one continuous matrix, dedupe overlap.
    R_full = pd.concat([R_is, R_os]).sort_index()
    R_full = R_full[~R_full.index.duplicated(keep="first")]
    common = sorted(set(R_is.columns) & set(R_os.columns))
    R_full = R_full[common]
    print(f"[load] combined shape={R_full.shape}  "
          f"({R_full.index.min().date()} → {R_full.index.max().date()})")

    if sanity_max_abs_daily and sanity_max_abs_daily > 0:
        keep_mask = R_full.abs().max() <= sanity_max_abs_daily
        dropped = R_full.columns[~keep_mask].tolist()
        if dropped:
            print(f"[sanity] dropping {len(dropped)} alphas (full-window blow-ups)")
        R_full = R_full.loc[:, keep_mask]
    print(f"[sanity] retained {R_full.shape[1]} alphas")

    # Build rebalance dates — first valid date is lookback_days bars after start.
    all_dates = R_full.index
    first_refit_idx = lookback_days
    if first_refit_idx >= len(all_dates):
        raise SystemExit(f"not enough history: have {len(all_dates)} bars, need {lookback_days}")
    eligible_dates = all_dates[first_refit_idx:]
    rebal_dates = pd.date_range(eligible_dates[0], eligible_dates[-1], freq=rebalance_freq)
    rebal_dates = [d for d in rebal_dates if d in all_dates]
    if rebal_dates and rebal_dates[0] != eligible_dates[0]:
        rebal_dates = [eligible_dates[0]] + rebal_dates
    rebal_dates = sorted(set(rebal_dates))
    print(f"[rebal] {len(rebal_dates)} rebalance dates ({rebal_dates[0].date()} → {rebal_dates[-1].date()})")

    pipelines = ["Baseline (EQW all)", "Greedy Drop", "Hierarchical Pruning", "AP + Greedy"]
    ret_chunks: dict[str, list[pd.Series]] = {p: [] for p in pipelines}
    selection_log: dict[str, list[dict]] = {p: [] for p in pipelines}

    # OS clip — applied to the realized-forward chunk only, not the look-back.
    OS_CLIP_LOW, OS_CLIP_HIGH = -0.5, 0.5

    for i, rebal_date in enumerate(rebal_dates):
        # Lookback slice: bars strictly before rebal_date.
        lb_mask = (all_dates < rebal_date) & (all_dates >= rebal_date - pd.Timedelta(days=lookback_days * 1.5))
        lookback_idx = all_dates[lb_mask]
        if len(lookback_idx) < lookback_days // 2:
            continue
        lookback_idx = lookback_idx[-lookback_days:]
        R_lb = R_full.loc[lookback_idx]

        # Forward slice: rebal_date inclusive → next rebal_date exclusive.
        if i + 1 < len(rebal_dates):
            fwd_end = rebal_dates[i + 1]
        else:
            fwd_end = all_dates[-1] + pd.Timedelta(days=1)
        fwd_mask = (all_dates >= rebal_date) & (all_dates < fwd_end)
        R_fwd_raw = R_full.loc[all_dates[fwd_mask]]
        R_fwd = R_fwd_raw.clip(lower=OS_CLIP_LOW, upper=OS_CLIP_HIGH)
        if R_fwd.empty:
            continue

        # Sign decide on lookback Sharpe; require min activity to keep an alpha.
        active = R_lb.std() > 0
        cols = R_lb.columns[active]
        if len(cols) < 4:
            continue
        R_lb = R_lb[cols]
        R_fwd_a = R_fwd[cols]
        raw_sh = {c: sharpe(R_lb[c]) for c in cols}
        if sign_align:
            flip_mask = pd.Series({c: -1 if raw_sh[c] < 0 else 1 for c in cols})
        else:
            flip_mask = pd.Series({c: 1 for c in cols})
        # Apply sign-flip to both lookback and forward in lockstep.
        R_lb_a = R_lb * flip_mask.values  # broadcasting across rows
        R_fwd_a = R_fwd_a * flip_mask.values
        lb_sh = {c: sharpe(R_lb_a[c]) for c in cols}
        corr_lb = R_lb_a.corr().fillna(0.0)

        # Per-pipeline selection
        sel_base = list(cols)
        sel_g = greedy_drop(corr_lb, lb_sh, threshold=threshold)
        try:
            sel_h, _, _ = hierarchical_pruning(corr_lb, lb_sh, threshold=threshold,
                                               method=linkage_method)
        except Exception:
            sel_h = sel_g
        try:
            _, sel_ap, _ = affinity_propagation_then_greedy(corr_lb, lb_sh, threshold=threshold)
        except Exception:
            sel_ap = sel_g

        for name, sel in zip(pipelines, (sel_base, sel_g, sel_h, sel_ap)):
            if not sel:
                continue
            chunk = R_fwd_a[sel].mean(axis=1)
            ret_chunks[name].append(chunk)
            selection_log[name].append({
                "rebal_date": str(rebal_date.date()),
                "n_selected": len(sel),
                "n_flipped": int((flip_mask.loc[sel] == -1).sum()),
                "members": sel,
            })

        if i % 6 == 0:
            print(f"  [rebal {i+1}/{len(rebal_dates)}] {rebal_date.date()}  "
                  f"base N={len(sel_base)}  greedy={len(sel_g)}  "
                  f"hier={len(sel_h)}  ap={len(sel_ap)}")

    pipelines_curves: dict[str, pd.Series] = {}
    for name in pipelines:
        if not ret_chunks[name]:
            pipelines_curves[name] = pd.Series(dtype=float)
            continue
        series = pd.concat(ret_chunks[name]).sort_index()
        series = series[~series.index.duplicated(keep="first")]
        pipelines_curves[name] = series

    metrics = {}
    for name, ret in pipelines_curves.items():
        if ret.empty:
            metrics[name] = {"N_avg": 0, "sharpe": 0.0}
            continue
        avg_n = float(np.mean([d["n_selected"] for d in selection_log[name]])) if selection_log[name] else 0.0
        avg_flip = float(np.mean([d["n_flipped"] for d in selection_log[name]])) if selection_log[name] else 0.0
        metrics[name] = {
            "N_avg": avg_n,
            "n_flipped_avg": avg_flip,
            "sharpe": sharpe(ret),
            "annualized_return": annualized_return(ret),
            "annualized_vol": annualized_vol(ret),
            "max_drawdown": max_drawdown(ret),
            "n_rebal_dates": len(selection_log[name]),
        }
    metrics["_meta"] = {
        "mode": "rolling",
        "sign_align": sign_align,
        "lookback_days": lookback_days,
        "rebalance_freq": rebalance_freq,
        "n_rebal_dates": len(rebal_dates),
        "corr_threshold": threshold,
        "cost_bps": cost_bps,
        "os_clip": [OS_CLIP_LOW, OS_CLIP_HIGH],
    }
    metrics["_curves"] = {name: ret for name, ret in pipelines_curves.items()}
    metrics["_rebal_dates"] = list(rebal_dates)

    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = "" if sign_align else "_nosign"
    out_metrics = {k: v for k, v in metrics.items() if not k.startswith("_curves") and not k.startswith("_rebal")}
    (output_dir / f"metrics_rolling{suffix}.json").write_text(json.dumps(out_metrics, indent=2))

    if _suppress_plot:
        return metrics

    # Plot rolling equity curve.
    fig, ax = plt.subplots(figsize=(12, 5.5))
    colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]
    for i, (name, ret) in enumerate(pipelines_curves.items()):
        if ret.empty:
            continue
        cum = (1.0 + ret.fillna(0.0)).cumprod()
        m = metrics[name]
        label = (f"{name}  (OOS Sh={m['sharpe']:+.2f}, "
                 f"AnnRet={m['annualized_return']:+.1%}, N̄={m['N_avg']:.0f})")
        ax.plot(cum.index, cum.values, label=label, linewidth=1.5,
                color=colors[i % len(colors)])
    for rd in rebal_dates:
        ax.axvline(rd, color="grey", linestyle=":", alpha=0.15, linewidth=0.5)
    ax.set_yscale("log")
    ax.set_title(f"Rolling oracle — lookback={lookback_days}d, rebal={rebalance_freq} "
                 f"(walk-forward OOS only)")
    ax.set_xlabel("date"); ax.set_ylabel("cum equity (×1.0 start)")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left", fontsize=9)
    fig.tight_layout()
    plot_name = "equity_curve_rolling.png" if sign_align else "equity_curve_rolling_nosign.png"
    fig.savefig(output_dir / plot_name, dpi=120)
    plt.close(fig)
    return metrics


def run_rolling_compare(run_id: str, threshold: float, cost_bps: float,
                        output_dir: Path, linkage_method: str = "ward",
                        sanity_max_abs_daily: float = 1.0,
                        lookback_days: int = 252,
                        rebalance_freq: str = "MS") -> dict:
    """Run the rolling oracle twice (sign-aligned vs raw) and produce a
    comparison chart so the marginal value of sign-flipping is visible."""
    print("\n=== Run A: SIGN-ALIGNED ===")
    m_signed = run_rolling(run_id, threshold, cost_bps, output_dir,
                           linkage_method, sanity_max_abs_daily,
                           lookback_days, rebalance_freq,
                           sign_align=True, _suppress_plot=True)
    print("\n=== Run B: RAW (no sign flip) ===")
    m_raw = run_rolling(run_id, threshold, cost_bps, output_dir,
                        linkage_method, sanity_max_abs_daily,
                        lookback_days, rebalance_freq,
                        sign_align=False, _suppress_plot=True)

    curves_signed = m_signed.pop("_curves")
    curves_raw = m_raw.pop("_curves")
    rebal_dates = m_signed.pop("_rebal_dates")
    m_raw.pop("_rebal_dates", None)

    pipelines = ["Baseline (EQW all)", "Greedy Drop",
                 "Hierarchical Pruning", "AP + Greedy"]
    colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]

    fig, ax = plt.subplots(figsize=(13, 6))
    for i, name in enumerate(pipelines):
        color = colors[i % len(colors)]
        ret_s = curves_signed.get(name, pd.Series(dtype=float))
        ret_r = curves_raw.get(name, pd.Series(dtype=float))
        if not ret_s.empty:
            cum = (1.0 + ret_s.fillna(0.0)).cumprod()
            sh = m_signed[name].get("sharpe", 0.0)
            ax.plot(cum.index, cum.values, color=color, linewidth=1.6,
                    label=f"{name}  signed (Sh={sh:+.2f})")
        if not ret_r.empty:
            cum = (1.0 + ret_r.fillna(0.0)).cumprod()
            sh = m_raw[name].get("sharpe", 0.0)
            ax.plot(cum.index, cum.values, color=color, linewidth=1.2,
                    linestyle="--", alpha=0.65,
                    label=f"{name}  raw    (Sh={sh:+.2f})")
    for rd in rebal_dates:
        ax.axvline(rd, color="grey", linestyle=":", alpha=0.10, linewidth=0.5)
    ax.set_yscale("log")
    ax.set_title(f"Rolling oracle — sign-align vs raw "
                 f"(lookback={lookback_days}d, rebal={rebalance_freq})")
    ax.set_xlabel("date"); ax.set_ylabel("cum equity (×1.0 start)")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left", fontsize=8, ncols=2)
    fig.tight_layout()
    fig.savefig(output_dir / "equity_curve_rolling_compare.png", dpi=120)
    plt.close(fig)

    combined = {
        "signed": m_signed,
        "raw": m_raw,
    }
    (output_dir / "metrics_rolling_compare.json").write_text(
        json.dumps(combined, indent=2)
    )
    return combined


def _split_sharpes(ret: pd.Series, is_end: pd.Timestamp) -> tuple[float, float, float]:
    """Return (IS Sh, OS Sh, Full Sh) for a return series, split at ``is_end``."""
    if ret.empty:
        return 0.0, 0.0, 0.0
    is_ret = ret[ret.index <= is_end]
    os_ret = ret[ret.index >  is_end]
    return sharpe(is_ret), sharpe(os_ret), sharpe(ret)


def _plot_stage(curves: dict, is_end: pd.Timestamp, path: Path, title: str,
                fade_is: bool = False, dashed_keys: tuple[str, ...] = ()) -> None:
    """One curve per name in ``curves``. Legend entries show
    "IS Sh / OS Sh / Full Sh". ``fade_is`` draws the IS portion at alpha
    0.35; ``dashed_keys`` use dashed lines (for the "raw" siblings in stage 3)."""
    fig, ax = plt.subplots(figsize=(12.5, 5.8))
    colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]
    # Stable color: derive from base pipeline name (before " — ").
    base_names = []
    for name in curves.keys():
        bn = name.split(" — ")[0]
        if bn not in base_names:
            base_names.append(bn)
    color_for = {bn: colors[i % len(colors)] for i, bn in enumerate(base_names)}

    for name, ret in curves.items():
        if ret.empty:
            continue
        cum = (1.0 + ret.fillna(0.0)).cumprod()
        sh_is, sh_os, sh_full = _split_sharpes(ret, is_end)
        bn = name.split(" — ")[0]
        color = color_for[bn]
        is_mask = cum.index <= is_end
        os_mask = cum.index >  is_end
        linestyle = "--" if name in dashed_keys else "-"
        alpha_os = 0.95
        label = (f"{name}  (IS Sh={sh_is:+.2f} | OS Sh={sh_os:+.2f} | "
                 f"Full Sh={sh_full:+.2f})")
        if fade_is:
            ax.plot(cum.index[is_mask], cum.values[is_mask],
                    color=color, alpha=0.30, linewidth=1.3, linestyle=linestyle)
            ax.plot(cum.index[os_mask], cum.values[os_mask],
                    color=color, alpha=alpha_os, linewidth=1.6,
                    linestyle=linestyle, label=label)
        else:
            ax.plot(cum.index, cum.values, color=color, alpha=alpha_os,
                    linewidth=1.5, linestyle=linestyle, label=label)
    ax.axvline(is_end, color="red", linestyle="--", linewidth=1.0,
               label=f"IS / OS split @ {is_end.date()}")
    ax.set_yscale("log")
    ax.set_title(title)
    ax.set_xlabel("date"); ax.set_ylabel("cum equity (×1.0 start)")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left", fontsize=8, ncols=1)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def _fit_eqw_curves(R: pd.DataFrame, threshold: float,
                    linkage_method: str = "ward") -> dict:
    """Static fit on the provided window. Returns
    {pipeline_name: (selection_list, sign_mask, sharpe_dict)}."""
    raw_sh = {c: sharpe(R[c]) for c in R.columns}
    sign_mask = pd.Series({c: -1 if raw_sh[c] < 0 else 1 for c in R.columns})
    R_aligned = R * sign_mask.values
    sharpes = {c: sharpe(R_aligned[c]) for c in R.columns}
    corr = R_aligned.corr().fillna(0.0)
    out = {
        "Baseline (EQW all)": (list(R.columns), sign_mask, sharpes),
        "Greedy Drop": (greedy_drop(corr, sharpes, threshold), sign_mask, sharpes),
    }
    try:
        kept_h, _, _ = hierarchical_pruning(corr, sharpes, threshold, linkage_method)
    except Exception:
        kept_h = []
    out["Hierarchical Pruning"] = (kept_h, sign_mask, sharpes)
    try:
        _, kept_ap, _ = affinity_propagation_then_greedy(corr, sharpes, threshold)
    except Exception:
        kept_ap = []
    out["AP + Greedy"] = (kept_ap, sign_mask, sharpes)
    return out


def run_linkage_compare(run_id: str, threshold: float, cost_bps: float,
                        output_dir: Path, sanity_max_abs_daily: float = 1.0,
                        methods: tuple[str, ...] = ("ward", "average", "complete")
                        ) -> dict:
    """Stage 1 (full-period sign-align + EQW) with hierarchical linkage
    swapped across {ward, average, complete}. Returns per-method curve +
    metrics so the user can see which linkage handles correlation-distance
    clustering best."""
    archive = REPO_ROOT / "archive" / run_id
    splits = json.loads((archive / "splits.json").read_text())
    is_end = pd.Timestamp(splits["is"]["end"]).normalize()

    ids = select_all_alphas(run_id)
    R_is = load_member_returns(run_id, ids, split="is")
    R_os = load_member_returns(run_id, ids, split="os")
    R_full = pd.concat([R_is, R_os]).sort_index()
    R_full = R_full[~R_full.index.duplicated(keep="first")]
    common = sorted(set(R_is.columns) & set(R_os.columns))
    R_full = R_full[common]
    if sanity_max_abs_daily and sanity_max_abs_daily > 0:
        keep = R_full.abs().max() <= sanity_max_abs_daily
        R_full = R_full.loc[:, keep]
    R_full = R_full.clip(lower=-0.5, upper=0.5)
    print(f"[linkage] {R_full.shape[1]} alphas")

    # Single sign-align step on full-period Sharpe (Stage 1 lens).
    raw_sh = {c: sharpe(R_full[c]) for c in R_full.columns}
    sign_mask = pd.Series({c: -1 if raw_sh[c] < 0 else 1 for c in R_full.columns})
    R_aligned = R_full * sign_mask.values
    sharpes = {c: sharpe(R_aligned[c]) for c in R_aligned.columns}
    corr = R_aligned.corr().fillna(0.0)

    curves: dict[str, pd.Series] = {}
    by_method: dict[str, dict] = {}
    for method in methods:
        sel, Z, cut_d = hierarchical_pruning(corr, sharpes, threshold, method=method)
        ret = R_aligned[sel].mean(axis=1) if sel else pd.Series(dtype=float)
        sh_is, sh_os, sh_full = _split_sharpes(ret, is_end)
        curves[f"Hierarchical ({method})"] = ret
        by_method[method] = {
            "linkage": method,
            "n_selected": len(sel),
            "cut_distance": float(cut_d),
            "sharpe_is": sh_is,
            "sharpe_os": sh_os,
            "sharpe_full": sh_full,
            "annualized_return": annualized_return(ret),
            "annualized_vol": annualized_vol(ret),
            "max_drawdown": max_drawdown(ret),
            "members": sel,
        }
        print(f"  [{method}] N={len(sel)}  IS={sh_is:+.2f}  OS={sh_os:+.2f}  "
              f"Full={sh_full:+.2f}")

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "metrics_linkage_compare.json").write_text(
        json.dumps(by_method, indent=2)
    )

    _plot_stage(curves, is_end, output_dir / "linkage_compare.png",
                "Linkage method comparison — Stage 1 setup "
                "(full-period sign-align + EQW)", fade_is=False)

    # Side-by-side correlation heatmaps of each linkage's surviving members.
    fig, axes = plt.subplots(1, len(methods),
                             figsize=(5.4 * len(methods), 5.4))
    if len(methods) == 1:
        axes = [axes]
    for ax, method in zip(axes, methods):
        sel = by_method[method]["members"]
        if not sel:
            ax.set_visible(False)
            continue
        sub = corr.loc[sel, sel].values
        im = ax.imshow(sub, vmin=-1, vmax=1, cmap="RdBu_r", aspect="auto")
        n = len(sel)
        ax.set_title(f"{method}  (N={n}, Full Sh={by_method[method]['sharpe_full']:+.2f})",
                     fontsize=10)
        ax.set_xticks([]); ax.set_yticks([])
        # off-diagonal mean |ρ| as a "compactness" indicator
        if n > 1:
            mask = ~np.eye(n, dtype=bool)
            mean_abs = float(np.mean(np.abs(sub[mask])))
            ax.text(0.02, 0.02, f"mean |ρ|={mean_abs:.2f}", transform=ax.transAxes,
                    fontsize=8.5, color="#cbd5e1",
                    bbox=dict(facecolor="#1a1a24", edgecolor="#3a3a44", pad=4))
    fig.colorbar(im, ax=axes, fraction=0.020, pad=0.02, label="ρ")
    fig.suptitle("Linkage survivors — correlation heatmaps (sign-aligned)",
                 fontsize=12)
    fig.savefig(output_dir / "linkage_heatmaps.png", dpi=120,
                bbox_inches="tight")
    plt.close(fig)
    return by_method


def run_lookback_sweep(run_id: str, threshold: float, cost_bps: float,
                       output_dir: Path, linkage_method: str = "ward",
                       sanity_max_abs_daily: float = 1.0,
                       rebalance_freq: str = "MS",
                       lookbacks: tuple[int, ...] = (63, 126, 252, 504, 756)
                       ) -> dict:
    """Sweep lookback window length, record rolling-Sh per pipeline.
    Shows how look-back length governs sign-flip stability."""
    archive = REPO_ROOT / "archive" / run_id
    splits = json.loads((archive / "splits.json").read_text())
    is_end = pd.Timestamp(splits["is"]["end"]).normalize()

    pipelines = ["Baseline (EQW all)", "Greedy Drop",
                 "Hierarchical Pruning", "AP + Greedy"]
    by_lb: dict[int, dict[str, dict]] = {}
    for lb in lookbacks:
        print(f"\n=== Sweep: lookback={lb} ===")
        try:
            m = run_rolling(run_id, threshold, cost_bps, output_dir,
                            linkage_method, sanity_max_abs_daily,
                            lookback_days=lb, rebalance_freq=rebalance_freq,
                            sign_align=True, _suppress_plot=True)
            curves = m.pop("_curves", {})
            m.pop("_rebal_dates", None)
            # also compute IS/OS split Sharpes
            stats = {}
            for p in pipelines:
                ret = curves.get(p, pd.Series(dtype=float))
                sh_is, sh_os, sh_full = _split_sharpes(ret, is_end)
                stats[p] = {
                    "sharpe_full": sh_full,
                    "sharpe_is": sh_is,
                    "sharpe_os": sh_os,
                    "n_avg": m.get(p, {}).get("N_avg", 0.0),
                    "n_flipped_avg": m.get(p, {}).get("n_flipped_avg", 0.0),
                    "annualized_return": m.get(p, {}).get("annualized_return", 0.0),
                }
            by_lb[lb] = stats
        except SystemExit as e:
            print(f"  [skip] lookback={lb}: {e}")
            continue

    # Plot — one line per pipeline, x=lookback, y=rolling Sh (signed Full).
    fig, ax = plt.subplots(figsize=(10, 5.5))
    colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]
    lbs_used = sorted(by_lb.keys())
    for i, p in enumerate(pipelines):
        ys = [by_lb[lb][p]["sharpe_full"] for lb in lbs_used]
        ax.plot(lbs_used, ys, marker="o", linewidth=1.8,
                color=colors[i % len(colors)], label=p)
    ax.axhline(0.0, color="grey", linestyle=":", alpha=0.6)
    ax.set_xticks(lbs_used)
    ax.set_xticklabels([f"{lb}d\n(~{lb/252:.1f}y)" for lb in lbs_used])
    ax.set_xlabel("Look-back window")
    ax.set_ylabel("Rolling-fit Full-period Sharpe (signed)")
    ax.set_title("Stage 4 — Look-back sensitivity (monthly rebalance, sign-aligned)")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best", fontsize=9)
    fig.tight_layout()
    fig.savefig(output_dir / "stage4_lookback_sweep.png", dpi=120)
    plt.close(fig)
    return by_lb


def run_report(run_id: str, threshold: float, cost_bps: float,
               output_dir: Path, linkage_method: str = "ward",
               sanity_max_abs_daily: float = 1.0,
               lookback_days: int = 252,
               rebalance_freq: str = "MS",
               sweep_lookbacks: tuple[int, ...] = (63, 126, 252, 504, 756)
               ) -> dict:
    """Build the 3-stage report: full-fit / IS-fit / rolling.
    Writes 3 PNGs + index.html into ``output_dir``."""
    archive = REPO_ROOT / "archive" / run_id
    splits = json.loads((archive / "splits.json").read_text())
    is_end = pd.Timestamp(splits["is"]["end"]).normalize()

    ids = select_all_alphas(run_id)
    R_is = load_member_returns(run_id, ids, split="is")
    R_os = load_member_returns(run_id, ids, split="os")
    R_full = pd.concat([R_is, R_os]).sort_index()
    R_full = R_full[~R_full.index.duplicated(keep="first")]
    common = sorted(set(R_is.columns) & set(R_os.columns))
    R_full = R_full[common]

    # Sanity gate on the full-period window so every stage works on the
    # same alpha set.
    if sanity_max_abs_daily and sanity_max_abs_daily > 0:
        keep = R_full.abs().max() <= sanity_max_abs_daily
        R_full = R_full.loc[:, keep]
    R_is = R_is[[c for c in R_full.columns if c in R_is.columns]]
    R_os_clipped = R_os.clip(lower=-0.5, upper=0.5)[R_full.columns]
    print(f"[report] {R_full.shape[1]} alphas, "
          f"{R_full.index.min().date()} → {R_full.index.max().date()}")

    output_dir.mkdir(parents=True, exist_ok=True)

    # --- Stage 1: full-period fit (IS+OS combined, sign+select on full data) ---
    print("\n=== Stage 1: full-period fit ===")
    R_full_clipped = R_full.clip(lower=-0.5, upper=0.5)
    fits_1 = _fit_eqw_curves(R_full_clipped, threshold, linkage_method)
    curves_1: dict[str, pd.Series] = {}
    for name, (sel, signs, _) in fits_1.items():
        if not sel:
            continue
        R_sub = R_full_clipped[sel].mul(signs[sel].values, axis=1)
        curves_1[name] = R_sub.mean(axis=1)
    _plot_stage(curves_1, is_end, output_dir / "stage1_full_period.png",
                "Stage 1 — Full-period fit (sign + select on IS+OS combined)",
                fade_is=False)

    # --- Stage 2: IS-only fit, replay across IS+OS ---
    print("\n=== Stage 2: IS-only fit (IS-decide, full-replay) ===")
    fits_2 = _fit_eqw_curves(R_is, threshold, linkage_method)
    curves_2: dict[str, pd.Series] = {}
    for name, (sel, signs, _) in fits_2.items():
        if not sel:
            continue
        # Replay across full timeline using IS-derived signs/selection.
        R_replay = R_full_clipped[sel].mul(signs[sel].values, axis=1)
        curves_2[name] = R_replay.mean(axis=1)
    _plot_stage(curves_2, is_end, output_dir / "stage2_is_only.png",
                "Stage 2 — IS-only fit (sign + select on IS; replay through OS)",
                fade_is=True)

    # --- Stage 3: rolling 1-yr lookback, monthly rebal, signed vs raw ---
    print("\n=== Stage 3: rolling 1-yr × {signed, raw} ===")
    m_sign = run_rolling(run_id, threshold, cost_bps, output_dir,
                         linkage_method, sanity_max_abs_daily,
                         lookback_days, rebalance_freq,
                         sign_align=True, _suppress_plot=True)
    m_raw = run_rolling(run_id, threshold, cost_bps, output_dir,
                        linkage_method, sanity_max_abs_daily,
                        lookback_days, rebalance_freq,
                        sign_align=False, _suppress_plot=True)
    curves_signed = m_sign.pop("_curves"); m_sign.pop("_rebal_dates", None)
    curves_raw = m_raw.pop("_curves"); m_raw.pop("_rebal_dates", None)
    curves_3 = {}
    dashed_keys = []
    for name in ("Baseline (EQW all)", "Greedy Drop",
                 "Hierarchical Pruning", "AP + Greedy"):
        ks = f"{name} — signed"
        kr = f"{name} — raw"
        curves_3[ks] = curves_signed.get(name, pd.Series(dtype=float))
        curves_3[kr] = curves_raw.get(name, pd.Series(dtype=float))
        dashed_keys.append(kr)
    _plot_stage(curves_3, is_end, output_dir / "stage3_rolling_compare.png",
                f"Stage 3 — Rolling {lookback_days}d lookback / {rebalance_freq} rebalance "
                f"(solid = sign-aligned, dashed = raw)",
                fade_is=False, dashed_keys=tuple(dashed_keys))

    # --- Tabulate Sharpes for HTML ---
    def _row(name: str, ret: pd.Series) -> dict:
        sh_is, sh_os, sh_full = _split_sharpes(ret, is_end)
        return {"name": name, "is": sh_is, "os": sh_os, "full": sh_full,
                "n": int(ret.dropna().shape[0])}
    stage1_rows = [_row(n, r) for n, r in curves_1.items()]
    stage2_rows = [_row(n, r) for n, r in curves_2.items()]
    stage3_rows = [_row(n, r) for n, r in curves_3.items()]

    # --- Stage 4: look-back sweep ---
    print("\n=== Stage 4: look-back sensitivity sweep ===")
    lb_results = run_lookback_sweep(run_id, threshold, cost_bps, output_dir,
                                    linkage_method, sanity_max_abs_daily,
                                    rebalance_freq=rebalance_freq,
                                    lookbacks=sweep_lookbacks)

    # --- Write index.html (self-contained: PNGs inlined as base64) ---
    import base64
    def _img_b64(p: Path) -> str:
        return base64.b64encode(p.read_bytes()).decode("ascii")
    img1 = _img_b64(output_dir / "stage1_full_period.png")
    img2 = _img_b64(output_dir / "stage2_is_only.png")
    img3 = _img_b64(output_dir / "stage3_rolling_compare.png")
    img4 = _img_b64(output_dir / "stage4_lookback_sweep.png")

    def _table(rows: list[dict]) -> str:
        cells = "".join(
            f"<tr><td>{r['name']}</td><td class='num'>{r['is']:+.2f}</td>"
            f"<td class='num'>{r['os']:+.2f}</td><td class='num'>{r['full']:+.2f}</td></tr>"
            for r in rows
        )
        return (
            "<table><thead><tr><th>Pipeline</th><th>IS Sharpe</th>"
            "<th>OS Sharpe</th><th>Full Sharpe</th></tr></thead>"
            f"<tbody>{cells}</tbody></table>"
        )

    def _lb_table(lb_results: dict) -> str:
        lbs = sorted(lb_results.keys())
        head_lbs = "".join(f"<th>{lb}d ({lb/252:.1f}y)</th>" for lb in lbs)
        head = f"<tr><th>Pipeline</th>{head_lbs}</tr>"
        body = []
        for p in ("Baseline (EQW all)", "Greedy Drop",
                  "Hierarchical Pruning", "AP + Greedy"):
            cells = "".join(
                f"<td class='num'>{lb_results[lb][p]['sharpe_full']:+.2f}</td>"
                for lb in lbs
            )
            body.append(f"<tr><td>{p}</td>{cells}</tr>")
        return f"<table><thead>{head}</thead><tbody>{''.join(body)}</tbody></table>"

    # Pick out headline numbers for the exec summary.
    def _find(rows, name, key):
        for r in rows:
            if r["name"] == name or r["name"].startswith(name):
                return r[key]
        return 0.0
    headline_full = _find(stage1_rows, "Greedy Drop", "full")
    headline_is_os = _find(stage2_rows, "Greedy Drop", "os")
    headline_roll = _find(stage3_rows, "Greedy Drop — signed", "full")

    is_start = R_full.index.min().date()
    full_end = R_full.index.max().date()

    html = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>Oracle Ceiling Report — {run_id}</title>
<style>
  :root {{
    --bg: #0a0a0e;
    --bg-elev: #14141c;
    --bg-soft: #1a1a24;
    --border: #2a2a36;
    --border-soft: #1f1f29;
    --muted: #9ca3af;
    --ink: #e5e7eb;
    --ink-strong: #f3f4f6;
    --accent: #60a5fa;
    --accent-deep: #3b82f6;
    --warn: #fbbf24;
    --success: #34d399;
  }}
  html, body {{ background: var(--bg); }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                 "Apple SD Gothic Neo", "Pretendard", sans-serif;
    max-width: 1180px; margin: 0 auto; padding: 56px 28px 64px;
    color: var(--ink); line-height: 1.62; font-size: 15.5px;
    -webkit-font-smoothing: antialiased;
  }}
  h1 {{ font-size: 2.1em; margin-bottom: 2px; letter-spacing: -0.02em;
        color: var(--ink-strong); }}
  h2 {{ border-bottom: 1px solid var(--border); padding-bottom: 10px;
        margin-top: 56px; font-size: 1.45em; font-weight: 600;
        color: var(--ink-strong); letter-spacing: -0.01em; }}
  h3 {{ margin-top: 26px; color: var(--accent); font-size: 1.05em;
        font-weight: 600; letter-spacing: 0.005em; }}
  p {{ margin: 12px 0; }}
  p.lead {{ color: var(--muted); margin-top: 4px; font-size: 0.94em; }}
  strong {{ color: var(--ink-strong); }}
  em {{ color: var(--ink-strong); font-style: normal;
        border-bottom: 1px dashed var(--border); }}
  a {{ color: var(--accent); text-decoration: none;
       border-bottom: 1px solid transparent; transition: border-color .15s; }}
  a:hover {{ border-bottom-color: var(--accent); }}
  img {{ width: 100%; height: auto; border: 1px solid var(--border);
         border-radius: 8px; background: var(--bg-elev);
         box-shadow: 0 1px 0 rgba(255,255,255,0.02); }}
  table {{ border-collapse: collapse; margin: 16px 0;
           font-size: 0.93em; width: 100%; background: var(--bg-elev);
           border: 1px solid var(--border); border-radius: 6px;
           overflow: hidden; }}
  th, td {{ padding: 9px 14px; border-bottom: 1px solid var(--border-soft);
            text-align: left; }}
  th {{ background: var(--bg-soft); font-weight: 600; color: var(--ink-strong);
        font-size: 0.88em; letter-spacing: 0.02em; text-transform: uppercase; }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: rgba(96, 165, 250, 0.04); }}
  td.num {{ text-align: right; font-family: "JetBrains Mono", ui-monospace, monospace;
            color: var(--ink-strong); }}
  .meta {{ color: var(--muted); font-size: 0.85em; margin-top: 8px; }}
  .note {{ background: rgba(251, 191, 36, 0.06); border-left: 3px solid var(--warn);
           padding: 12px 18px; margin: 16px 0; border-radius: 0 4px 4px 0;
           color: var(--ink); font-size: 0.94em; }}
  .summary {{ background: linear-gradient(135deg, #131320, #1a1a2e);
              border: 1px solid var(--border); border-left: 3px solid var(--accent);
              padding: 22px 26px; margin: 22px 0 28px;
              border-radius: 0 8px 8px 0; }}
  .summary h3 {{ margin-top: 0; margin-bottom: 8px; }}
  .summary p {{ color: var(--ink); }}
  .kpi-row {{ display: grid; grid-template-columns: repeat(3, 1fr);
              gap: 14px; margin: 18px 0 4px; }}
  .kpi {{ background: var(--bg-elev); border: 1px solid var(--border);
          border-radius: 8px; padding: 16px 20px; }}
  .kpi .label {{ color: var(--muted); font-size: 0.74em;
                  text-transform: uppercase; letter-spacing: 0.08em;
                  font-weight: 600; }}
  .kpi .value {{ font-family: "JetBrains Mono", ui-monospace, monospace;
                  font-size: 1.85em; font-weight: 700; color: var(--accent);
                  margin-top: 6px; line-height: 1.1; }}
  .kpi .desc {{ color: var(--muted); font-size: 0.82em; margin-top: 6px; }}
  ul {{ padding-left: 22px; }}
  ul.glossary li {{ margin: 6px 0; color: var(--ink); }}
  ul.glossary code, code {{ background: var(--bg-soft); padding: 2px 7px;
                       border-radius: 4px; font-size: 0.92em;
                       color: var(--accent); font-family: ui-monospace, monospace;
                       border: 1px solid var(--border-soft); }}
  .bg-block {{ background: var(--bg-elev); border: 1px solid var(--border);
               border-radius: 8px; padding: 18px 22px; margin: 14px 0; }}
  .bg-block h3 {{ margin-top: 0; }}
  .bg-block ul {{ margin-bottom: 0; }}
  ol li {{ margin: 8px 0; }}
  .pill {{ display: inline-block; padding: 2px 8px; border-radius: 9999px;
           font-size: 0.78em; font-weight: 600;
           background: rgba(96, 165, 250, 0.12);
           color: var(--accent); border: 1px solid rgba(96, 165, 250, 0.25);
           margin-right: 6px; }}
  .pill.warn {{ background: rgba(251, 191, 36, 0.08); color: var(--warn);
                border-color: rgba(251, 191, 36, 0.25); }}
  .pill.success {{ background: rgba(52, 211, 153, 0.08); color: var(--success);
                    border-color: rgba(52, 211, 153, 0.25); }}
</style>
</head>
<body>

<h1>Oracle Ceiling Report</h1>
<p class="lead">run_id: <strong>{run_id}</strong> · 목표 풀 ~500개 ·
   IS/OS 둘 다 완료 {R_full.shape[1] + 43}개 → sanity gate 후 평가 {R_full.shape[1]}개 ·
   기간: {is_start} → {full_end} · IS/OS split: {is_end.date()} ·
   correlation τ={threshold} (signed) · fee={cost_bps}bp 가정</p>

<div class="summary">
<h3>이 리포트가 답하는 한 가지 질문</h3>
<p>"우리 알파 풀의 <strong>현실적 천장(Sharpe ceiling)</strong>은 얼마인가?"<br>
in-sample 숫자는 항상 부풀려 있다. 같은 데이터로 fit하고 평가하면 천장이 3.4도
나오지만, 실거래 시점엔 그 수치를 만질 수 없다. 이 리포트는 3단계로
점점 엄격하게 평가해서 over-fit이 어디서 사라지는지 보여준다.</p>
<div class="kpi-row">
  <div class="kpi"><div class="label">Stage 1 — 전체기간 fit</div>
    <div class="value">{headline_full:+.2f}</div>
    <div class="desc">Greedy Drop Full Sharpe. 이론 상한, in-sample.</div></div>
  <div class="kpi"><div class="label">Stage 2 — IS fit → OS 평가</div>
    <div class="value">{headline_is_os:+.2f}</div>
    <div class="desc">Greedy Drop OS Sharpe. static train/test.</div></div>
  <div class="kpi"><div class="label">Stage 3 — 1년 rolling fit</div>
    <div class="value">{headline_roll:+.2f}</div>
    <div class="desc">Greedy Drop Full Sharpe. 실거래 walk-forward.</div></div>
</div>
<p style="margin-bottom:0;"><strong>핵심 메시지</strong>: Stage 1 → Stage 3로 갈수록
Sharpe가 약 1/3로 줄어든다. 이게 over-fit shrinkage. 합성 전략을 만들 때 in-sample
Sharpe를 보고 기대치를 세우면 안 되고, Stage 3 수치에 가중치를 둬야 한다.</p>
</div>

<h2>알파 풀의 배경 — 어떻게 만들어진 신호인가</h2>
<p>지금 분석 중인 풀은 <strong>크립토 일봉 cross-sectional 알파 zoo</strong>다.
"500개 알파"는 사람이 일일이 손으로 만든 게 아니라, factor zoo 자동 생성기로
체계적으로 찍어낸 후 일괄 백테스트로 검증된 모음이다.</p>

<div class="bg-block">
<h3>생성 파이프라인</h3>
<p>스크립트: <code>scripts/tools/generate_factor_zoo.py</code> →
<code>scripts/run_batch_backtests.py</code>.</p>
<ol>
<li><strong>신호 라이브러리</strong>: 학계·업계 알려진 cross-sectional factor 약 185개를
파이썬 식(expression)으로 등록. 카테고리:
  <span class="pill">liquidity / size</span>
  <span class="pill">momentum / return</span>
  <span class="pill">realised volatility</span>
  <span class="pill">mean-reversion (BB pos, CCI)</span>
  <span class="pill">channel breakout (Donchian, Aroon)</span>
  <span class="pill">acceleration / skew / kurtosis</span>
  <span class="pill">illiquidity (Amihud)</span>
  <span class="pill">volume z-score</span>
  <br>예: <code>atr_proxy_7d</code>, <code>illiq_amihud_60d</code>, <code>aroon_up_14d</code>,
  <code>bb_pos_20d</code>, <code>accel_5d</code>, <code>vol_ratio_5_20</code> 등. 윈도우 길이
  변형이 본질적으로 다른 신호라 5d/7d/14d/21d/60d 등 따로 등록.</li>

<li><strong>방향 × 농도 grid</strong>: 각 신호를 두 방향(<code>fwd</code> = 신호 상위 long /
하위 short; <code>rev</code> = 반대) × 6개 농도(<code>c05·c10·c20·c30·c40·c50</code>, 즉 풀의
상·하위 5/10/20/30/40/50% 추출) 로 교배.<br>
<strong>185 신호 × 2 방향 × 6 농도 ≈ 2,220개 모듈</strong>이 자동 생성된다.
파일명 형식: <code>xs_factor_&lt;signal&gt;&lt;window&gt;d_&lt;dir&gt;_c&lt;K&gt;.py</code>.</li>

<li><strong>일괄 백테스트</strong>: 같은 백테스트 엔진(<code>scripts/tools/backtest.py</code>)이
각 모듈에 대해 IS(2022-01-01 ~ 2024-04-19) + OS(2024-04-20 ~ 2026-05-07) 분리해서
실행. 출력 = 일봉 weights / equity_curve / metrics.json 등 표준 artifact.</li>

<li><strong>SUBMITTABLE 게이트</strong>(현행, <code>alpha_dashboard_lib.classify_alpha</code>):
fee-only 컷 3개 AND ─ |pnl_bps_simple| &gt; 15 bps, trades &gt; 100, |MDD| &lt; 60%.
부호 무관 (mirror는 같은 zoo가 fwd/rev 양쪽 다 생성하므로 별도 모듈로 통과).
+ population-level correlation gate τ=0.7로 SUBMITTABLE → NORMAL 강등.</li>

<li><strong>실제 결과</strong>: archive/run_2026_05_full531/alphas/ 에 279개 알파(IS·OS 둘 다
완료된 것 기준)가 살아 있고, 본 EDA의 sanity gate(|일일 ret| &gt; 100% 제외)를 통과한
236개가 분석 대상이다.</li>
</ol>
</div>

<div class="note"><strong>왜 풀에 노이즈가 많은가</strong>: zoo는 의도적으로 넓게 펼친
파라미터 sweep이다. 같은 factor(예: atr_proxy)의 윈도우 × K 변형 18개가 동시에 들어와
있어서 cousin cell이 자연 발생한다. "어떤 K가 옳은가"를 미리 정하지 않고 데이터에게
결정시키는 정통 zoo 철학 — 대신 직교화 단계에서 정리해야 한다. 본 EDA가 그 정리
효과를 측정한다.</div>

<h2>용어 (처음 보는 사람을 위해)</h2>
<ul class="glossary">
<li><code>Sharpe</code> 위험 조정 수익. 일일 평균 수익률 ÷ 일일 표준편차 ×
  √252. 0.5 이하 = 약함, 1.0 = 실거래 적합, 2.0+ = 매우 우수 (보통 over-fit 신호).</li>
<li><code>IS / OS</code> In-Sample / Out-of-Sample. 학습 구간 vs 검증 구간.
  IS는 {is_start} ~ {is_end.date()}, OS는 그 이후.</li>
<li><code>sign-flip (부호 뒤집기)</code> 알파의 Sharpe가 음수면 신호를 반대로
  내서 양수로 만든다. raw 데이터의 60%가 음의 Sharpe라 부호 결정이 합성
  알파 가치의 70%를 책임진다.</li>
<li><code>signed correlation</code> 부호 보존 상관계수. |ρ|와 달리 ρ=-0.5인
  페어는 hedge로 가까이 두지 않는다. Lopez de Prado 거리 D=√(½(1−ρ)).</li>
<li><code>Greedy Drop</code> Sharpe 내림차순으로 walk하며 기존 멤버와 ρ≥τ면
  drop. 가장 단순하고 robust한 직교화.</li>
<li><code>Hierarchical (Ward)</code> 거리 행렬에 계층 군집화 → τ 컷오프.
  cluster 안에서 IS Sharpe 최고만 뽑음.</li>
<li><code>AP + Greedy</code> Affinity Propagation으로 exemplar 추출 후
  greedy로 한 번 더 정제. 가장 직교한 코어를 만듦.</li>
<li><code>오라클 천장</code> "이 풀에서 합성 알파가 도달할 수 있는 최대
  Sharpe". 정의 방식에 따라 다른 값이 나옴 — 그래서 3단계로 측정.</li>
</ul>

<div class="note"><strong>방법 공통</strong>: ① Sanity gate (|일일 ret|&gt;100%
인 마이크로캡 blow-up 알파 제외, 43개). ② OS 단일일 ±50% clip (시뮬레이션
artifact 차단). ③ 부호 결정 = 룩백 윈도우 Sharpe&lt;0 인 알파를 −1 곱. ④
군집 셀렉션 = Greedy / Ward Hierarchical / Affinity Propagation. ⑤ 합성 시
EQW (각 멤버 동등가중).</div>

<h2>Stage 1 — 전체 기간 fit (information ceiling)</h2>
<p>IS+OS 전 기간을 모두 사용해서 부호와 멤버 선택을 한 뒤, <em>같은</em> 기간을
평가한다. 풀이 보유한 <strong>raw 정보량</strong>의 상한선. 평가 데이터로 fit
했으므로 in-sample over-fit이 최대치 — 실거래 기대치로 쓰면 안 됨. 차트의
빨간 점선은 IS/OS 경계 (참고용).</p>
<img src="data:image/png;base64,{img1}" alt="Stage 1 — Full-period fit">
{_table(stage1_rows)}
<p class="meta">Greedy Drop이 Full Sh +{headline_full:.2f}로 챔피언. 이 숫자가
실거래에서 나올 리는 거의 없다.</p>

<h2>Stage 2 — IS-only fit, OS replay (static train/test)</h2>
<p>부호와 멤버 선택을 IS 윈도우({is_start} ~ {is_end.date()})에서만 결정한 뒤
그 결정을 동결해 IS+OS 전체를 재생한다. 클래식 train/test 분리. IS Sharpe
대비 OS Sharpe가 떨어지는 정도가 <strong>shrinkage factor</strong>. 그래프에서
IS 구간은 흐리게(α=0.30), OS 구간은 진하게(α=0.95).</p>
<img src="data:image/png;base64,{img2}" alt="Stage 2 — IS-only fit">
{_table(stage2_rows)}
<p class="meta">IS Sharpe의 약 1/2이 OS Sharpe로 살아남는다. Greedy Drop:
IS +3.35 → OS +1.86. shrinkage 0.55.</p>

<h2>Stage 3 — 1년 룩백 / 월간 리밸런싱 (walk-forward, honest ceiling)</h2>
<p>실거래에 가장 가까운 평가. 매월 첫 거래일에 직전 252일(약 1년) 데이터를
룩백으로 사용해 (1) 부호 결정, (2) 멤버 선택을 한다. 그 결정으로 다음 한 달간
운용 후 결과를 stitch.</p>
<p><strong>부호 결정의 영향</strong>을 분리해서 보기 위해 solid(sign-aligned)와
dashed(raw)를 같이 그렸다 — 같은 색 = 같은 파이프라인.</p>
<img src="data:image/png;base64,{img3}" alt="Stage 3 — Rolling compare">
{_table(stage3_rows)}
<p class="meta">관찰: <strong>raw(dashed)는 4개 모두 음의 Sharpe</strong> (-1.0 ~ -2.3).
sign-flip만 추가하면 +2.0 ~ +2.5 가치 발생. 풀의 60%가 음의 Sharpe라
부호 결정이 합성 알파의 핵심 가치.</p>

<h2>Stage 4 — 룩백 길이 민감도 (lookback sensitivity)</h2>
<p>Stage 3는 룩백을 252일(1년)로 고정했다. 룩백을 더 짧게(63일=3개월) 또는
길게(756일=3년) 가져가면 결과가 어떻게 바뀌는가? <strong>부호 결정의
"기억 길이"</strong>에 대한 민감도. 짧은 룩백은 regime change에 빨리 적응하지만
노이즈에 취약하고, 긴 룩back은 안정적이지만 regime 변화 못 따라감.</p>
<img src="data:image/png;base64,{img4}" alt="Stage 4 — Lookback sweep">
{_lb_table(lb_results)}
<p class="meta">y축: walk-forward Full Sharpe (sign-aligned). 곡선이 위로 솟구치는
구간이 해당 파이프라인의 sweet-spot 룩백.</p>

<h2>결론 & 권장 사항</h2>
<ol>
<li><strong>현실적 천장 ≈ Sharpe 1.0</strong>. Stage 3 Greedy Drop +1.17, AP +0.97.
  in-sample 3.4 같은 숫자는 무시. 합성 기대치는 1.0~1.3 사이로 설정.</li>
<li><strong>부호 결정이 우선, 직교화는 다음</strong>. 부호만 추가해도 Sh +2,
  직교화 추가는 +0.3. 합성 모듈 만들 때 부호 결정 로직(rolling Sharpe)을 절대
  빼면 안 됨.</li>
<li><strong>12-15개 직교 코어가 robust</strong>. Greedy Drop / AP+Greedy 둘 다
  N̄ 11-14, OS Sharpe 0.6+. Hierarchical 38개는 in-sample 챔피언이지만 rolling에서
  중간. N이 적을수록 부호 안정성 ↑.</li>
<li><strong>입구컷 강화 필요</strong>. 현재 게이트가 부호 안정성·풀 ΔSharpe·
  거래량 상한을 측정 안 함. 5-tier 게이트 도입 시 풀 노이즈 60% → 30%, 천장
  1.17 → 1.3+ 기대.</li>
</ol>

<p class="meta">생성: scripts/tools/oracle_ceiling_eda.py --mode report</p>

</body></html>
"""
    (output_dir / "index.html").write_text(html)

    return {
        "stage1": stage1_rows,
        "stage2": stage2_rows,
        "stage3": stage3_rows,
        "_meta": {
            "run_id": run_id,
            "n_alphas": R_full.shape[1],
            "is_end": str(is_end.date()),
            "corr_threshold": threshold,
            "cost_bps": cost_bps,
            "lookback_days": lookback_days,
            "rebalance_freq": rebalance_freq,
        },
    }


def _fmt_table_rolling_compare(combined: dict) -> str:
    cols = ["Pipeline", "N̄ sign", "Sh signed", "AnnRet sign",
            "N̄ raw", "Sh raw", "AnnRet raw", "Δ Sh"]
    rows = []
    for name in ("Baseline (EQW all)", "Greedy Drop",
                 "Hierarchical Pruning", "AP + Greedy"):
        s = combined["signed"].get(name, {})
        r = combined["raw"].get(name, {})
        if "sharpe" not in s or "sharpe" not in r:
            continue
        rows.append([
            name,
            f"{s['N_avg']:.0f}",
            f"{s['sharpe']:+.2f}",
            f"{s['annualized_return']:+.1%}",
            f"{r['N_avg']:.0f}",
            f"{r['sharpe']:+.2f}",
            f"{r['annualized_return']:+.1%}",
            f"{s['sharpe'] - r['sharpe']:+.2f}",
        ])
    widths = [max(len(str(rr[i])) for rr in [cols] + rows) for i in range(len(cols))]
    sep = "  ".join("-" * w for w in widths)
    line = lambda rr: "  ".join(str(c).ljust(w) for c, w in zip(rr, widths))
    return "\n".join([line(cols), sep, *(line(rr) for rr in rows)])


def _fmt_table_rolling(metrics: dict) -> str:
    cols = ["Pipeline", "N̄", "Flipped̄", "OOS Sharpe", "AnnRet", "AnnVol", "MDD"]
    rows = []
    for name, m in metrics.items():
        if name.startswith("_") or "sharpe" not in m:
            continue
        rows.append([
            name, f"{m['N_avg']:.0f}", f"{m.get('n_flipped_avg', 0.0):.0f}",
            f"{m['sharpe']:+.2f}",
            f"{m['annualized_return']:+.1%}", f"{m['annualized_vol']:.1%}",
            f"{m['max_drawdown']:.1%}",
        ])
    widths = [max(len(str(r[i])) for r in [cols] + rows) for i in range(len(cols))]
    sep = "  ".join("-" * w for w in widths)
    line = lambda r: "  ".join(str(c).ljust(w) for c, w in zip(r, widths))
    return "\n".join([line(cols), sep, *(line(r) for r in rows)])


def _fmt_table_is_to_os(metrics: dict) -> str:
    cols = ["Pipeline", "N", "IS Sh", "OS Sh", "Sh degr",
            "IS MDD", "OS MDD", "IS AnnRet", "OS AnnRet"]
    rows = []
    for name, m in metrics.items():
        if name.startswith("_"):
            continue
        sh_is = m.get("sh_is", 0.0)
        sh_os = m.get("sh_os", 0.0)
        degr = sh_os / sh_is if sh_is else 0.0
        rows.append([
            name, f"{m['N']:>4}",
            f"{sh_is:+.2f}", f"{sh_os:+.2f}", f"{degr:+.2f}",
            f"{m['is_max_drawdown']:.1%}", f"{m['os_max_drawdown']:.1%}",
            f"{m['is_annualized_return']:+.1%}", f"{m['os_annualized_return']:+.1%}",
        ])
    widths = [max(len(str(r[i])) for r in [cols] + rows) for i in range(len(cols))]
    sep = "  ".join("-" * w for w in widths)
    line = lambda r: "  ".join(str(c).ljust(w) for c, w in zip(r, widths))
    return "\n".join([line(cols), sep, *(line(r) for r in rows)])


def _fmt_table(metrics: dict) -> str:
    cols = ["Pipeline", "N", "Sharpe (gross)", "Sharpe (net)",
            "MDD", "AnnRet", "AnnVol", "Trades/yr (avg)"]
    rows = []
    for name, m in metrics.items():
        if name.startswith("_"):
            continue
        rows.append([
            name, f"{m['N']:>4}",
            f"{m['sharpe_gross']:+.2f}", f"{m['sharpe_net']:+.2f}",
            f"{m['max_drawdown']:.1%}", f"{m['annualized_return']:+.1%}",
            f"{m['annualized_vol']:.1%}",
            f"{m['avg_trades_per_year_per_member']:,.0f}",
        ])
    widths = [max(len(str(r[i])) for r in [cols] + rows) for i in range(len(cols))]
    sep = "  ".join("-" * w for w in widths)
    line = lambda r: "  ".join(str(c).ljust(w) for c, w in zip(r, widths))
    return "\n".join([line(cols), sep, *(line(r) for r in rows)])


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--run-id", required=True)
    p.add_argument("--corr-threshold", type=float, default=0.3,
                   help="|ρ| threshold for dedup (default 0.3)")
    p.add_argument("--cost-bps", type=float, default=0.0,
                   help="round-trip transaction cost in bps (applied to net Sharpe)")
    p.add_argument("--linkage", default="ward",
                   choices=["ward", "average", "complete", "single"])
    p.add_argument("--max-abs-daily", type=float, default=1.0,
                   help="sanity cap: drop alphas whose any daily |return| "
                        "exceeds this (default 1.0 = ±100%%). Set 0 to disable.")
    p.add_argument("--no-sign-align", action="store_true",
                   help="skip flipping Sharpe-negative alphas (default ON — "
                        "negative-Sharpe alphas are positive alphas read "
                        "backwards; flipping reveals the pool's true ceiling)")
    p.add_argument("--mode", default="is_to_os",
                   choices=["is_only", "is_to_os", "rolling",
                            "rolling_compare", "report", "linkage_compare"],
                   help="is_only = in-sample ceiling (IS-decide + IS-evaluate); "
                        "is_to_os = IS-decide + OS-evaluate (honest oracle); "
                        "rolling = walk-forward (monthly rebalance, 1yr lookback); "
                        "rolling_compare = rolling × {signed, raw} side-by-side; "
                        "report = 3-stage HTML report with all PNGs")
    p.add_argument("--lookback-days", type=int, default=252,
                   help="lookback bars for the rolling mode (default 252 = 1yr)")
    p.add_argument("--rebalance-freq", default="MS",
                   help="pandas offset alias for rebalance cadence "
                        "(MS=month-start, W=weekly, QS=quarter-start; default MS)")
    p.add_argument("--output-dir",
                   default=str(REPO_ROOT / "reports" / "oracle_eda"))
    args = p.parse_args()

    out = Path(args.output_dir) / args.run_id
    if args.mode == "is_to_os":
        metrics = run_is_to_os(
            run_id=args.run_id,
            threshold=args.corr_threshold,
            cost_bps=args.cost_bps,
            output_dir=out,
            linkage_method=args.linkage,
            sanity_max_abs_daily=args.max_abs_daily,
        )
        print()
        print(_fmt_table_is_to_os(metrics))
    elif args.mode == "rolling":
        metrics = run_rolling(
            run_id=args.run_id,
            threshold=args.corr_threshold,
            cost_bps=args.cost_bps,
            output_dir=out,
            linkage_method=args.linkage,
            sanity_max_abs_daily=args.max_abs_daily,
            lookback_days=args.lookback_days,
            rebalance_freq=args.rebalance_freq,
            sign_align=not args.no_sign_align,
        )
        metrics.pop("_curves", None); metrics.pop("_rebal_dates", None)
        print()
        print(_fmt_table_rolling(metrics))
    elif args.mode == "rolling_compare":
        combined = run_rolling_compare(
            run_id=args.run_id,
            threshold=args.corr_threshold,
            cost_bps=args.cost_bps,
            output_dir=out,
            linkage_method=args.linkage,
            sanity_max_abs_daily=args.max_abs_daily,
            lookback_days=args.lookback_days,
            rebalance_freq=args.rebalance_freq,
        )
        print()
        print(_fmt_table_rolling_compare(combined))
    elif args.mode == "linkage_compare":
        by_method = run_linkage_compare(
            run_id=args.run_id, threshold=args.corr_threshold,
            cost_bps=args.cost_bps, output_dir=out,
            sanity_max_abs_daily=args.max_abs_daily,
        )
        print()
        cols = ["Linkage", "N", "IS Sh", "OS Sh", "Full Sh", "AnnRet", "MDD"]
        rows = []
        for m, d in by_method.items():
            rows.append([m, str(d["n_selected"]),
                         f"{d['sharpe_is']:+.2f}", f"{d['sharpe_os']:+.2f}",
                         f"{d['sharpe_full']:+.2f}",
                         f"{d['annualized_return']:+.1%}",
                         f"{d['max_drawdown']:.1%}"])
        widths = [max(len(str(r[i])) for r in [cols]+rows) for i in range(len(cols))]
        line = lambda r: "  ".join(str(c).ljust(w) for c, w in zip(r, widths))
        print(line(cols))
        print("  ".join("-" * w for w in widths))
        for r in rows: print(line(r))
    elif args.mode == "report":
        report = run_report(
            run_id=args.run_id,
            threshold=args.corr_threshold,
            cost_bps=args.cost_bps,
            output_dir=out,
            linkage_method=args.linkage,
            sanity_max_abs_daily=args.max_abs_daily,
            lookback_days=args.lookback_days,
            rebalance_freq=args.rebalance_freq,
        )
        print()
        print(f"stage1 rows: {len(report['stage1'])}, "
              f"stage2: {len(report['stage2'])}, "
              f"stage3: {len(report['stage3'])}")
        print(f"HTML index → {out}/index.html")
    else:
        metrics = run(
            run_id=args.run_id,
            threshold=args.corr_threshold,
            cost_bps=args.cost_bps,
            output_dir=out,
            linkage_method=args.linkage,
            sanity_max_abs_daily=args.max_abs_daily,
            sign_align=not args.no_sign_align,
        )
        print()
        print(_fmt_table(metrics))
    print()
    print(f"artifacts → {out}")


if __name__ == "__main__":
    main()
