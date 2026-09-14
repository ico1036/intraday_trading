"""What a backtest needs to be reproduced from its archive alone.

``run_config`` is the exact set of engine inputs behind one archived run and
``engine_fingerprint`` identifies the engine code that produced it. Together
they let a composite decide whether a member's archived weights are current
and, when they are not, rerun the member from the archive without guessing
its parameters.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[3]

# Source files whose change alters engine output. A run archived under a
# different fingerprint was produced by a different engine.
ENGINE_FILES: tuple[str, ...] = (
    "src/intraday/backtest/multi_tick_runner.py",
    "src/intraday/backtest/costs.py",
    "src/intraday/backtest/metrics.py",
    "src/intraday/candle_builder.py",
    "src/intraday/data/bar_loader.py",
    "src/intraday/data/funding_loader.py",
    "src/intraday/strategy.py",
    "src/intraday/strategies/_xs_factor_base.py",
)

# Cost-model defaults shared by the CLI and by member freshness checks.
COST_DEFAULTS: dict[str, Any] = {
    "funding": True,
    "funding_path": "data/funding_rates_full",
    "slippage": "adv_tier",
    "stale_bar_exit": 2,
}

# Sizing inputs a composite replay must share with its members.
SIZING_FIELDS: tuple[str, ...] = (
    "initial_capital",
    "position_size_pct",
    "leverage",
    "maker_fee_rate",
    "taker_fee_rate",
    "fixed_aum_sizing",
)


def file_sha256(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def engine_fingerprint(repo_root: Path = REPO_ROOT) -> str:
    """Short digest of the engine source files, in a fixed order."""
    digest = hashlib.sha256()
    for rel in ENGINE_FILES:
        path = Path(repo_root) / rel
        digest.update(rel.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes() if path.exists() else b"<missing>")
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def class_to_module_name(class_name: str) -> str:
    """``XsFactorAmihud60dFwdC10`` -> ``xs_factor_amihud60d_fwd_c10``."""
    out: list[str] = []
    for idx, char in enumerate(class_name):
        if char.isupper() and idx > 0 and not class_name[idx - 1].isupper():
            out.append("_")
        out.append(char.lower())
    return "".join(out)


def run_config_from_args(
    args: Any,
    strategy_params: Mapping[str, Any],
    symbol_data_paths: Mapping[str, str],
) -> dict[str, Any]:
    """The engine inputs of one ``backtest.py`` invocation, as plain JSON."""
    return {
        "strategy": args.strategy,
        "strategy_params": dict(strategy_params),
        "data_type": args.data_type,
        "data_path": str(args.data_path),
        "symbol_data_paths": dict(symbol_data_paths),
        "bar_type": args.bar_type,
        "bar_size": float(args.bar_size),
        "start": args.start,
        "end": args.end,
        "is_end": getattr(args, "is_end", None),
        "initial_capital": float(args.initial_capital),
        "position_size_pct": float(args.position_size_pct),
        "leverage": int(args.leverage),
        "max_portfolio_weight": float(args.max_portfolio_weight),
        "maker_fee_rate": float(args.maker_fee_rate),
        "taker_fee_rate": float(args.taker_fee_rate),
        "fixed_aum_sizing": bool(getattr(args, "fixed_aum_sizing", False)),
        "funding": bool(getattr(args, "funding", True)),
        "funding_path": str(args.funding_path),
        "slippage": str(args.slippage),
        "stale_bar_exit": int(getattr(args, "stale_bar_exit", COST_DEFAULTS["stale_bar_exit"])),
    }


def run_config_to_cli(
    cfg: Mapping[str, Any],
    *,
    output_dir: Path | str,
    symbols: list[str],
    overrides: Mapping[str, Any] | None = None,
) -> list[str]:
    """``backtest.py`` arguments that reproduce ``cfg`` (with ``overrides``
    applied) for ``symbols`` into ``output_dir``. Run-mode flags such as
    ``--json`` or ``--no-prefix-check`` are the caller's to add."""
    c = {**cfg, **(overrides or {})}
    cmd = [
        "--strategy", str(c["strategy"]),
        "--symbols", *symbols,
        "--data-type", str(c["data_type"]),
        "--data-path", str(c["data_path"]),
        "--bar-type", str(c["bar_type"]),
        "--bar-size", str(c["bar_size"]),
        "--initial-capital", str(c["initial_capital"]),
        "--position-size-pct", str(c["position_size_pct"]),
        "--leverage", str(c["leverage"]),
        "--max-portfolio-weight", str(c["max_portfolio_weight"]),
        "--maker-fee-rate", str(c["maker_fee_rate"]),
        "--taker-fee-rate", str(c["taker_fee_rate"]),
        "--funding-path", str(c["funding_path"]),
        "--slippage", str(c["slippage"]),
        "--stale-bar-exit", str(c["stale_bar_exit"]),
        "--output-dir", str(output_dir),
    ]
    for flag, key in (("--start", "start"), ("--end", "end"), ("--is-end", "is_end")):
        if c.get(key):
            cmd.extend([flag, str(c[key])])
    if not c.get("funding", True):
        cmd.append("--no-funding")
    if c.get("fixed_aum_sizing"):
        cmd.append("--fixed-aum-sizing")
    if c.get("strategy_params"):
        cmd.extend(["--strategy-params", json.dumps(c["strategy_params"])])
    if c.get("symbol_data_paths"):
        cmd.extend(["--symbol-data-paths", json.dumps(c["symbol_data_paths"])])
    return cmd
