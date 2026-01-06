#!/usr/bin/env python3
"""
VPIN Breakout 전략 백테스트 (선물 + 레버리지)

VPIN(Volume-Synchronized Probability of Informed Trading) 기반 breakout 전략을
선물 데이터와 레버리지로 백테스트합니다.

사용법:
    # 기본 실행
    python scripts/run_vpin_backtest.py

    # 시각화 포함
    python scripts/run_vpin_backtest.py --visualize

    # 리포트 저장
    python scripts/run_vpin_backtest.py --save-report

교육 포인트:
    1. VPIN: Order flow toxicity 지표
    2. Breakout + VPIN: 노이즈 필터링
    3. 선물 레버리지: 10x 마진 거래
    4. 양방향 거래: 롱/숏 모두 가능
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

# 프로젝트 루트 추가
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from intraday import (
    TickDataDownloader,
    TickDataLoader,
    TickBacktestRunner,
    BarType,
    MarketType,
    BacktestVisualizer,
)
from intraday.strategies.tick import VPINBreakoutStrategy


def main():
    """VPIN Breakout 백테스트 메인 함수"""

    # 인자 파싱
    parser = argparse.ArgumentParser(description="VPIN Breakout 백테스트 (선물)")
    parser.add_argument(
        "--visualize",
        action="store_true",
        help="시각화 HTML 파일 생성",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="시각화 파일 저장 경로",
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
    parser.add_argument(
        "--leverage",
        type=int,
        default=10,
        help="레버리지 배율 (기본: 10)",
    )
    args = parser.parse_args()

    # === 설정 ===
    symbol = "BTCUSDT"
    year = 2024
    month = 1
    data_dir = Path("./data/futures_ticks")

    # 전략 파라미터
    quantity = 0.01  # BTC
    n_buckets = 50  # VPIN 계산 윈도우
    breakout_lookback = 20  # 돌파 판단 기간
    vpin_threshold = 0.4  # VPIN 진입 임계값

    # 백테스트 파라미터
    bar_type = BarType.VOLUME
    bar_size = 10.0  # 10 BTC마다 바 생성
    initial_capital = 10000.0
    leverage = args.leverage

    print("=" * 60)
    print("VPIN Breakout 백테스트 (선물 + 레버리지)")
    print("=" * 60)

    # === 1. 선물 데이터 다운로드 ===
    print("\n[Step 1] 선물 데이터 다운로드...")

    downloader = TickDataDownloader(market_type=MarketType.FUTURES)

    try:
        filepath = downloader.download_monthly(
            symbol=symbol,
            year=year,
            month=month,
            output_dir=data_dir,
        )
        print(f"데이터 파일: {filepath}")
    except Exception as e:
        print(f"다운로드 실패: {e}")
        print("이미 다운로드된 파일이 있는지 확인합니다...")

    # === 2. 데이터 로드 ===
    print("\n[Step 2] 데이터 로드...")

    try:
        loader = TickDataLoader(data_dir, symbol=symbol)
        print(f"로드된 파일 수: {loader.file_count}")
    except FileNotFoundError as e:
        print(f"데이터 파일을 찾을 수 없습니다: {e}")
        print("\n먼저 데이터를 다운로드하세요.")
        return

    # === 3. 전략 생성 ===
    print("\n[Step 3] VPIN Breakout 전략 생성...")

    strategy = VPINBreakoutStrategy(
        quantity=quantity,
        n_buckets=n_buckets,
        breakout_lookback=breakout_lookback,
        vpin_threshold=vpin_threshold,
    )

    print(f"전략: {strategy.__class__.__name__}")
    print(f"  - Quantity: {quantity} BTC")
    print(f"  - VPIN Buckets: {n_buckets}")
    print(f"  - Breakout Lookback: {breakout_lookback}")
    print(f"  - VPIN Threshold: {vpin_threshold}")

    # === 4. 백테스트 실행 (선물 + 레버리지) ===
    print(f"\n[Step 4] 백테스트 실행 ({leverage}x 레버리지)...")
    print(f"바 타입: {bar_type.value}, 바 크기: {bar_size}")

    runner = TickBacktestRunner(
        strategy=strategy,
        data_loader=loader,
        bar_type=bar_type,
        bar_size=bar_size,
        initial_capital=initial_capital,
        symbol=symbol,
        leverage=leverage,  # 선물 레버리지
    )

    report = runner.run(progress_interval=50000)

    # === 5. 결과 출력 ===
    print("\n[Step 5] 백테스트 결과")
    print("=" * 60)
    report.print_summary()

    # 선물 모드 정보
    print(f"\n[선물 모드]")
    print(f"  - 레버리지: {leverage}x")
    print(f"  - 실효 자본: ${initial_capital * leverage:,.2f}")

    # === 6. 시각화 (옵션) ===
    if args.visualize:
        print("\n[Step 6] 시각화 생성...")

        results_dir = Path("./results")
        results_dir.mkdir(exist_ok=True)

        if args.output:
            output_file = Path(args.output)
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = results_dir / f"vpin_backtest_{symbol}_{timestamp}.html"

        visualizer = BacktestVisualizer(report, runner.trader.trades)
        visualizer.save_html(str(output_file))

        print(f"\n시각화 파일 저장됨: {output_file}")

    # === 7. 리포트 저장 (옵션) ===
    if args.save_report:
        print("\n[Step 7] 리포트 저장...")

        report_dir = runner.save_report(args.report_dir)
        print(f"\n리포트 저장됨: {report_dir}")


if __name__ == "__main__":
    main()
