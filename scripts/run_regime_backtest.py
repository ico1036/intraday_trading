#!/usr/bin/env python3
"""
RegimeStrategy 백테스트 예제 스크립트

국면 분석 기반 전략을 백테스트하고 리포트를 저장합니다.

사용법:
    # 기본 실행
    python scripts/run_regime_backtest.py

    # 리포트 저장
    python scripts/run_regime_backtest.py --save-report

    # 짧은 테스트 (1시간)
    python scripts/run_regime_backtest.py --hours 1 --save-report
"""

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 프로젝트 루트 추가
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from intraday import (
    TickDataDownloader,
    TickDataLoader,
    TickBacktestRunner,
    BarType,
)
from intraday.strategies.tick.regime import RegimeStrategy


def main():
    """RegimeStrategy 백테스트 메인 함수"""

    # 인자 파싱
    parser = argparse.ArgumentParser(description="RegimeStrategy 백테스트")
    parser.add_argument(
        "--hours",
        type=float,
        default=None,
        help="테스트 기간 (시간). 미지정 시 전체 데이터",
    )
    parser.add_argument(
        "--save-report",
        action="store_true",
        help="리포트 저장 (Parquet + PNG)",
    )
    parser.add_argument(
        "--report-dir",
        type=str,
        default="./reports",
        help="리포트 저장 디렉토리 (기본: ./reports)",
    )
    args = parser.parse_args()

    # === 설정 ===
    symbol = "BTCUSDT"
    data_dir = Path("./data/ticks")

    # 전략 파라미터 (RegimeStrategy 기본값 사용)
    quantity = 0.01  # BTC

    # 백테스트 파라미터
    bar_type = BarType.VOLUME
    bar_size = 10.0  # 10 BTC마다 바 생성
    initial_capital = 10000.0

    print("=" * 60)
    print("RegimeStrategy 백테스트")
    print("=" * 60)

    # === 1. 데이터 로드 ===
    print("\n[Step 1] 데이터 로드...")

    try:
        loader = TickDataLoader(data_dir, symbol=symbol)
        print(f"로드된 파일 수: {loader.file_count}")
    except FileNotFoundError as e:
        print(f"데이터 파일을 찾을 수 없습니다: {e}")
        print("\n먼저 데이터를 다운로드하세요:")
        print("  python scripts/run_tick_backtest.py")
        return

    # === 2. 전략 생성 ===
    print("\n[Step 2] 전략 생성...")

    strategy = RegimeStrategy(
        quantity=quantity,
        lookback=20,
        trend_threshold=0.3,
        trend_exit=-0.2,
        mean_revert_entry=-0.4,
        mean_revert_exit=0.0,
    )
    print(f"전략: {strategy.__class__.__name__}")
    print(f"  - Lookback: 20 bars")
    print(f"  - Trend Threshold: 0.3")
    print(f"  - Quantity: {quantity} BTC")

    # === 3. 백테스트 실행 ===
    print("\n[Step 3] 백테스트 실행...")
    print(f"바 타입: {bar_type.value}, 바 크기: {bar_size}")

    runner = TickBacktestRunner(
        strategy=strategy,
        data_loader=loader,
        bar_type=bar_type,
        bar_size=bar_size,
        initial_capital=initial_capital,
        symbol=symbol,
        latency_ms=50.0,
    )

    # 시간 범위 계산
    start_time = None
    end_time = None

    if args.hours:
        # 첫 N시간만 테스트
        start_time = datetime(2024, 1, 1, 0, 0, 0)
        end_time = start_time + timedelta(hours=args.hours)
        print(f"테스트 기간: {start_time} ~ {end_time}")

    report = runner.run(
        start_time=start_time,
        end_time=end_time,
        progress_interval=50000,
    )

    # === 4. 결과 출력 ===
    print("\n[Step 4] 백테스트 결과")
    print("=" * 60)
    report.print_summary()

    # 국면 분석 통계
    if strategy.current_regime:
        print("\n[국면 분석]")
        print(f"최종 국면: {strategy.current_regime.regime}")
        print(f"추세 강도: {strategy.current_regime.trend_score:.2f}")
        print(f"변동성: {strategy.current_regime.volatility_score:.2f}")

    # === 5. 리포트 저장 (옵션) ===
    if args.save_report:
        print("\n[Step 5] 리포트 저장...")

        report_dir = runner.save_report(args.report_dir)
        print(f"\n리포트 저장됨: {report_dir}")
        print("  - equity_curve.parquet: 누적 수익률 시계열")
        print("  - trades.parquet: 거래 내역")
        print("  - summary.parquet: 요약 지표")
        print("  - report.png: 시각화 리포트")

    # Equity curve 통계
    print(f"\n[Equity Curve 통계]")
    print(f"데이터 포인트 수: {len(runner.equity_curve)}")
    if runner.equity_curve:
        returns = [ep.cumulative_return_pct for ep in runner.equity_curve]
        print(f"최대 수익률: {max(returns):.2f}%")
        print(f"최소 수익률: {min(returns):.2f}%")


if __name__ == "__main__":
    main()
