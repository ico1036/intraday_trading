#!/usr/bin/env python3
"""
Forward Test 실행 스크립트

CLI에서 포워드 테스트를 실행합니다.

사용법:
    python scripts/run_forward_test.py --duration 60
    python scripts/run_forward_test.py --symbol ethusdt --buy-threshold 0.4
"""

import argparse
import asyncio

from intraday import ForwardRunner, OBIStrategy


async def main():
    parser = argparse.ArgumentParser(description="Run Forward Test")
    parser.add_argument("--symbol", default="btcusdt", help="Trading symbol (default: btcusdt)")
    parser.add_argument("--capital", type=float, default=10000, help="Initial capital (default: 10000)")
    parser.add_argument("--fee-rate", type=float, default=0.001, help="Fee rate (default: 0.001)")
    parser.add_argument("--buy-threshold", type=float, default=0.3, help="OBI buy threshold (default: 0.3)")
    parser.add_argument("--sell-threshold", type=float, default=-0.3, help="OBI sell threshold (default: -0.3)")
    parser.add_argument("--quantity", type=float, default=0.01, help="Trade quantity (default: 0.01)")
    parser.add_argument("--duration", type=float, default=None, help="Test duration in seconds (default: infinite)")
    
    args = parser.parse_args()
    
    # 전략 생성
    strategy = OBIStrategy(
        buy_threshold=args.buy_threshold,
        sell_threshold=args.sell_threshold,
        quantity=args.quantity,
    )
    
    # 러너 생성
    runner = ForwardRunner(
        strategy=strategy,
        symbol=args.symbol,
        initial_capital=args.capital,
        fee_rate=args.fee_rate,
    )
    
    print("=" * 60)
    print("Forward Test Configuration")
    print("=" * 60)
    print(f"Symbol: {args.symbol.upper()}")
    print(f"Initial Capital: ${args.capital:,.2f}")
    print(f"Fee Rate: {args.fee_rate * 100:.2f}%")
    print(f"OBI Buy Threshold: {args.buy_threshold}")
    print(f"OBI Sell Threshold: {args.sell_threshold}")
    print(f"Quantity: {args.quantity}")
    print(f"Duration: {args.duration}s" if args.duration else "Duration: Infinite (Ctrl+C to stop)")
    print("=" * 60)
    print()
    
    try:
        await runner.run(duration_seconds=args.duration)
    except KeyboardInterrupt:
        print("\n[Main] Interrupted by user")
        await runner.stop()
    
    # 결과 출력
    print()
    report = runner.get_performance_report()
    report.print_summary()


if __name__ == "__main__":
    asyncio.run(main())

