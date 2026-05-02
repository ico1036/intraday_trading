#!/usr/bin/env python3
"""
ATR+볼륨바 기반 포트폴리오 전략 백테스트 스크립트

Usage:
    python scripts/run_atr_volume_backtest.py
"""

import sys
from pathlib import Path
from datetime import datetime

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from intraday.data import TickDataLoader
from intraday.backtest.multi_tick_runner import PortfolioTickBacktestRunner
from intraday.candle_builder import CandleType
from intraday.strategies.multi.atr_volume_risk_momentum import ATRVolumeRiskMomentumStrategy


def main():
    # Configuration
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
    data_base = Path(__file__).parent.parent / "data" / "futures_ticks"

    # Strategy parameters (from algorithm_prompt.txt)
    strategy_params = {
        "lookback_minutes": 60,
        "atr_window": 20,
        "atr_stop_multiplier": 2.0,
        "target_rr": 1.8,
        "min_rr": 1.0,
        "rebalance_interval_minutes": 30,
        "top_n": 2,
        "bottom_n": 1,
        "max_units_single": 4,
        "max_units_corr_cluster": 6,
        "max_units_total": 6,
    }

    # Backtest configuration
    initial_capital = 10000.0
    position_size_pct = 0.5
    leverage = 5
    bar_size = 50.0  # Volume bar size (BTC 기준)
    maker_fee = 0.00017
    taker_fee = 0.0002

    # Period (IS 1 month)
    start_time = datetime(2025, 1, 1, 0, 0, 0)
    end_time = datetime(2025, 1, 31, 23, 59, 59)

    print("=" * 60)
    print("🚀 ATRVolumeRiskMomentum Backtest")
    print("=" * 60)
    print(f"Symbols:        {symbols}")
    print(f"Period:         {start_time.date()} ~ {end_time.date()}")
    print(f"Bar Type:       VOLUME ({bar_size})")
    print(f"Capital:        ${initial_capital:,.2f}")
    print(f"Position Size:  {position_size_pct * 100:.0f}%")
    print(f"Leverage:       {leverage}x")
    print(f"Fees:           Maker {maker_fee*100:.3f}% / Taker {taker_fee*100:.3f}%")
    print("=" * 60)
    print("\nStrategy Parameters:")
    for k, v in strategy_params.items():
        print(f"  {k}: {v}")
    print("=" * 60)

    # Load data
    print("\n📥 Loading tick data...")
    loaders = {}
    for sym in symbols:
        sym_path = data_base / sym / "2025"
        if not sym_path.exists():
            print(f"  {sym}: NOT FOUND at {sym_path}")
            continue
        try:
            loader = TickDataLoader(sym_path, symbol=sym)
            loaders[sym] = loader
            print(f"  {sym}: OK")
        except Exception as e:
            print(f"  {sym}: ERROR - {e}")

    if len(loaders) < 2:
        print("\n❌ Not enough data. Need at least 2 symbols.")
        return

    available_symbols = list(loaders.keys())
    print(f"\n✅ Loaded {len(available_symbols)} symbols: {available_symbols}")

    # Create strategy
    strategy = ATRVolumeRiskMomentumStrategy(
        symbols=available_symbols,
        **strategy_params,
    )

    # Create runner
    print("\n⚡ Running backtest...")
    runner = PortfolioTickBacktestRunner(
        strategy=strategy,
        data_loaders=loaders,
        bar_type=CandleType.VOLUME,
        bar_size=bar_size,
        initial_capital=initial_capital,
        position_size_pct=position_size_pct,
        leverage=leverage,
        maker_fee_rate=maker_fee,
        taker_fee_rate=taker_fee,
    )

    # Run backtest
    result = runner.run(start_time=start_time, end_time=end_time)

    # Print results
    print("\n" + "=" * 60)
    print("📊 BACKTEST RESULTS")
    print("=" * 60)
    print(f"Initial Capital:  ${result.initial_capital:,.2f}")
    print(f"Final Capital:    ${result.final_capital:,.2f}")
    print(f"Total Return:     {result.total_return * 100:.2f}%")
    print(f"Sharpe Ratio:     {result.sharpe_ratio:.3f}")
    print(f"Max Drawdown:     {result.max_drawdown * 100:.2f}%")
    print(f"Total Trades:     {result.total_trades}")
    print(f"Win Rate:         {result.win_rate * 100:.1f}%")
    print(f"Profit Factor:    {result.profit_factor:.2f}")
    print("=" * 60)

    # Success criteria check
    print("\n🎯 SUCCESS CRITERIA CHECK:")
    criteria = [
        ("Sharpe Ratio >= 1.0", result.sharpe_ratio >= 1.0, result.sharpe_ratio),
        ("Profit Factor >= 1.3", result.profit_factor >= 1.3, result.profit_factor),
        ("Max Drawdown >= -15%", result.max_drawdown >= -0.15, result.max_drawdown * 100),
        ("Total Return >= 5%", result.total_return >= 0.05, result.total_return * 100),
        ("Min Trades >= 30", result.total_trades >= 30, result.total_trades),
    ]

    all_pass = True
    for name, passed, value in criteria:
        status = "✅ PASS" if passed else "❌ FAIL"
        if "%" in name:
            print(f"  {status} {name}: {value:.2f}%")
        else:
            print(f"  {status} {name}: {value:.3f}" if isinstance(value, float) else f"  {status} {name}: {value}")
        if not passed:
            all_pass = False

    print("\n" + "=" * 60)
    if all_pass:
        print("🎉 ALL CRITERIA PASSED - STRATEGY APPROVED!")
    else:
        print("⚠️  SOME CRITERIA FAILED - NEEDS IMPROVEMENT")
    print("=" * 60)

    # Symbol breakdown
    print("\n📊 Per-Symbol Breakdown:")
    breakdown = result.get_symbol_breakdown()
    for symbol, stats in breakdown.items():
        win_rate = stats["wins"] / stats["trades"] * 100 if stats["trades"] > 0 else 0
        print(f"  {symbol}: PnL=${stats['total_pnl']:,.2f}, Trades={stats['trades']}, WinRate={win_rate:.1f}%")

    # Save results
    output_dir = Path(__file__).parent.parent / "output"
    output_dir.mkdir(exist_ok=True)

    equity_file = output_dir / "equity_atr_volume_is.csv"
    result.equity_curve.to_csv(equity_file)
    print(f"\n💾 Equity curve saved to: {equity_file}")

    return result


if __name__ == "__main__":
    main()
