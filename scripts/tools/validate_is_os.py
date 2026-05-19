#!/usr/bin/env python3
"""Compare IS/OS alpha metrics and write a warning label."""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise ValueError(f"missing file: {path}") from exc
    except Exception as exc:
        raise ValueError(f"unreadable JSON: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object: {path}")
    return data


def _metric(metrics: dict[str, Any], key: str) -> float:
    value = metrics.get(key)
    if value is None:
        raise ValueError(f"metrics.json missing key: {key}")
    try:
        return float(value)
    except Exception as exc:
        raise ValueError(f"metrics.json key is not numeric: {key}={value!r}") from exc


def _alpha_id(alpha_dir: Path, is_dir: Path, os_dir: Path) -> str:
    for path in (alpha_dir / "manifest.json", is_dir / "manifest.json", os_dir / "manifest.json"):
        if path.exists():
            manifest = _read_json(path)
            value = manifest.get("alpha_id") or manifest.get("strategy_name")
            if value:
                return str(value)
    return alpha_dir.name


def compare_metrics(
    *,
    alpha_dir: Path,
    is_dir: Path,
    os_dir: Path,
    return_ratio: float,
    sharpe_ratio: float,
    drawdown_ratio: float,
    win_rate_gap: float,
    min_os_trades: int,
) -> dict[str, Any]:
    # Two layouts are supported:
    #   legacy: alpha_dir/{is,os}/metrics.json (separate runs)
    #   flat:   alpha_dir/metrics.json with "is" / "os" sub-blocks
    # Detect flat via alpha_dir/metrics.json existing without is/.
    flat_metrics_path = alpha_dir / "metrics.json"
    if flat_metrics_path.exists() and not is_dir.is_dir():
        bundle = _read_json(flat_metrics_path)
        if not isinstance(bundle.get("is"), dict) or not isinstance(bundle.get("os"), dict):
            raise ValueError(
                f"flat metrics.json missing 'is' / 'os' sub-blocks: {flat_metrics_path}"
            )
        is_metrics = bundle["is"]
        os_metrics = bundle["os"]
    else:
        is_metrics = _read_json(is_dir / "metrics.json")
        os_metrics = _read_json(os_dir / "metrics.json")

    is_return = _metric(is_metrics, "total_return")
    os_return = _metric(os_metrics, "total_return")
    is_sharpe = _metric(is_metrics, "sharpe")
    os_sharpe = _metric(os_metrics, "sharpe")
    is_drawdown = abs(_metric(is_metrics, "max_drawdown"))
    os_drawdown = abs(_metric(os_metrics, "max_drawdown"))
    is_win_rate = _metric(is_metrics, "win_rate")
    os_win_rate = _metric(os_metrics, "win_rate")
    os_trades = int(_metric(os_metrics, "total_trades"))

    flags: list[str] = []
    notes: list[str] = []

    if is_return > 0 and os_return < is_return * return_ratio:
        flags.append("RETURN_COLLAPSE")
        notes.append(f"OS return {os_return:.6f} < IS return {is_return:.6f} * {return_ratio:.2f}")

    if is_sharpe > 0 and os_sharpe < is_sharpe * sharpe_ratio:
        flags.append("SHARPE_COLLAPSE")
        notes.append(f"OS Sharpe {os_sharpe:.6f} < IS Sharpe {is_sharpe:.6f} * {sharpe_ratio:.2f}")

    if is_sharpe > 0 and os_sharpe < 0:
        flags.append("SHARPE_SIGN_FLIP")
        notes.append(f"IS Sharpe is positive ({is_sharpe:.6f}) but OS Sharpe is negative ({os_sharpe:.6f})")

    if is_drawdown > 0 and os_drawdown > is_drawdown * drawdown_ratio:
        flags.append("DRAWDOWN_EXPANSION")
        notes.append(
            f"OS drawdown {os_drawdown:.6f} > IS drawdown {is_drawdown:.6f} * {drawdown_ratio:.2f}"
        )

    if abs(os_win_rate - is_win_rate) > win_rate_gap:
        flags.append("WIN_RATE_DRIFT")
        notes.append(
            f"win rate gap {abs(os_win_rate - is_win_rate):.6f} > {win_rate_gap:.6f}"
        )

    if os_trades < min_os_trades:
        flags.append("OS_TRADE_COUNT_TOO_LOW")
        notes.append(f"OS trades {os_trades} < {min_os_trades}")

    # Preserve insertion order but avoid duplicate flags when rules overlap.
    flags = list(dict.fromkeys(flags))

    return {
        "alpha_id": _alpha_id(alpha_dir, is_dir, os_dir),
        "status": "WARNING" if flags else "PASS",
        "flags": flags,
        "notes": notes,
        "is_dir": str(is_dir),
        "os_dir": str(os_dir),
        "is_metrics": is_metrics,
        "os_metrics": os_metrics,
        "thresholds": {
            "return_ratio": return_ratio,
            "sharpe_ratio": sharpe_ratio,
            "drawdown_ratio": drawdown_ratio,
            "win_rate_gap": win_rate_gap,
            "min_os_trades": min_os_trades,
        },
        "rules": {
            "RETURN_COLLAPSE": (
                "Triggered when IS total_return is positive and OS total_return is less than "
                "IS total_return * return_ratio."
            ),
            "SHARPE_COLLAPSE": (
                "Triggered when IS Sharpe is positive and OS Sharpe is less than "
                "IS Sharpe * sharpe_ratio."
            ),
            "SHARPE_SIGN_FLIP": (
                "Triggered when IS Sharpe is positive but OS Sharpe is negative."
            ),
            "DRAWDOWN_EXPANSION": (
                "Triggered when absolute OS max_drawdown is greater than "
                "absolute IS max_drawdown * drawdown_ratio."
            ),
            "WIN_RATE_DRIFT": (
                "Triggered when absolute OS win_rate minus IS win_rate is greater than "
                "win_rate_gap."
            ),
            "OS_TRADE_COUNT_TOO_LOW": (
                "Triggered when OS total_trades is less than min_os_trades."
            ),
        },
        "generated_at": datetime.now().isoformat(),
        "policy": (
            "OS validation labels distribution shift only. Do not modify the strategy based on OS results."
        ),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare IS and OS alpha artifacts")
    parser.add_argument("--alpha-dir", required=True, help="alpha directory containing is/ and os/")
    parser.add_argument("--is-name", default="is", help="IS child directory name")
    parser.add_argument("--os-name", default="os", help="OS child directory name")
    parser.add_argument("--output", default="", help="validation JSON path, default <alpha-dir>/validation.json")
    parser.add_argument("--return-ratio", type=float, default=0.30)
    parser.add_argument("--sharpe-ratio", type=float, default=0.30)
    parser.add_argument("--drawdown-ratio", type=float, default=2.0)
    parser.add_argument("--win-rate-gap", type=float, default=0.20)
    parser.add_argument("--min-os-trades", type=int, default=5)
    parser.add_argument("--json", action="store_true", help="emit JSON only")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    alpha_dir = Path(args.alpha_dir)
    output = Path(args.output) if args.output else alpha_dir / "validation.json"
    try:
        result = compare_metrics(
            alpha_dir=alpha_dir,
            is_dir=alpha_dir / args.is_name,
            os_dir=alpha_dir / args.os_name,
            return_ratio=args.return_ratio,
            sharpe_ratio=args.sharpe_ratio,
            drawdown_ratio=args.drawdown_ratio,
            win_rate_gap=args.win_rate_gap,
            min_os_trades=args.min_os_trades,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, default=_json_default))
        result["output"] = str(output)
        print(json.dumps(result, indent=2, default=_json_default))
        return 0
    except Exception as exc:
        result = {
            "status": "ERROR",
            "flags": [],
            "error": str(exc),
            "alpha_dir": str(alpha_dir),
            "output": str(output),
        }
        print(json.dumps(result, indent=2, default=_json_default))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
