#!/usr/bin/env python3
"""Run a portfolio alpha backtest from CLI and emit JSON."""
from __future__ import annotations

import argparse
import importlib
import inspect
import json
import os
import subprocess
import sys
import tempfile
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from intraday.backtest.multi_tick_runner import PortfolioTickBacktestRunner
from intraday.candle_builder import CandleType
from intraday.data.bar_loader import BarDataLoader
from intraday.data.loader import TickDataLoader

import shutil

from scripts.governance.check import (
    _apply_quality_gates,
    _cell_signature,
    _load_quality_gates_for_run,
    _parse_module_constants,
    _resolve_strategy_path_from_manifest,
    _validate_cell,
    ALPHA_CELL_KEYS,
    REPO_ROOT as GOVERNANCE_REPO_ROOT,
)
from scripts.tools.verify_artifact import verify_artifact


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.strptime(value, "%Y-%m-%d")


def _class_to_module_name(class_name: str) -> str:
    out = []
    for idx, char in enumerate(class_name):
        if char.isupper() and idx > 0 and not class_name[idx - 1].isupper():
            out.append("_")
        out.append(char.lower())
    return "".join(out)


def load_strategy_class(class_name: str) -> type:
    candidates = [
        f"intraday.strategies.multi.{_class_to_module_name(class_name)}",
        "intraday.strategies.multi._alpha_template",
        "intraday.strategies.multi",
    ]
    errors = []
    for module_name in candidates:
        try:
            if module_name in sys.modules:
                del sys.modules[module_name]
            module = importlib.import_module(module_name)
            cls = getattr(module, class_name, None)
            if isinstance(cls, type):
                return cls
        except Exception as exc:
            errors.append(f"{module_name}: {exc}")
    raise ValueError(f"strategy class not found: {class_name}; tried {errors}")


def build_loaders(
    *,
    symbols: list[str],
    data_path: Path,
    symbol_data_paths: dict[str, str],
    data_type: str,
) -> dict[str, TickDataLoader]:
    loaders = {}
    loader_cls = BarDataLoader if data_type == "bars" else TickDataLoader
    for symbol in symbols:
        path = Path(symbol_data_paths[symbol]) if symbol in symbol_data_paths else data_path
        candidate = data_path / symbol
        if symbol not in symbol_data_paths and candidate.exists():
            path = candidate
        if not path.exists():
            raise FileNotFoundError(f"data path not found for {symbol}: {path}")
        loaders[symbol] = loader_cls(path, symbol=symbol)
    return loaders


