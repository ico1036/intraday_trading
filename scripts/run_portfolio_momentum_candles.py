#!/usr/bin/env python3
"""
포트폴리오 모멘텀 전략 백테스트 - 캔들 데이터 사용

전처리된 OHLCV 캔들 데이터로 빠르게 백테스트합니다.

Usage:
    python scripts/run_portfolio_momentum_candles.py
    python scripts/run_portfolio_momentum_candles.py --symbols BTCUSDT ETHUSDT
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pandas as pd

from intraday.data import get_config
from intraday.strategies.multi import PortfolioMomentum
from intraday.backtest.multi_runner import PortfolioBacktestRunner


def load_candle_data(
    symbols: list[str],
    candle_dir: Path,
    interval: int = 5,
    start_date: str = None,
    end_date: str = None,
) -> dict[str, pd.DataFrame]:
    """
    캔들 데이터 로드
    
    Args:
        symbols: 심볼 목록
        candle_dir: 캔들 파일 디렉토리
        interval: 캔들 간격 (분)
        start_date: 시작일 (YYYY-MM-DD)
        end_date: 종료일 (YYYY-MM-DD)
    """
    data = {}
    
    for symbol in symbols:
        file_path = candle_dir / f"{symbol}_{interval}m.parquet"
        
        if not file_path.exists():
            print(f"  {symbol}: File not found ({file_path.name})")
            continue
        
        print(f"  Loading {symbol}...", end=" ", flush=True)
        
        df = pd.read_parquet(file_path)
        
        # 시간 필터링
        if start_date:
            start_dt = pd.to_datetime(start_date)
            df = df[df["timestamp"] >= start_dt]
        if end_date:
            end_dt = pd.to_datetime(end_date)
            df = df[df["timestamp"] <= end_dt]
        
        # price 컬럼 추가 (close 사용)
        if "price" not in df.columns:
            df["price"] = df["close"]
        
        data[symbol] = df
        print(f"OK ({len(df):,} candles)")
    
    return data


def main():
    parser = argparse.ArgumentParser(description="Run Portfolio Momentum with Candle Data")
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT"])
    parser.add_argument("--interval", type=int, default=5)
    parser.add_argument("--start", default="2025-03-01", help="Start date (IS period)")
    parser.add_argument("--end", default="2025-09-30", help="End date")
    parser.add_argument("--lookback", type=int, default=60, help="Lookback in minutes")
    parser.add_argument("--top-n", type=int, default=1)
    parser.add_argument("--bottom-n", type=int, default=1)
    parser.add_argument("--capital", type=float, default=10000)
    parser.add_argument("--position-size", type=float, default=0.3)
    parser.add_argument("--rebalance", type=int, default=60, help="Rebalance interval (minutes)")
    
    args = parser.parse_args()
    
    config = get_config()
    candle_dir = config.data_dir / "candles"
    
    print("=" * 60)
    print("🚀 Portfolio Momentum Backtest (Candle Data)")
    print("=" * 60)
    print(f"Symbols:      {args.symbols}")
    print(f"Period:       {args.start} ~ {args.end}")
    print(f"Interval:     {args.interval}m candles")
    print(f"Lookback:     {args.lookback} min")
    print(f"Top/Bottom:   {args.top_n} / {args.bottom_n}")
    print(f"Capital:      ${args.capital:,.2f}")
    print(f"Position:     {args.position_size * 100:.0f}%")
    print(f"Rebalance:    {args.rebalance} min")
    print("=" * 60)
    
    # 데이터 로드
    print("\n📥 Loading candle data...")
    data = load_candle_data(
        symbols=args.symbols,
        candle_dir=candle_dir,
        interval=args.interval,
        start_date=args.start,
        end_date=args.end,
    )
    
    if len(data) < 2:
        print("\n❌ Need at least 2 symbols with data")
        return 1
    
    available = list(data.keys())
    print(f"\n✅ Loaded {len(available)} symbols")
    
    # 전략 생성
    strategy = PortfolioMomentum(
        symbols=available,
        lookback_minutes=args.lookback,
        top_n=min(args.top_n, len(available) - 1),
        bottom_n=min(args.bottom_n, len(available) - 1),
    )
    
    # 백테스트
    print("\n⚡ Running backtest...")
    runner = PortfolioBacktestRunner(
        strategy=strategy,
        initial_capital=args.capital,
        position_size_pct=args.position_size,
        rebalance_minutes=args.rebalance,
        fee_rate=0.001,  # 0.1% (spread + slippage 포함)
    )
    
    runner.load_data(data)
    result = runner.run()
    
    # 결과
    print(result.summary())
    
    # 심볼별
    print("📊 Per-Symbol Breakdown:")
    breakdown = result.get_symbol_breakdown()
    for symbol, stats in breakdown.items():
        wr = stats["wins"] / stats["trades"] * 100 if stats["trades"] > 0 else 0
        print(f"  {symbol}: PnL=${stats['total_pnl']:,.2f}, Trades={stats['trades']}, WR={wr:.1f}%")
    
    # 저장
    output_dir = Path(__file__).parent.parent / "output"
    output_dir.mkdir(exist_ok=True)
    
    result.equity_curve.to_csv(output_dir / "equity_portfolio_momentum.csv")
    print(f"\n💾 Saved to {output_dir}/equity_portfolio_momentum.csv")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
