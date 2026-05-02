#!/usr/bin/env python3
"""
포트폴리오 모멘텀 전략 백테스트 실행 스크립트

실제 데이터로 MomentumPortfolio 전략을 백테스트합니다.

Usage:
    python scripts/run_portfolio_momentum.py
    python scripts/run_portfolio_momentum.py --timeframe tf1 --period is
    python scripts/run_portfolio_momentum.py --symbols BTCUSDT ETHUSDT --lookback 30
"""

import argparse
import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pandas as pd

from intraday.data import TickDataLoader, TimeframeConfig, get_config
from intraday.strategies.multi import PortfolioMomentum
from intraday.backtest.multi_runner import PortfolioBacktestRunner


def load_price_data(
    symbols: list[str],
    timeframe: str,
    period: str,
    resample_minutes: int = 1,
) -> dict[str, pd.DataFrame]:
    """
    여러 심볼의 가격 데이터 로드
    
    Args:
        symbols: 심볼 목록
        timeframe: 타임프레임 ID
        period: 기간 ("eda", "is", "os")
        resample_minutes: 리샘플링 간격 (분)
        
    Returns:
        {symbol: DataFrame} 형태
    """
    data = {}
    
    for symbol in symbols:
        try:
            print(f"Loading {symbol}...", end=" ", flush=True)
            loader = TickDataLoader.from_timeframe(symbol, timeframe, period)
            
            # DataFrame으로 로드
            df = loader.to_dataframe()
            
            if df.empty:
                print("EMPTY")
                continue
            
            # 리샘플링 (OHLCV)
            df = df.set_index("timestamp")
            ohlcv = df["price"].resample(f"{resample_minutes}min").agg({
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "price": "last",  # 백테스터용
            }).dropna()
            
            ohlcv = ohlcv.reset_index()
            ohlcv = ohlcv.rename(columns={"timestamp": "timestamp"})
            
            data[symbol] = ohlcv
            print(f"OK ({len(ohlcv):,} bars)")
            
        except FileNotFoundError as e:
            print(f"NOT FOUND: {e}")
        except Exception as e:
            print(f"ERROR: {e}")
    
    return data


def main():
    parser = argparse.ArgumentParser(description="Run Portfolio Momentum Backtest")
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=None,
        help="Symbols to trade (default: from config)",
    )
    parser.add_argument(
        "--timeframe",
        default="tf1",
        help="Timeframe ID (default: tf1)",
    )
    parser.add_argument(
        "--period",
        default="is",
        choices=["eda", "is", "os"],
        help="Period (default: is)",
    )
    parser.add_argument(
        "--lookback",
        type=int,
        default=60,
        help="Lookback minutes for momentum (default: 60)",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=1,
        help="Number of coins to long (default: 1)",
    )
    parser.add_argument(
        "--bottom-n",
        type=int,
        default=1,
        help="Number of coins to short (default: 1)",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=10000,
        help="Initial capital (default: 10000)",
    )
    parser.add_argument(
        "--position-size",
        type=float,
        default=0.3,
        help="Position size as fraction of capital (default: 0.3)",
    )
    parser.add_argument(
        "--rebalance",
        type=int,
        default=60,
        help="Rebalance interval in minutes (default: 60)",
    )
    parser.add_argument(
        "--resample",
        type=int,
        default=5,
        help="Data resample interval in minutes (default: 5)",
    )
    
    args = parser.parse_args()
    
    # 설정 로드
    config = get_config()
    symbols = args.symbols or config.symbols
    
    print("=" * 60)
    print("🚀 Portfolio Momentum Backtest")
    print("=" * 60)
    print(f"Symbols:      {symbols}")
    print(f"Timeframe:    {args.timeframe} / {args.period}")
    print(f"Lookback:     {args.lookback} min")
    print(f"Top N:        {args.top_n}")
    print(f"Bottom N:     {args.bottom_n}")
    print(f"Capital:      ${args.capital:,.2f}")
    print(f"Position:     {args.position_size * 100:.0f}%")
    print(f"Rebalance:    {args.rebalance} min")
    print("=" * 60)
    
    # 데이터 로드
    print("\n📥 Loading data...")
    data = load_price_data(
        symbols=symbols,
        timeframe=args.timeframe,
        period=args.period,
        resample_minutes=args.resample,
    )
    
    if len(data) < 2:
        print("\n❌ Not enough data. Need at least 2 symbols.")
        return
    
    available_symbols = list(data.keys())
    print(f"\n✅ Loaded {len(available_symbols)} symbols: {available_symbols}")
    
    # 전략 생성
    strategy = PortfolioMomentum(
        symbols=available_symbols,
        lookback_minutes=args.lookback,
        top_n=min(args.top_n, len(available_symbols) - 1),
        bottom_n=min(args.bottom_n, len(available_symbols) - 1),
    )
    
    # 백테스트 실행
    print("\n⚡ Running backtest...")
    runner = PortfolioBacktestRunner(
        strategy=strategy,
        initial_capital=args.capital,
        position_size_pct=args.position_size,
        rebalance_minutes=args.rebalance,
    )
    
    runner.load_data(data)
    result = runner.run()
    
    # 결과 출력
    print(result.summary())
    
    # 심볼별 분석
    print("\n📊 Per-Symbol Breakdown:")
    breakdown = result.get_symbol_breakdown()
    for symbol, stats in breakdown.items():
        win_rate = stats["wins"] / stats["trades"] * 100 if stats["trades"] > 0 else 0
        print(f"  {symbol}: PnL=${stats['total_pnl']:,.2f}, Trades={stats['trades']}, WinRate={win_rate:.1f}%")
    
    # 에쿼티 커브 저장
    output_dir = Path(__file__).parent.parent / "output"
    output_dir.mkdir(exist_ok=True)
    
    equity_file = output_dir / f"equity_{args.timeframe}_{args.period}.csv"
    result.equity_curve.to_csv(equity_file)
    print(f"\n💾 Equity curve saved to: {equity_file}")


if __name__ == "__main__":
    main()