def run_backtest(args: argparse.Namespace) -> dict[str, Any]:
    symbols = [s.upper() for s in args.symbols]
    strategy_params = json.loads(args.strategy_params) if args.strategy_params else {}
    symbol_data_paths = json.loads(args.symbol_data_paths) if args.symbol_data_paths else {}

    strategy_cls = load_strategy_class(args.strategy)

    # Pre-flight: ALPHA_CELL / SOURCE_NOTES + saturation
    output_dir = Path(args.output_dir)
    preflight = _preflight_governance(
        strategy_cls=strategy_cls,
        strategy_class_name=args.strategy,
        output_dir=output_dir,
        enforce=args.enforce_governance,
    )
    if not preflight["ok"]:
        return {
            "ok": False,
            "error": "governance pre-flight failed",
            "preflight": preflight,
            "artifact_dir": str(output_dir),
            "artifact_kept": False,
        }

    sig = inspect.signature(strategy_cls.__init__)
    if "symbols" in sig.parameters and "symbols" not in strategy_params:
        strategy_params["symbols"] = symbols
    strategy = strategy_cls(**strategy_params)

    data_path = Path(args.data_path)
    loaders = build_loaders(
        symbols=symbols,
        data_path=data_path,
        symbol_data_paths=symbol_data_paths,
        data_type=args.data_type,
    )

    runner = PortfolioTickBacktestRunner(
        strategy=strategy,
        data_loaders=loaders,
        bar_type=CandleType[args.bar_type],
        bar_size=args.bar_size,
        initial_capital=args.initial_capital,
        position_size_pct=args.position_size_pct,
        maker_fee_rate=args.maker_fee_rate,
        taker_fee_rate=args.taker_fee_rate,
        leverage=args.leverage,
        fixed_aum_sizing=getattr(args, "fixed_aum_sizing", False),
        max_portfolio_weight=args.max_portfolio_weight,
    )
    result = runner.run(start_time=parse_dt(args.start), end_time=parse_dt(args.end))
    runner.save_report(output_dir)
    _snapshot_strategy_source(strategy_cls, output_dir)
    verification = verify_artifact(output_dir)

    # Compute display-only summary metrics that the dashboard previously
    # recomputed on every render. Persist into metrics.json so the dashboard
    # is read-only and the cost is paid once at write time.
    pnl_bps_simple, pnl_bps_w = _persist_display_metrics(
        output_dir, is_end=getattr(args, "is_end", None)
    )
    _compute_split_metrics(output_dir, getattr(args, "is_end", None))

    metrics = {
        "profit_factor": result.profit_factor,
        "total_return": result.total_return,
        "max_drawdown": -abs(result.max_drawdown),
        "total_trades": result.total_trades,
        "win_rate": result.win_rate,
        "sharpe": result.sharpe_ratio,
        "pnl_bps_simple": pnl_bps_simple,
        "pnl_bps_notional_weighted": pnl_bps_w,
        "per_symbol": result.get_symbol_breakdown(),
    }

    prefix_report = _enforce_prefix_invariance(output_dir, args)

    quality_report = _enforce_quality_gates(output_dir, enforce=args.enforce_quality)

    reject_report = _enforce_reject_rules(output_dir, enforce=args.enforce_quality)

    if not prefix_report["ok"] and args.enforce_quality and quality_report["kept"] and reject_report["kept"]:
        _delete_artifact_scope(output_dir)
        prefix_report["kept"] = False

    overall_ok = (
        verification["ok"]
        and prefix_report["ok"]
        and quality_report["ok"]
        and reject_report["ok"]
    )
    return {
        "ok": overall_ok,
        "artifact_dir": str(output_dir) if quality_report["kept"] and reject_report["kept"] and prefix_report["kept"] else None,
        "artifact_kept": quality_report["kept"] and reject_report["kept"] and prefix_report["kept"],
        "strategy": args.strategy,
        "symbols": symbols,
        "metrics": metrics,
        "verification": verification,
        "prefix_invariance": prefix_report,
        "quality": quality_report,
        "summary": {
            "initial_capital": result.initial_capital,
            "final_capital": result.final_capital,
            "tick_counts": result.tick_counts,
            "bar_counts": result.bar_counts,
            "data_type": args.data_type,
        },
    }


def _strategy_module_path(strategy_cls: type) -> Path | None:
    """Return the source file of an already-loaded strategy class."""
    try:
        return Path(inspect.getfile(strategy_cls))
    except (TypeError, OSError):
        return None


def _snapshot_strategy_source(strategy_cls: type, output_dir: Path) -> None:
    """Copy the strategy module into the archive so the alpha stays
    reproducible even if the source file is later deleted or refactored.

    Past trap: xs_factor_amihud60d_fwd_c20 lost its strategy file during
    a variant-sweep cleanup; the archive metrics remained but the code
    that produced them was gone. Snapshotting here breaks that linkage.
    Also persists the strategy class name + git HEAD so the alpha can be
    bound back to the exact module identity later.
    """
    import shutil
    import subprocess
    src = _strategy_module_path(strategy_cls)
    if src is None or not src.exists():
        return
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, output_dir / "strategy_source.py")
        git_sha = ""
        try:
            git_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=src.parent, capture_output=True, text=True, timeout=3,
            ).stdout.strip()
        except Exception:
            pass
        metrics_path = output_dir / "metrics.json"
        if metrics_path.exists():
            try:
                metrics = json.loads(metrics_path.read_text())
            except Exception:
                metrics = {}
            metrics.update({
                "strategy_class": strategy_cls.__name__,
                "strategy_source": "strategy_source.py",
                "source_original_path": str(src),
                "git_head": git_sha,
            })
            metrics_path.write_text(json.dumps(metrics, indent=2, default=str))
    except Exception:
        pass


