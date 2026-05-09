#!/usr/bin/env python3
"""Run a portfolio alpha backtest from CLI and emit JSON."""
from __future__ import annotations

import argparse
import importlib
import inspect
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

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
    )
    result = runner.run(start_time=parse_dt(args.start), end_time=parse_dt(args.end))
    runner.save_report(output_dir)
    verification = verify_artifact(output_dir)

    # Compute display-only summary metrics that the dashboard previously
    # recomputed on every render. Persist into metrics.json so the dashboard
    # is read-only and the cost is paid once at write time.
    pnl_bps_simple, pnl_bps_w = _persist_display_metrics(output_dir)

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

    quality_report = _enforce_quality_gates(output_dir, enforce=args.enforce_quality)

    reject_report = _enforce_reject_rules(output_dir, enforce=args.enforce_quality)

    overall_ok = verification["ok"] and quality_report["ok"] and reject_report["ok"]
    return {
        "ok": overall_ok,
        "artifact_dir": str(output_dir) if quality_report["kept"] else None,
        "artifact_kept": quality_report["kept"],
        "strategy": args.strategy,
        "symbols": symbols,
        "metrics": metrics,
        "verification": verification,
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
        for split in ("is", "os"):
            manifest = alpha_dir / split / "manifest.json"
            if not manifest.exists():
                continue
            strat_path = _resolve_strategy_path_from_manifest(manifest)
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
        if _cell_signature(cell) in existing:
            report["issues"].append(
                "ALPHA_CELL signature already present in this run (saturation)"
            )

    if report["issues"] and enforce:
        report["ok"] = False
    return report


def _persist_display_metrics(output_dir: Path) -> tuple[float | None, float | None]:
    """Compute per-trade statistics and merge them into metrics.json.

    Returns (simple_avg_bps, notional_weighted_avg_bps) for backwards
    compatibility with the caller signature. The full stats dict (t-stat,
    per-trade Sharpe, win_rate, profit_factor, win/loss avg, largest W/L,
    Calmar etc.) is also persisted so the dashboard is purely read-only.
    """
    metrics_path = output_dir / "metrics.json"
    trades_path = output_dir / "trades.parquet"
    if not metrics_path.exists():
        return (None, None)
    try:
        _here = Path(__file__).resolve().parent
        if str(_here) not in sys.path:
            sys.path.insert(0, str(_here))
        from alpha_dashboard_lib import compute_trade_stats  # noqa: E402
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
    metrics_path.write_text(json.dumps(existing, indent=2, default=str))
    return (simple, weighted)


def _enforce_reject_rules(output_dir: Path, *, enforce: bool) -> dict:
    """Apply user-defined reject rules R1-R4 once both IS and OS exist.

    Only fires after the OS run (when sibling IS metrics is available). If
    the alpha trips any reject rule, the entire alpha directory (both IS
    and OS) is removed — these alphas are not worth keeping per user policy.
    """
    report = {"ok": True, "kept": True, "category": None, "reason": None}
    if output_dir.name != "os":
        return report  # only evaluate after OS leg
    is_metrics_path = output_dir.parent / "is" / "metrics.json"
    os_metrics_path = output_dir / "metrics.json"
    if not is_metrics_path.exists() or not os_metrics_path.exists():
        return report  # incomplete, skip
    try:
        is_m = json.loads(is_metrics_path.read_text())
        os_m = json.loads(os_metrics_path.read_text())
    except Exception:
        return report
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
    parser.add_argument("--bar-type", choices=["TIME", "VOLUME", "TICK", "DOLLAR"], default="TIME")
    parser.add_argument("--bar-size", type=float, default=60.0)
    parser.add_argument("--initial-capital", type=float, default=10000.0)
    parser.add_argument("--position-size-pct", type=float, default=1.0)
    parser.add_argument("--leverage", type=int, default=1)
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
