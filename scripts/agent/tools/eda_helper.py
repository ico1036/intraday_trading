#!/usr/bin/env python3
"""
EDA Helper - Bar Size 최적화를 위한 변동성 분석

Researcher 에이전트가 Bash로 호출하여 최적 bar_size를 결정.

Usage:
    uv run python scripts/agent/tools/eda_helper.py \
        --data-path ./data/futures_ticks \
        --bar-type VOLUME \
        --bar-sizes 10 50 100 200 \
        --fee-type taker \
        --start 2024-01-01 \
        --end 2024-01-07

Output:
    ## EDA Results (2024-01-01 ~ 2024-01-07)
    | Bar Size | Bars | Avg Vol% | Fee Ratio | Status |
    |----------|------|----------|-----------|--------|
    | 10       | 5234 | 0.08%    | 0.80      | REJECT |
    | 100      | 523  | 0.22%    | 2.20      | OK     |

Fee Ratio = Avg Volatility / Round-Trip Fee
- >= 5.0: GOOD (충분한 마진)
- 2.0 ~ 5.0: OK (선택 가능)
- 1.0 ~ 2.0: MARGINAL (위험)
- < 1.0: REJECT (손실 예상)
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import pandas as pd

import logging

# Suppress noisy logs from data loader
logging.getLogger("intraday.data.loader").setLevel(logging.WARNING)

from intraday.candle_builder import CandleBuilder, CandleType
from intraday.data.loader import TickDataLoader


# Round-trip fee rates (Binance Futures)
FEE_RATES = {
    "taker": 0.0010,   # 0.10% (MARKET order: 0.05% × 2)
    "maker": 0.0004,   # 0.04% (LIMIT order: 0.02% × 2)
    "mixed": 0.0007,   # 0.07% (LIMIT entry + MARKET exit)
}

BAR_TYPES = {
    "VOLUME": CandleType.VOLUME,
    "TIME": CandleType.TIME,
    "TICK": CandleType.TICK,
    "DOLLAR": CandleType.DOLLAR,
}


def analyze_bar_volatility(
    data_path: Path,
    bar_type: CandleType,
    bar_size: float,
    start_time: datetime,
    end_time: datetime,
) -> dict:
    """
    특정 bar_size에서의 평균 변동성 계산.

    변동성 = (high - low) / close
    """
    try:
        # Suppress loader print statements
        import io
        import contextlib

        with contextlib.redirect_stdout(io.StringIO()):
            loader = TickDataLoader(data_path)
        builder = CandleBuilder(bar_type, bar_size)
        candles = builder.build_from_loader(loader, start_time, end_time)

        if not candles:
            return {
                "bar_size": bar_size,
                "bars": 0,
                "avg_volatility": 0.0,
                "error": "No candles generated",
            }

        # 변동성 계산: (high - low) / close
        volatilities = [(c.high - c.low) / c.close for c in candles if c.close > 0]

        if not volatilities:
            return {
                "bar_size": bar_size,
                "bars": len(candles),
                "avg_volatility": 0.0,
                "error": "No valid volatility data",
            }

        avg_vol = sum(volatilities) / len(volatilities)

        return {
            "bar_size": bar_size,
            "bars": len(candles),
            "avg_volatility": avg_vol,
            "min_volatility": min(volatilities),
            "max_volatility": max(volatilities),
            "error": None,
        }

    except Exception as e:
        return {
            "bar_size": bar_size,
            "bars": 0,
            "avg_volatility": 0.0,
            "error": str(e),
        }


def get_status(fee_ratio: float) -> str:
    """Fee ratio에 따른 상태 반환."""
    if fee_ratio >= 5.0:
        return "GOOD"
    elif fee_ratio >= 2.0:
        return "OK"
    elif fee_ratio >= 1.0:
        return "MARGINAL"
    else:
        return "REJECT"


def main():
    parser = argparse.ArgumentParser(
        description="EDA Helper - Bar Size 최적화를 위한 변동성 분석"
    )
    parser.add_argument(
        "--data-path",
        type=str,
        default="./data/futures_ticks",
        help="Tick data directory path",
    )
    parser.add_argument(
        "--bar-type",
        type=str,
        default="VOLUME",
        choices=list(BAR_TYPES.keys()),
        help="Bar type (VOLUME, TIME, TICK, DOLLAR)",
    )
    parser.add_argument(
        "--bar-sizes",
        type=float,
        nargs="+",
        default=[10, 50, 100, 200],
        help="Bar sizes to analyze",
    )
    parser.add_argument(
        "--fee-type",
        type=str,
        default="taker",
        choices=list(FEE_RATES.keys()),
        help="Fee type (taker, maker, mixed)",
    )
    parser.add_argument(
        "--start",
        type=str,
        default="2024-01-01",
        help="Start date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end",
        type=str,
        default="2024-01-07",
        help="End date (YYYY-MM-DD)",
    )

    args = parser.parse_args()

    # Parse dates
    try:
        start_time = datetime.strptime(args.start, "%Y-%m-%d")
        end_time = datetime.strptime(args.end, "%Y-%m-%d")
    except ValueError as e:
        print(f"ERROR: Invalid date format: {e}")
        print("Use YYYY-MM-DD format")
        sys.exit(1)

    # Validate period (max 14 days for EDA)
    period_days = (end_time - start_time).days
    if period_days > 14:
        print(f"ERROR: EDA period too long ({period_days} days). Max 14 days.")
        sys.exit(1)

    if period_days < 1:
        print(f"ERROR: EDA period too short. At least 1 day required.")
        sys.exit(1)

    # Check data path
    data_path = Path(args.data_path)
    if not data_path.exists():
        print(f"ERROR: Data path not found: {data_path}")
        print("\nAvailable data paths:")
        print("  ./data/futures_ticks  (FUTURES)")
        print("  ./data/ticks          (SPOT)")
        sys.exit(1)

    # Get fee rate
    fee_rate = FEE_RATES[args.fee_type]
    bar_type = BAR_TYPES[args.bar_type]

    # Header
    print(f"## EDA Results ({args.start} ~ {args.end})")
    print(f"Bar Type: {args.bar_type}")
    print(f"Fee Type: {args.fee_type.upper()} ({fee_rate*100:.2f}% round-trip)")
    print()

    # Results table
    print("| Bar Size | Bars | Avg Vol% | Fee Ratio | Status |")
    print("|----------|------|----------|-----------|--------|")

    results = []
    for bar_size in sorted(args.bar_sizes):
        result = analyze_bar_volatility(
            data_path=data_path,
            bar_type=bar_type,
            bar_size=bar_size,
            start_time=start_time,
            end_time=end_time,
        )

        if result["error"]:
            print(f"| {bar_size:<8} | ERROR: {result['error'][:30]} |")
            continue

        fee_ratio = result["avg_volatility"] / fee_rate if fee_rate > 0 else 0
        status = get_status(fee_ratio)

        results.append({
            "bar_size": bar_size,
            "bars": result["bars"],
            "avg_volatility": result["avg_volatility"],
            "fee_ratio": fee_ratio,
            "status": status,
        })

        print(
            f"| {bar_size:<8} | {result['bars']:<4} | "
            f"{result['avg_volatility']*100:.2f}%    | "
            f"{fee_ratio:<9.2f} | {status:<6} |"
        )

    # Recommendation
    print()
    print("## Recommendation")

    # Filter OK or better
    good_results = [r for r in results if r["status"] in ("GOOD", "OK")]

    if not good_results:
        marginal = [r for r in results if r["status"] == "MARGINAL"]
        if marginal:
            best = max(marginal, key=lambda x: x["fee_ratio"])
            print(f"WARNING: No good options. Best marginal: bar_size={best['bar_size']}")
            print(f"Consider using LIMIT orders (lower fees) or larger bar_size.")
        else:
            print("ERROR: All bar sizes have fee_ratio < 1.0 (expected loss)")
            print("This strategy may not be profitable with current fee structure.")
        sys.exit(0)

    # Pick best: prefer fee_ratio >= 2.0 with reasonable bar count
    # Balance between fee_ratio and statistical significance (bar count)
    def score(r):
        # Prefer higher fee_ratio, but penalize too few bars
        bar_penalty = 0 if r["bars"] >= 100 else (100 - r["bars"]) * 0.01
        return r["fee_ratio"] - bar_penalty

    best = max(good_results, key=score)

    print(f"→ bar_size = {best['bar_size']}")
    print(f"  - Fee Ratio: {best['fee_ratio']:.2f} ({best['status']})")
    print(f"  - Expected Bars: ~{best['bars']} per {period_days} days")
    print(f"  - Avg Volatility: {best['avg_volatility']*100:.2f}%")

    # Additional guidance
    if best["bars"] < 50:
        print()
        print("NOTE: Low bar count. Consider:")
        print("  - Smaller bar_size for more signals")
        print("  - Longer backtest period for statistical significance")


if __name__ == "__main__":
    main()
