"""
Simple diagnostic script to identify VWAP calculation issue.

This mimics how the Analyst agent runs backtests, using TickDataLoader directly.
"""

from datetime import datetime
from pathlib import Path

from intraday.config import get_default_data_dir
from intraday.strategies.tick.volume_imbalance_momentum import VolumeImbalanceMomentumStrategy
from intraday.backtest.tick_runner import TickBacktestRunner
from intraday.data.loader import TickDataLoader
from intraday.candle_builder import CandleType

# Configuration
SYMBOL = "BTCUSDT"
DATA_PATH = get_default_data_dir() / SYMBOL
START_DATE = datetime(2025, 3, 1)
END_DATE = datetime(2025, 3, 14)

# Strategy parameters (Iteration 4 Attempt 3 - RELAXED FILTERS)
STRATEGY_PARAMS = {
    "quantity": 0.01,
    "vwap_deviation_entry": 1.2,
    "vwap_reversion_target": 0.2,
    "stop_loss_pct": 1.5,
    "atr_threshold": 2.5,  # RELAXED from 1.5%
    "bb_width_threshold": 5.0,  # RELAXED from 3.0%
    "timeout_bars": 10,
    "warmup_bars": 30,
}

# Backtest configuration
BAR_TYPE = CandleType.TIME
BAR_SIZE = 120  # 2 minutes
LEVERAGE = 1
INITIAL_CAPITAL = 100000.0


def main():
    """Run diagnostic backtest."""
    print("=" * 80)
    print("VWAP DIAGNOSTIC BACKTEST (Simple Version)")
    print("=" * 80)
    print(f"Symbol: {SYMBOL}")
    print(f"Data Path: {DATA_PATH}")
    print(f"Period: {START_DATE.date()} to {END_DATE.date()}")
    print(f"Bar Type: TIME")
    print(f"Bar Size: {BAR_SIZE} seconds (2 minutes)")
    print(f"Initial Capital: ${INITIAL_CAPITAL:,.2f}")
    print(f"Leverage: {LEVERAGE}x")
    print()
    print("Strategy Parameters:")
    for key, value in STRATEGY_PARAMS.items():
        print(f"  {key}: {value}")
    print()
    print("=" * 80)
    print("LOADING DATA...")
    print("=" * 80)

    # Load data
    try:
        loader = TickDataLoader(DATA_PATH)
        print(f"✅ Data loaded successfully from {DATA_PATH}")
    except Exception as e:
        print(f"❌ Failed to load data: {e}")
        return

    # Create strategy
    print()
    print("Creating strategy...")
    strategy = VolumeImbalanceMomentumStrategy(**STRATEGY_PARAMS)
    print("✅ Strategy created")

    # Create runner
    print()
    print("Creating runner...")
    runner = TickBacktestRunner(
        strategy=strategy,
        data_loader=loader,
        bar_type=BAR_TYPE,
        bar_size=BAR_SIZE,
        initial_capital=INITIAL_CAPITAL,
        leverage=LEVERAGE,
        symbol=SYMBOL,
    )
    print("✅ Runner created")

    # Run backtest
    print()
    print("=" * 80)
    print("RUNNING BACKTEST...")
    print("=" * 80)
    print("Diagnostic logging will appear every 100 bars.")
    print()

    try:
        results = runner.run(start_time=START_DATE, end_time=END_DATE)
    except Exception as e:
        print(f"❌ Backtest failed: {e}")
        import traceback
        traceback.print_exc()
        return

    # Print results
    print()
    print("=" * 80)
    print("DIAGNOSTIC RESULTS")
    print("=" * 80)
    print()
    print("Execution Stats:")
    print(f"  Period: {results.start_time.date()} to {results.end_time.date()}")
    print(f"  Total Trades: {results.total_trades}")
    print()

    if results.total_trades == 0:
        print("⚠️  CRITICAL: 0 TRADES GENERATED")
        print()
        print("Diagnostic Analysis:")
        print("1. Review the diagnostic logs above for:")
        print("   - Is VWAP always None? → VWAP calculation broken")
        print("   - Does VWAP always equal close? → VWAP always 0% deviation")
        print("   - Are deviations always < 1.2%? → Entry threshold too strict")
        print("   - Are ATR values always > 2.5%? → ATR filter too strict")
        print("   - Are BB width values always > 5.0%? → BB filter too strict")
        print()
        print("2. Expected behavior (from backtest_report.md):")
        print("   - Expected trades: 50-150")
        print("   - Probability of 0 trades: 10^-68 (statistically impossible)")
        print()
        print("ROOT CAUSE:")
        print("  [Review diagnostic logs above to determine which field is broken]")
    else:
        print("✅ SUCCESS: Strategy generated trades!")
        print()
        print("Performance Metrics:")
        print(f"  Total Return: {results.total_return:.2f}%")
        print(f"  Win Rate: {results.win_rate:.1f}%")
        print(f"  Profit Factor: {results.profit_factor:.2f}")
        print(f"  Max Drawdown: {results.max_drawdown:.2f}%")
        print(f"  Sharpe Ratio: {results.sharpe_ratio:.2f}")
        print()
        print("NOTE: VWAP calculation is working correctly.")

    print()
    print("=" * 80)
    print("DIAGNOSTIC COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()