def _existing_cells_in_run(run_dir: Path, *, exclude: Path | None = None) -> set[tuple]:
    """Collect ALPHA_CELL signatures from already-archived alphas in the run."""
    cells: set[tuple] = set()
    alphas_dir = run_dir / "alphas"
    if not alphas_dir.exists():
        return cells
    for alpha_dir in alphas_dir.iterdir():
        if not alpha_dir.is_dir():
            continue
        if exclude is not None and alpha_dir.resolve() == exclude.resolve():
            continue
        metadata_paths = [alpha_dir / "metrics.json"]
        metadata_paths.extend(alpha_dir / split / name for split in ("is", "os") for name in ("metrics.json", "manifest.json"))
        metadata_paths.append(alpha_dir / "manifest.json")
        for manifest in metadata_paths:
            if not manifest.exists():
                continue
            strat_path = _resolve_strategy_path_from_manifest(manifest)
            if strat_path is None:
                snap = alpha_dir / "strategy_source.py"
                strat_path = snap if snap.exists() else None
            if strat_path is None:
                continue
            consts = _parse_module_constants(strat_path)
            if consts is None:
                continue
            cells.add(_cell_signature(consts["alpha_cell"]))
            break
    return cells


def _preflight_governance(
    *,
    strategy_cls: type,
    strategy_class_name: str,
    output_dir: Path,
    enforce: bool,
) -> dict:
    """Validate ALPHA_CELL + SOURCE_NOTES and check saturation before backtest.

    On any failure with enforce=True we return ok=False and the caller refuses
    to run. enforce=False still reports issues but allows continuation.
    """
    report: dict = {
        "ok": True,
        "enforced": enforce,
        "issues": [],
        "cell": None,
        "source_notes": None,
    }

    strat_path = _strategy_module_path(strategy_cls)
    if strat_path is None or not strat_path.exists():
        report["issues"].append("strategy module path not resolvable")
        report["ok"] = not enforce
        return report

    consts = _parse_module_constants(strat_path)
    if consts is None:
        report["issues"].append(
            f"{strat_path.name} missing or invalid ALPHA_CELL / SOURCE_NOTES"
        )
        report["ok"] = not enforce
        return report

    cell = consts["alpha_cell"]
    notes = consts["source_notes"]
    report["cell"] = cell
    report["source_notes"] = notes

    cell_issues = _validate_cell(cell)
    if cell_issues:
        report["issues"].extend(f"ALPHA_CELL: {i}" for i in cell_issues)

    if not isinstance(notes, list) or not notes:
        report["issues"].append("SOURCE_NOTES is empty")
    else:
        for n in notes:
            if not (PROJECT_ROOT / str(n)).exists():
                report["issues"].append(f"SOURCE_NOTES missing file: {n}")

    if cell.get("idea_family") == "_template_do_not_use":
        report["issues"].append(
            "ALPHA_CELL.idea_family is the template placeholder — must be set"
        )

    # Saturation: same cell signature already in run.
    try:
        run_dir = output_dir.resolve().parents[2]
    except IndexError:
        run_dir = None
    if run_dir is not None and run_dir.exists() and not cell_issues:
        # Exclude the alpha_dir we're about to (re)write; reruns of the same id
        # should not trip saturation against themselves.
        try:
            self_alpha_dir = output_dir.resolve().parents[0]
        except IndexError:
            self_alpha_dir = None
        existing = _existing_cells_in_run(run_dir, exclude=self_alpha_dir)
        # Cell-saturation guard disabled per owner directive 2026-05-22
        # ("패밀리 개념 없애"). idea_family classification was too
        # narrowly defined (variant-level) to act as a real coverage
        # guard, and the owner prefers free-form alpha exploration with
        # per-attempt feedback instead of an enforced taxonomy.
        # The cell signature is still recorded in metrics/strategy source for
        # post-hoc analysis, but does not block runs.
        _ = _cell_signature  # keep import alive for governance check
        del existing

    if report["issues"] and enforce:
        report["ok"] = False
    return report


