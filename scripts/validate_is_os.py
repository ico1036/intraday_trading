#!/usr/bin/env python3
"""IS/OOS(Out-of-Sample) 검증 실행 스크립트.

- 하나의 전략에 대해 IS와 OS 구간을 각각 실행
- 과적합 경향(Overfit) 경고 규칙 적용
- 단일 실행 보고서 출력
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path
from typing import Any

# allow local imports
import sys

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "src"))

from scripts.agent.tools import backtest_tool


def _parse_metric(report_text: str, label: str) -> float | None:
    """Parse metric from backtest markdown report.

    Supports table-style output and common fallback formats.
    """
    if report_text is None:
        return None

    if "Error running backtest" in report_text:
        return None

    # label-based rows in backtest report
    if label in ("Total Return", "Sharpe Ratio", "Max Drawdown", "Win Rate", "Initial Capital", "Final Capital"):
        pattern = rf"\|\s*\**\s*{re.escape(label)}\s*\**\s*\|\s*([^|]+?)\s*\|"
        match = re.search(pattern, report_text)
        if match:
            raw = match.group(1).strip().replace("**", "")
            num = re.findall(r"-?[0-9]+\.?[0-9]*", raw.replace(",", ""))
            if num:
                v = float(num[0])
                if raw.endswith("%"):
                    return v / 100.0
                return v

        # fallback patterns
        fallback_map = {
            "Total Return": [r"Total Return\s*[:\s]+([+-]?[0-9]+\.?[0-9]*)%", r"Return\s*[:\s]+([+-]?[0-9]+\.?[0-9]*)"],
            "Sharpe Ratio": [r"Sharpe\s*Ratio\s*[:\s]+([+-]?[0-9]+\.?[0-9]*)"],
            "Max Drawdown": [r"Max Drawdown\s*[:\s]+([+-]?[0-9]+\.?[0-9]*)%"],
            "Win Rate": [r"Win Rate\s*[:\s]+([+-]?[0-9]+\.?[0-9]*)%"],
            "Initial Capital": [r"Initial Capital\s*[:\s]+\$?([0-9]+\.?[0-9]*)"],
            "Final Capital": [r"Final Capital\s*[:\s]+\$?([0-9]+\.?[0-9]*)"],
        }
        for p in fallback_map.get(label, []):
            m = re.search(p, report_text, re.IGNORECASE)
            if m:
                val = float(m.group(1))
                if label in {"Total Return", "Max Drawdown", "Win Rate"}:
                    return val / 100.0
                return val
        return None

    if label == "Total Trades":
        pattern = r"\|\s*\**\s*Total Trades\s*\**\s*\|\s*([0-9]+)\s*\|"
        match = re.search(pattern, report_text)
        if match:
            return float(int(match.group(1)))

        m = re.search(r"Total Trades\s*[:\s]+([0-9]+)", report_text, re.IGNORECASE)
        if m:
            return float(int(m.group(1)))
        return None

    return None


def _extract_metrics(result: dict[str, Any]) -> dict[str, float]:
    if result.get("is_error"):
        raise ValueError(
            result.get("content", [{"text": "Backtest failed"}])[0]["text"]
            if isinstance(result.get("content"), list)
            else str(result)
        )

    # support both dict and plain string contents
    text = ""
    if isinstance(result.get("content"), list) and result["content"]:
        text = str(result["content"][0].get("text", ""))
    elif isinstance(result.get("content"), str):
        text = result["content"]
    else:
        text = str(result)

    metrics = {
        "total_return": _parse_metric(text, "Total Return"),
        "sharpe": _parse_metric(text, "Sharpe Ratio"),
        "max_drawdown": _parse_metric(text, "Max Drawdown"),
        "win_rate": _parse_metric(text, "Win Rate"),
        "trades": _parse_metric(text, "Total Trades"),
    }

    missing = [k for k, v in metrics.items() if v is None]
    if missing:
        # Try synthetic fallback: compute return from Initial/Final capital
        if ("Initial Capital" in missing or "initial_capital" in missing or "final_capital" in missing):
            init_cap = _parse_metric(text, "Initial Capital")
            final_cap = _parse_metric(text, "Final Capital")
            if init_cap is not None and final_cap is not None and init_cap != 0:
                metrics["total_return"] = (final_cap - init_cap) / init_cap
                missing = [k for k, v in metrics.items() if v is None]

    if missing:
        raise ValueError(f"Could not parse metrics: {missing}\n{text[:400]}")

    return metrics


def _run_backtest(params: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(backtest_tool._run_backtest_impl(params))


def _eval_rule(is_metrics: dict[str, float], os_metrics: dict[str, float]) -> tuple[str, list[str]]:
    """Evaluate IS/OOS validation rules and return decision + notes."""
    notes: list[str] = []

    if is_metrics["trades"] < 5:
        notes.append("IS trades < 5 (logic / data sparse)")
    if is_metrics["sharpe"] < -0.5:
        notes.append("IS Sharpe < -0.5 (strategy quality issue)")

    if os_metrics["trades"] < 1:
        notes.append("OS no trade")

    if os_metrics["total_return"] < is_metrics["total_return"] * 0.5:
        notes.append(
            f"OS return collapsed: OS={os_metrics['total_return']:.4f}, IS={is_metrics['total_return']:.4f}"
        )

    if (is_metrics["sharpe"] >= 0 and os_metrics["sharpe"] < 0) or (
        is_metrics["sharpe"] < 0 and os_metrics["sharpe"] >= 0
    ):
        notes.append("Sharpe sign differs between IS and OS")

    wr_gap = abs(os_metrics["win_rate"] - is_metrics["win_rate"])
    if wr_gap > 0.20:
        notes.append(f"Win rate drift > 20% ({wr_gap:.2%})")

    decision = "APPROVED" if not notes else "REVIEW_REQUIRED"
    return decision, notes


def main() -> None:
    parser = argparse.ArgumentParser(description="Run IS/OOS validation backtests")
    parser.add_argument("--strategy", required=True)
    parser.add_argument("--data-path", default="./data/futures_ticks")
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT"],
    )
    parser.add_argument("--bar-type", default="VOLUME")
    parser.add_argument("--bar-size", type=float, default=20.0)
    parser.add_argument("--initial-capital", type=float, default=10000.0)
    parser.add_argument("--leverage", type=int, default=10)
    parser.add_argument("--position-size-pct", type=float, default=1.0)
    parser.add_argument("--include-funding", action="store_true", default=True)
    parser.add_argument("--no-funding", dest="include_funding", action="store_false", help="Disable futures funding")
    parser.add_argument("--strategy-params", default="{}", help='JSON string, e.g. {"top_n":5}')

    parser.add_argument("--is-start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--is-end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--os-start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--os-end", required=True, help="YYYY-MM-DD")

    args = parser.parse_args()

    try:
        strategy_params = json.loads(args.strategy_params or "{}")
    except Exception as exc:
        raise SystemExit(f"Invalid --strategy-params JSON: {exc}")

    symbol_data_paths = {sym: str(Path(args.data_path) / sym / "2025") for sym in args.symbols}

    base = {
        "strategy": args.strategy,
        "data_type": "tick",
        "data_path": args.data_path,
        "symbols": args.symbols,
        "symbol_data_paths": symbol_data_paths,
        "bar_type": args.bar_type,
        "bar_size": args.bar_size,
        "initial_capital": args.initial_capital,
        "leverage": args.leverage,
        "position_size_pct": args.position_size_pct,
        "include_funding": args.include_funding,
        "strategy_params": strategy_params,
    }

    print("[IS] Running...")
    is_args = base | {"start_date": args.is_start, "end_date": args.is_end}
    is_result = _run_backtest(is_args)

    print("[OS] Running...")
    os_args = base | {"start_date": args.os_start, "end_date": args.os_end}
    os_result = _run_backtest(os_args)

    is_metrics = _extract_metrics(is_result)
    os_metrics = _extract_metrics(os_result)

    decision, notes = _eval_rule(is_metrics, os_metrics)

    print("\n=== IS/OOS Validation Report ===")
    print(f"Strategy: {args.strategy}")
    print(f"Symbols: {', '.join(args.symbols)}")
    print(f"IS: {args.is_start} ~ {args.is_end}")
    print(f"OS: {args.os_start} ~ {args.os_end}")
    print("\n-- IS Metrics --")
    print(
        f"Return={is_metrics['total_return']:.4%}, Sharpe={is_metrics['sharpe']:.2f}, DD={is_metrics['max_drawdown']:.4%}, "
        f"WR={is_metrics['win_rate']:.2%}, Trades={int(is_metrics['trades'])}"
    )
    print("\n-- OS Metrics --")
    print(
        f"Return={os_metrics['total_return']:.4%}, Sharpe={os_metrics['sharpe']:.2f}, DD={os_metrics['max_drawdown']:.4%}, "
        f"WR={os_metrics['win_rate']:.2%}, Trades={int(os_metrics['trades'])}"
    )
    print("\nDecision:", decision)
    if notes:
        print("Notes:")
        for n in notes:
            print(" -", n)

    if decision != "APPROVED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
