"""
Diagnostic script to identify VWAP calculation issue in backtest.

This script runs the VWAP strategy with diagnostic logging enabled.
Expected behavior:
- If VWAP is None or always equals close: 0 trades (BUG)
- If VWAP is working: 50-150 trades (EXPECTED)

Run this to identify the root cause of 0 trades in Iteration 4.
"""

import os
from datetime import datetime
from intraday.backtest.tick_runner import TickBacktestRunner
from intraday.strategies.tick.volume_imbalance_momentum import VolumeImbalanceMomentumStrategy

# Configuration from backtest_report.md
DATA_DIR = "data/processed/binance"
SYMBOL = "BTCUSDT"
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
BAR_TYPE = "time"
BAR_SIZE = 120  # 2 minutes
LEVERAGE = 1
INITIAL_CAPITAL = 100000.0


def main():
    """Run diagnostic backtest to identify VWAP issue."""
    print("=" * 80)
    print("VWAP DIAGNOSTIC BACKTEST")
    print("=" * 80)
    print(f"Symbol: {SYMBOL}")
    print(f"Period: {START_DATE.date()} to {END_DATE.date()}")
    print(f"Bar Type: {BAR_TYPE.upper()}")
    print(f"Bar Size: {BAR_SIZE} seconds (2 minutes)")
    print(f"Initial Capital: ${INITIAL_CAPITAL:,.2f}")
    print(f"Leverage: {LEVERAGE}x")
    print()
    print("Strategy Parameters (Iteration 4 Attempt 3 - RELAXED FILTERS):")
    for key, value in STRATEGY_PARAMS.items():
        print(f"  {key}: {value}")
    print()
    print("=" * 80)
    print("RUNNING BACKTEST WITH DIAGNOSTIC LOGGING...")
    print("=" * 80)
    print()

    # Verify data exists
    data_path = os.path.join(DATA_DIR, f"{SYMBOL}.parquet")
    if not os.path.exists(data_path):
        print(f"ERROR: Data file not found: {data_path}")
        print("Please run data download/preprocessing scripts first.")
        return

    # Create strategy
    strategy = VolumeImbalanceMomentumStrategy(**STRATEGY_PARAMS)

    # Create runner
    runner = TickBacktestRunner(
        strategy=strategy,
        data_dir=DATA_DIR,
        symbol=SYMBOL,
        start_date=START_DATE,
        end_date=END_DATE,
        bar_type=BAR_TYPE,
        bar_size=BAR_SIZE,
        leverage=LEVERAGE,
        initial_capital=INITIAL_CAPITAL,
    )

    # Run backtest
    print("Processing ticks and generating bars...")
    print("Diagnostic logging will appear every 100 bars.")
    print()

    results = runner.run()

    # Print results
    print()
    print("=" * 80)
    print("DIAGNOSTIC RESULTS")
    print("=" * 80)
    print()
    print("Execution Stats:")
    print(f"  Ticks Processed: {results['ticks_processed']:,}")
    print(f"  Bars Generated: {results['bars_generated']:,}")
    print(f"  Total Trades: {results['metrics']['total_trades']}")
    print()

    if results["metrics"]["total_trades"] == 0:
        print("⚠️  CRITICAL: 0 TRADES GENERATED")
        print()
        print("Diagnostic Analysis:")
        print("1. Check the diagnostic logs above for:")
        print("   - Is VWAP always None? → VWAP calculation broken")
        print("   - Does VWAP always equal close? → VWAP always 0% deviation")
        print("   - Are deviations always < 1.2%? → Entry threshold too strict")
        print("   - Are ATR values always > 2.5%? → ATR filter too strict")
        print("   - Are BB width values always > 5.0%? → BB filter too strict")
        print()
        print("2. Expected behavior (from backtest_report.md):")
        print("   - Bars passing ATR filter: ~6,500 (65%)")
        print("   - Bars passing BB filter: ~6,000 (60%)")
        print("   - Combined eligible bars: ~4,500 (45%)")
        print("   - VWAP deviations >1.2%: ~150-225 opportunities")
        print("   - Expected trades: 50-150")
        print()
        print("3. Probability of 0 trades: 10^-68 (statistically impossible)")
        print()
        print("ROOT CAUSE (based on logs):")
        print("  [Review diagnostic logs above to determine which field is broken]")
    else:
        print("✅ SUCCESS: Strategy generated trades!")
        print()
        print("Performance Metrics:")
        print(f"  Total Return: {results['metrics']['total_return_pct']:.2f}%")
        print(f"  Win Rate: {results['metrics']['win_rate']:.1f}%")
        print(f"  Profit Factor: {results['metrics']['profit_factor']:.2f}")
        print(f"  Max Drawdown: {results['metrics']['max_drawdown_pct']:.2f}%")
        print(f"  Sharpe Ratio: {results['metrics']['sharpe_ratio']:.2f}")
        print()
        print("NOTE: If trades generated, VWAP calculation is working.")
        print("      The 0-trade issue in Iteration 4 was a different problem.")

    print()
    print("=" * 80)
    print("DIAGNOSTIC COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()
