#!/usr/bin/env python3
"""
Pair Trading 백테스트 스크립트

BTC/ETH 스프레드 트레이딩
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pandas as pd

from intraday.data import get_config
from intraday.strategies.multi import PairTradingStrategy
from intraday.backtest.pair_runner import PairBacktestRunner


def main():
    parser = argparse.ArgumentParser(description="Run Pair Trading Backtest")
    parser.add_argument("--coin-a", default="BTCUSDT")
    parser.add_argument("--coin-b", default="ETHUSDT")
    parser.add_argument("--entry", type=float, default=2.0, help="Z-score entry threshold")
    parser.add_argument("--exit", type=float, default=0.5, help="Z-score exit threshold")
    parser.add_argument("--lookback", type=int, default=288, help="Lookback (candles)")  # 1일 = 288 * 5분
    parser.add_argument("--start", default="2025-03-01")
    parser.add_argument("--end", default="2025-09-30")
    parser.add_argument("--capital", type=float, default=10000)
    parser.add_argument("--position-size", type=float, default=0.5)
    
    args = parser.parse_args()
    
    config = get_config()
    candle_dir = config.data_dir / "candles"
    
    print("=" * 60)
    print("🔄 Pair Trading Backtest")
    print("=" * 60)
    print(f"Pair:         {args.coin_a} / {args.coin_b}")
    print(f"Period:       {args.start} ~ {args.end}")
    print(f"Entry Z:      ±{args.entry}")
    print(f"Exit Z:       ±{args.exit}")
    print(f"Lookback:     {args.lookback} candles ({args.lookback * 5 / 60:.1f}h)")
    print(f"Capital:      ${args.capital:,.2f}")
    print(f"Position:     {args.position_size * 100:.0f}%")
    print("=" * 60)
    
    # 데이터 로드
    print("\n📥 Loading data...")
    
    file_a = candle_dir / f"{args.coin_a}_5m.parquet"
    file_b = candle_dir / f"{args.coin_b}_5m.parquet"
    
    if not file_a.exists() or not file_b.exists():
        print(f"❌ Candle files not found. Run preprocess_data.py first.")
        return 1
    
    df_a = pd.read_parquet(file_a)
    df_b = pd.read_parquet(file_b)
    
    # 시간 필터
    start_dt = pd.to_datetime(args.start)
    end_dt = pd.to_datetime(args.end)
    
    df_a = df_a[(df_a["timestamp"] >= start_dt) & (df_a["timestamp"] <= end_dt)]
    df_b = df_b[(df_b["timestamp"] >= start_dt) & (df_b["timestamp"] <= end_dt)]
    
    if "price" not in df_a.columns:
        df_a["price"] = df_a["close"]
    if "price" not in df_b.columns:
        df_b["price"] = df_b["close"]
    
    print(f"  {args.coin_a}: {len(df_a):,} candles")
    print(f"  {args.coin_b}: {len(df_b):,} candles")
    
    # 전략 생성
    strategy = PairTradingStrategy(
        coin_a=args.coin_a,
        coin_b=args.coin_b,
        zscore_entry=args.entry,
        zscore_exit=args.exit,
        lookback=args.lookback,
    )
    
    # 백테스트
    print("\n⚡ Running backtest...")
    runner = PairBacktestRunner(
        strategy=strategy,
        initial_capital=args.capital,
        position_size_pct=args.position_size,
        fee_rate=0.001,
    )
    
    runner.load_data(df_a, df_b)
    result = runner.run()
    
    print(result.summary())
    
    # 거래 로그
    if result.trade_log:
        print("📊 Sample Trades:")
        for t in result.trade_log[:5]:
            exit_z = f"{t.exit_zscore:.2f}" if t.exit_zscore is not None else "N/A"
            print(f"  {t.direction}: Z {t.entry_zscore:.2f} → {exit_z}, PnL=${t.pnl:.2f}")
    
    # 저장
    output_dir = Path(__file__).parent.parent / "output"
    output_dir.mkdir(exist_ok=True)
    result.equity_curve.to_csv(output_dir / "equity_pair_trading.csv")
    print(f"\n💾 Saved to {output_dir}/equity_pair_trading.csv")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