def _persist_display_metrics(output_dir: Path, is_end: str | None = None) -> tuple[float | None, float | None]:
    """Compute per-trade statistics and merge them into metrics.json.

    Returns (simple_avg_bps, notional_weighted_avg_bps) for backwards
    compatibility with the caller signature. The full stats dict (t-stat,
    per-trade Sharpe, win_rate, profit_factor, win/loss avg, largest W/L,
    Calmar etc.) is also persisted so the dashboard is purely read-only.
    """
    metrics_path = output_dir / "metrics.json"
    trades_path = output_dir / "trades.parquet"
    weights_path = output_dir / "weights.parquet"
    if not metrics_path.exists():
        return (None, None)
    try:
        _here = Path(__file__).resolve().parent
        if str(_here) not in sys.path:
            sys.path.insert(0, str(_here))
        from alpha_dashboard_lib import compute_trade_stats, compute_ic  # noqa: E402
        import pandas as _pd
    except Exception:
        return (None, None)

    try:
        existing = json.loads(metrics_path.read_text())
    except Exception:
        return (None, None)

    # Trade-level stats from trades.parquet
    stats = {}
    if trades_path.exists():
        try:
            trades_df = _pd.read_parquet(trades_path)
            stats = compute_trade_stats(trades_df)
        except Exception:
            stats = {}

    simple = stats.get("mean_bps")
    weighted = stats.get("mean_bps_notional_weighted")

    # Calmar = total_return / |max_drawdown|, using existing engine values
    total_return = existing.get("total_return")
    max_dd = existing.get("max_drawdown")
    calmar = None
    try:
        if total_return is not None and max_dd is not None and float(max_dd) != 0:
            calmar = float(total_return) / abs(float(max_dd))
    except Exception:
        calmar = None

    # Persist (kept ``pnl_bps_simple`` / ``pnl_bps_notional_weighted`` keys for
    # back-compat with already-built dashboards / index caches).
    existing["pnl_bps_simple"] = simple
    existing["pnl_bps_notional_weighted"] = weighted
    existing["per_trade_sharpe"] = stats.get("per_trade_sharpe")
    existing["t_stat"] = stats.get("t_stat")
    existing["pnl_bps_std"] = stats.get("std_bps")
    existing["round_trips"] = stats.get("n_round_trips")
    existing["trade_win_rate"] = stats.get("win_rate")
    existing["avg_win_bps"] = stats.get("avg_win_bps")
    existing["avg_loss_bps"] = stats.get("avg_loss_bps")
    existing["win_loss_ratio"] = stats.get("win_loss_ratio")
    existing["profit_factor_trades"] = stats.get("profit_factor")
    existing["largest_win_bps"] = stats.get("largest_win_bps")
    existing["largest_loss_bps"] = stats.get("largest_loss_bps")
    existing["calmar"] = calmar

    # Information Coefficient — signal-vs-return rank corr per emit bar,
    # then time-averaged. Sign-agnostic SUBMITTABLE gates key off |IC|
    # and |IC_IR|.
    ic_stats: dict = {}
    if weights_path.exists():
        try:
            weights_df = _pd.read_parquet(weights_path)
            ic_stats = compute_ic(weights_df, is_end=is_end)
        except Exception:
            ic_stats = {}
    for key in ("ic_mean", "ic_std", "ic_ir", "ic_hit_rate", "ic_bars",
                "ic_mean_is", "ic_std_is", "ic_bars_is",
                "ic_mean_os", "ic_std_os", "ic_bars_os",
                "ic_z"):
        existing[key] = ic_stats.get(key)

    metrics_path.write_text(json.dumps(existing, indent=2, default=str))
    return (simple, weighted)


def _compute_split_metrics(output_dir: Path, is_end_str: str | None) -> None:
    """Persist IS/OS sub-metrics into metrics.json.

    When ``--is-end`` is set, backtest ran once across the full IS+OS
    range. This helper reads equity_curve.parquet + trades.parquet,
    slices each by ``is_end``, computes IS and OS metric blocks
    independently, and merges them into metrics.json under the keys
    ``"is"`` and ``"os"`` (the top-level keys remain the full-period
    metric, for back-compat).

    Agents must NOT read metrics.json directly when this field is
    populated; use ``scripts/tools/load_alpha.py --split is`` so OS
    blocks stay hidden behind ``SEAL_OPEN=1``.
    """
    if not is_end_str:
        return
    metrics_path = output_dir / "metrics.json"
    equity_path = output_dir / "equity_curve.parquet"
    trades_path = output_dir / "trades.parquet"
    if not metrics_path.exists():
        return

    try:
        import pandas as _pd
        import numpy as _np
        _here = Path(__file__).resolve().parent
        if str(_here) not in sys.path:
            sys.path.insert(0, str(_here))
        from alpha_dashboard_lib import compute_trade_stats  # noqa: E402
        from intraday.backtest.metrics import sharpe_daily_annualized  # noqa: E402
    except Exception:
        return

    try:
        is_end = _pd.Timestamp(is_end_str)
    except Exception:
        return

    try:
        existing = json.loads(metrics_path.read_text())
    except Exception:
        return

    equity_df = _pd.read_parquet(equity_path) if equity_path.exists() else _pd.DataFrame()
    trades_df = _pd.read_parquet(trades_path) if trades_path.exists() else _pd.DataFrame()

    def _slice_metrics(eq: "_pd.DataFrame", tr: "_pd.DataFrame") -> dict:
        out: dict[str, Any] = {}
        if not eq.empty and "timestamp" in eq.columns and "equity" in eq.columns:
            eq = eq.dropna(subset=["timestamp", "equity"]).sort_values("timestamp")
            if len(eq) >= 2:
                e0 = float(eq["equity"].iloc[0])
                e1 = float(eq["equity"].iloc[-1])
                out["initial_equity"] = e0
                out["final_equity"] = e1
                out["total_return"] = (e1 - e0) / e0 if e0 != 0 else 0.0
                cummax = eq["equity"].cummax()
                dd = (eq["equity"] - cummax) / cummax.replace(0, _np.nan)
                out["max_drawdown"] = float(dd.min()) if dd.notna().any() else 0.0
                # Engine convention: daily-resample equity, then sqrt(252)
                # annualise. Calling the same helper the runner uses keeps
                # PoC IS-slice metrics consistent with single-period runs.
                out["sharpe"] = sharpe_daily_annualized(
                    eq["equity"].tolist(), timestamps=eq["timestamp"].tolist()
                )
                tr_val = out["total_return"]
                mdd_val = out["max_drawdown"]
                out["calmar"] = (
                    float(tr_val) / abs(float(mdd_val)) if mdd_val and mdd_val != 0 else None
                )
        if not tr.empty:
            closed = tr[tr["pnl"].notna()] if "pnl" in tr.columns else tr.iloc[0:0]
            out["total_trades"] = int(len(closed))
            if len(closed) > 0:
                wins = closed[closed["pnl"] > 0]
                losses = closed[closed["pnl"] < 0]
                out["win_rate"] = float(len(wins) / len(closed))
                gross_w = float(wins["pnl"].sum()) if not wins.empty else 0.0
                gross_l = float(-losses["pnl"].sum()) if not losses.empty else 0.0
                out["profit_factor"] = (gross_w / gross_l) if gross_l > 0 else float("inf") if gross_w > 0 else 0.0
            try:
                stats = compute_trade_stats(tr)
                out["pnl_bps_simple"] = stats.get("mean_bps")
                out["pnl_bps_notional_weighted"] = stats.get("mean_bps_notional_weighted")
                out["per_trade_sharpe"] = stats.get("per_trade_sharpe")
                out["t_stat"] = stats.get("t_stat")
                out["pnl_bps_std"] = stats.get("std_bps")
                out["round_trips"] = stats.get("n_round_trips")
                out["trade_win_rate"] = stats.get("win_rate")
                out["avg_win_bps"] = stats.get("avg_win_bps")
                out["avg_loss_bps"] = stats.get("avg_loss_bps")
                out["win_loss_ratio"] = stats.get("win_loss_ratio")
                out["profit_factor_trades"] = stats.get("profit_factor")
                out["largest_win_bps"] = stats.get("largest_win_bps")
                out["largest_loss_bps"] = stats.get("largest_loss_bps")
            except Exception:
                pass
        return out

    if not equity_df.empty:
        equity_df["timestamp"] = _pd.to_datetime(equity_df["timestamp"])
        is_eq = equity_df[equity_df["timestamp"] <= is_end]
        os_eq = equity_df[equity_df["timestamp"] > is_end]
    else:
        is_eq = os_eq = equity_df

    if not trades_df.empty and "timestamp" in trades_df.columns:
        trades_df["timestamp"] = _pd.to_datetime(trades_df["timestamp"])
        is_tr = trades_df[trades_df["timestamp"] <= is_end]
        os_tr = trades_df[trades_df["timestamp"] > is_end]
    else:
        is_tr = os_tr = trades_df

    is_block = _slice_metrics(is_eq, is_tr)
    os_block = _slice_metrics(os_eq, os_tr)
    existing["is_end"] = is_end.isoformat()
    existing["is"] = is_block
    existing["os"] = os_block
    metrics_path.write_text(json.dumps(existing, indent=2, default=str))

    # Re-emit backtest_report.md as two clearly delimited sections so the
    # loader can serve the IS section without leaking OS numbers. The
    # original report file contained the full-period summary only; once
    # this helper runs the file is the canonical IS/OS split view.
    report_path = output_dir / "backtest_report.md"
    if report_path.exists():
        def _section(label: str, block: dict) -> str:
            if not block:
                return f"## {label}\n\n(no data)\n"
            lines = [f"## {label}\n"]
            ordered = [
                ("total_return", "Total Return"),
                ("sharpe", "Sharpe"),
                ("max_drawdown", "Max Drawdown"),
                ("calmar", "Calmar"),
                ("profit_factor", "Profit Factor"),
                ("win_rate", "Win Rate"),
                ("total_trades", "Total Trades"),
                ("initial_equity", "Initial Equity"),
                ("final_equity", "Final Equity"),
                ("t_stat", "t-stat"),
                ("pnl_bps_simple", "Mean PnL (bps, simple)"),
                ("pnl_bps_notional_weighted", "Mean PnL (bps, notional-weighted)"),
            ]
            for key, label_pretty in ordered:
                if key in block and block[key] is not None:
                    lines.append(f"- **{label_pretty}**: {block[key]}")
            return "\n".join(lines) + "\n"

        new_report = (
            f"# Backtest report\n\n"
            f"is_end: {is_end.isoformat()}\n\n"
            + _section("In-Sample (IS)", is_block)
            + "\n"
            + _section("Out-of-Sample (OS)", os_block)
        )
        report_path.write_text(new_report)


def _delete_artifact_scope(output_dir: Path) -> None:
    """Delete the same durable scope other hard gates remove.

    Split runs write to ``.../alphas/<alpha>/<split>`` and should remove the
    whole alpha directory. Flat/debug runs remove only their output dir.
    """
    try:
        resolved = output_dir.resolve()
        if resolved.name in {"is", "os", "forward"}:
            shutil.rmtree(resolved.parent, ignore_errors=True)
        else:
            shutil.rmtree(resolved, ignore_errors=True)
    except Exception:
        shutil.rmtree(output_dir, ignore_errors=True)


def _prefix_child_end(args: argparse.Namespace) -> datetime | None:
    start = parse_dt(args.start)
    end = parse_dt(args.end)
    if start is None or end is None or end <= start:
        return None
    span = end - start
    return start + span * 0.8


def _prefix_compare_cutoff(args: argparse.Namespace, child_end: datetime) -> datetime:
    return child_end


def _weight_events_for_compare(path: Path, cutoff: datetime, tol: float) -> pd.DataFrame:
    import pandas as _pd

    df = _pd.read_parquet(path)
    required = {"timestamp", "symbol", "target_weight"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{path.name} missing columns: {sorted(missing)}")
    if df.empty:
        return _pd.DataFrame(columns=["timestamp", "symbol", "target_weight"])
    out = df[["timestamp", "symbol", "target_weight"]].copy()
    out["timestamp"] = _pd.to_datetime(out["timestamp"])
    out["symbol"] = out["symbol"].astype(str).str.upper()
    out["target_weight"] = _pd.to_numeric(out["target_weight"], errors="coerce")
    out = out[out["timestamp"] <= _pd.Timestamp(cutoff)]
    out = out.dropna(subset=["timestamp", "symbol", "target_weight"])
    out["target_weight"] = out["target_weight"].where(out["target_weight"].abs() > tol, 0.0)
    return (
        out.sort_values(["timestamp", "symbol"])
        .groupby(["timestamp", "symbol"], as_index=False)
        .last()
        .sort_values(["timestamp", "symbol"])
        .reset_index(drop=True)
    )


def _compare_prefix_weights(parent_path: Path, child_path: Path, cutoff: datetime, tol: float = 1e-9) -> dict:
    import pandas as _pd

    parent = _weight_events_for_compare(parent_path, cutoff, tol)
    child = _weight_events_for_compare(child_path, cutoff, tol)
    if parent.empty and child.empty:
        return {
            "ok": False,
            "reason": "no comparable weight rows before prefix cutoff",
            "compared_rows": 0,
            "parent_rows": 0,
            "child_rows": 0,
        }
    joined = parent.merge(
        child,
        on=["timestamp", "symbol"],
        how="outer",
        suffixes=("_parent", "_prefix"),
        indicator=True,
    )
    both = joined["_merge"] == "both"
    joined["abs_diff"] = (joined["target_weight_parent"] - joined["target_weight_prefix"]).abs()
    mismatched = joined[(~both) | (joined["abs_diff"] > tol)]
    sample_cols = ["timestamp", "symbol", "target_weight_parent", "target_weight_prefix", "_merge", "abs_diff"]
    samples = []
    for row in mismatched.head(20)[sample_cols].to_dict("records"):
        samples.append({k: (str(v) if isinstance(v, _pd.Timestamp) else v) for k, v in row.items()})
    return {
        "ok": bool(mismatched.empty),
        "reason": None if mismatched.empty else "prefix weights changed when backtest end changed",
        "compared_rows": int(len(joined)),
        "parent_rows": int(len(parent)),
        "child_rows": int(len(child)),
        "mismatched_rows": int(len(mismatched)),
        "max_abs_diff": float(joined.loc[both, "abs_diff"].max()) if bool(both.any()) else None,
        "cutoff": str(pd.Timestamp(cutoff)),
        "samples": samples,
    }


def _enforce_prefix_invariance(output_dir: Path, args: argparse.Namespace) -> dict:
    """Hard lookahead guard: changing backtest end must not rewrite past weights."""
    report: dict[str, Any] = {
        "ok": True,
        "kept": True,
        "enforced": True,
        "skipped": False,
        "reason": None,
    }
    if os.environ.get("INTRADAY_PREFIX_INTEGRITY_CHILD") == "1":
        report["skipped"] = True
        report["reason"] = "internal prefix child run"
        return report

    child_end = _prefix_child_end(args)
    if child_end is None:
        report.update({"ok": False, "reason": "cannot compute prefix window from --start/--end"})
        return report

    parent_weights = output_dir / "weights.parquet"
    if not parent_weights.exists():
        report.update({"ok": False, "reason": "parent weights.parquet missing"})
        return report

    cutoff = _prefix_compare_cutoff(args, child_end)
    with tempfile.TemporaryDirectory(prefix="prefix_invariance_") as tmp:
        child_dir = Path(tmp) / "prefix"
        cmd = [
            sys.executable,
            "-u",
            str(Path(__file__).resolve()),
            "--strategy",
            args.strategy,
            "--symbols",
            *args.symbols,
            "--data-type",
            args.data_type,
            "--data-path",
            args.data_path,
            "--start",
            str(args.start),
            "--end",
            child_end.isoformat(sep=" "),
            "--bar-type",
            args.bar_type,
            "--bar-size",
            str(args.bar_size),
            "--initial-capital",
            str(args.initial_capital),
            "--position-size-pct",
            str(args.position_size_pct),
            "--leverage",
            str(args.leverage),
            "--max-portfolio-weight",
            str(args.max_portfolio_weight),
            "--maker-fee-rate",
            str(args.maker_fee_rate),
            "--taker-fee-rate",
            str(args.taker_fee_rate),
            "--output-dir",
            str(child_dir),
            "--no-enforce-quality",
            "--no-enforce-governance",
            "--json",
        ]
        if getattr(args, "fixed_aum_sizing", False):
            cmd.append("--fixed-aum-sizing")
        if getattr(args, "symbol_data_paths", ""):
            cmd.extend(["--symbol-data-paths", args.symbol_data_paths])
        if getattr(args, "strategy_params", ""):
            cmd.extend(["--strategy-params", args.strategy_params])

        env = {**os.environ, "INTRADAY_PREFIX_INTEGRITY_CHILD": "1"}
        proc = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        child_weights = child_dir / "weights.parquet"
        if proc.returncode not in (0, 2) or not child_weights.exists():
            report.update(
                {
                    "ok": False,
                    "reason": f"prefix child backtest failed rc={proc.returncode}",
                    "child_end": child_end.isoformat(sep=" "),
                    "cutoff": pd.Timestamp(cutoff).isoformat(),
                }
            )
            return report
        try:
            compare = _compare_prefix_weights(parent_weights, child_weights, cutoff)
        except Exception as exc:
            report.update({"ok": False, "reason": f"prefix comparison failed: {exc}"})
            return report

    report.update(compare)
    report["child_end"] = child_end.isoformat(sep=" ")
    return report


def _enforce_reject_rules(output_dir: Path, *, enforce: bool) -> dict:
    """Apply user-defined reject rules and delete the alpha dir on failure.

    - After IS run: applies IS-only reject (R1-IS bps ≤ 0, R2-IS t-stat < 1.5,
      R4 IS trades < 100). Deletes the alpha dir if any fires — there is no
      point holding incomplete alphas that already fail an IS-side rule.
    - After OS run: applies the full IS+OS rules (R1-R4 plus degradation
      checks), again deleting the entire alpha dir on failure.
    """
    report = {"ok": True, "kept": True, "category": None, "reason": None}
    is_metrics_path = output_dir.parent / "is" / "metrics.json"
    os_metrics_path = output_dir.parent / "os" / "metrics.json"

    if not is_metrics_path.exists():
        return report  # nothing to evaluate yet
    try:
        is_m = json.loads(is_metrics_path.read_text())
    except Exception:
        return report
    os_m = None
    if os_metrics_path.exists():
        try:
            os_m = json.loads(os_metrics_path.read_text())
        except Exception:
            os_m = None

    try:
        _here = Path(__file__).resolve().parent
        if str(_here) not in sys.path:
            sys.path.insert(0, str(_here))
        from alpha_dashboard_lib import classify_alpha  # noqa: E402
    except Exception:
        return report

    category, reason = classify_alpha(is_m, os_m)
    report["category"] = category
    report["reason"] = reason
    if category == "REJECT":
        report["ok"] = False
        if enforce:
            try:
                shutil.rmtree(output_dir.parent, ignore_errors=True)
                report["kept"] = False
            except Exception:
                pass
    return report


def _enforce_quality_gates(output_dir: Path, *, enforce: bool) -> dict:
    """Apply run quality_gates; delete artifact dir on failure when enforce=True.

    The run dir is inferred as ``output_dir.parents[2]`` (i.e.
    ``archive/<run>/alphas/<alpha>/<split>`` -> ``archive/<run>``).
    If the run has no ``quality_gates`` block, nothing is enforced.
    """
    report: dict = {
        "ok": True,
        "kept": True,
        "enforced": bool(enforce),
        "violations": [],
        "gates": {},
    }
    try:
        run_dir = output_dir.resolve().parents[2]
    except IndexError:
        return report
    gates = _load_quality_gates_for_run(run_dir)
    if not gates:
        return report
    report["gates"] = gates
    violations = _apply_quality_gates(output_dir, gates)
    if not violations:
        return report
    report["ok"] = False
    report["violations"] = violations
    if enforce:
        # Delete the entire alpha directory (parent of split) on quality gate
        # failure so the dashboard never shows a partial / orphan alpha row.
        # output_dir = archive/<run>/alphas/<alpha>/<split>
        try:
            alpha_dir = output_dir.resolve().parent
            shutil.rmtree(alpha_dir, ignore_errors=True)
        except Exception:
            shutil.rmtree(output_dir, ignore_errors=True)
        report["kept"] = False
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run deterministic alpha backtest")
    parser.add_argument("--strategy", required=True)
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--data-type", choices=["ticks", "bars"], default="bars")
    parser.add_argument("--data-path", default="data/futures_klines")
    parser.add_argument("--symbol-data-paths", default="")
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument(
        "--is-end", default=None,
        help="If set with a full IS+OS --start/--end range, runs once and "
             "splits metrics into IS (up to is-end) and OS (after is-end) "
             "sets inside metrics.json. agents read the IS set via "
             "scripts/tools/load_alpha.py.",
    )
    parser.add_argument("--bar-type", choices=["TIME", "VOLUME", "TICK", "DOLLAR"], default="TIME")
    parser.add_argument("--bar-size", type=float, default=60.0)
    parser.add_argument("--initial-capital", type=float, default=10000.0)
    parser.add_argument("--position-size-pct", type=float, default=1.0)
    parser.add_argument("--leverage", type=int, default=1)
    parser.add_argument("--max-portfolio-weight", type=float, default=1.0)
    parser.add_argument(
        "--fixed-aum-sizing", action="store_true",
        help="Scale leg notional off initial_capital instead of running "
             "capital. Recommended for evaluating market-neutral L/S signals.",
    )
    parser.add_argument("--maker-fee-rate", type=float, default=0.0002)
    parser.add_argument("--taker-fee-rate", type=float, default=0.0005)
    parser.add_argument("--strategy-params", default="")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--no-enforce-quality",
        dest="enforce_quality",
        action="store_false",
        help="Do not delete artifact dir on quality_gate failure (debug only).",
    )
    parser.set_defaults(enforce_quality=True)
    parser.add_argument(
        "--no-enforce-governance",
        dest="enforce_governance",
        action="store_false",
        help="Skip ALPHA_CELL / SOURCE_NOTES / saturation pre-flight (debug only).",
    )
    parser.set_defaults(enforce_governance=True)
    parser.add_argument("--json", action="store_true", help="emit JSON only")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = run_backtest(args)
    except Exception as exc:
        result = {
            "ok": False,
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "artifact_dir": args.output_dir,
        }
        print(json.dumps(result, indent=2, default=_json_default))
        return 2

    print(json.dumps(result, indent=2, default=_json_default))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
