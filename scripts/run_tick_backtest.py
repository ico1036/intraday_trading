#!/usr/bin/env python3
"""
Tick 기반 백테스트 예제 스크립트

Binance Public Data에서 aggTrades 데이터를 다운로드하고
볼륨바 기반으로 전략을 백테스트합니다.

사용법:
    # 텍스트 리포트만
    python scripts/run_tick_backtest.py

    # 시각화 포함 (HTML)
    python scripts/run_tick_backtest.py --visualize

    # 리포트 저장 (Parquet + PNG)
    python scripts/run_tick_backtest.py --save-report

교육 포인트:
    1. 데이터 다운로드 (처음 한 번만)
    2. 데이터 로드
    3. 백테스트 실행
    4. 성과 분석 및 시각화
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
    VolumeImbalanceStrategy,
    BacktestVisualizer,
)


def main():
    """Tick 백테스트 메인 함수"""
    
    # 인자 파싱
    parser = argparse.ArgumentParser(description="Tick 기반 백테스트")
    parser.add_argument(
        "--visualize",
        action="store_true",
        help="시각화 HTML 파일 생성",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="시각화 파일 저장 경로 (기본: ./results/backtest_YYYYMMDD_HHMMSS.html)",
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
    year = 2024
    month = 1  # 2024년 1월 데이터 사용
    data_dir = Path("./data/ticks")
    
    # 전략 파라미터
    buy_threshold = 0.3
    sell_threshold = -0.3
    quantity = 0.01  # BTC
    
    # 백테스트 파라미터
    bar_type = BarType.VOLUME
    bar_size = 10.0  # 10 BTC마다 바 생성
    initial_capital = 10000.0
    
    print("=" * 60)
    print("Tick 기반 백테스트 예제")
    print("=" * 60)
    
    # === 1. 데이터 다운로드 ===
    print("\n[Step 1] 데이터 다운로드...")
    
    downloader = TickDataDownloader()
    
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
    print("\n[Step 3] 전략 생성...")
    
    # VolumeImbalanceStrategy: 틱 데이터의 매수/매도 주도 비율 기반
    # (OBIStrategy는 오더북 기반이므로 틱 백테스트에 부적합)
    strategy = VolumeImbalanceStrategy(
        buy_threshold=buy_threshold,
        sell_threshold=sell_threshold,
        quantity=quantity,
    )
    print(f"전략: {strategy.__class__.__name__}")
    print(f"  - Buy Threshold: {buy_threshold}")
    print(f"  - Sell Threshold: {sell_threshold}")
    print(f"  - Quantity: {quantity} BTC")
    
    # === 4. 백테스트 실행 ===
    print("\n[Step 4] 백테스트 실행...")
    print(f"바 타입: {bar_type.value}, 바 크기: {bar_size}")
    
    runner = TickBacktestRunner(
        strategy=strategy,
        data_loader=loader,
        bar_type=bar_type,
        bar_size=bar_size,
        initial_capital=initial_capital,
        symbol=symbol,
    )
    
    # 처음 10,000개 틱만 테스트 (빠른 확인용)
    # 전체 데이터 테스트 시 start_time, end_time 제거
    report = runner.run(progress_interval=50000)
    
    # === 5. 결과 출력 ===
    print("\n[Step 5] 백테스트 결과")
    print("=" * 60)
    report.print_summary()
    
    # === 6. 시각화 (옵션) ===
    if args.visualize:
        print("\n[Step 6] 시각화 생성...")
        
        # 출력 디렉토리 생성
        results_dir = Path("./results")
        results_dir.mkdir(exist_ok=True)
        
        # 파일명 생성
        if args.output:
            output_file = Path(args.output)
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = results_dir / f"backtest_{symbol}_{timestamp}.html"
        
        visualizer = BacktestVisualizer(report, runner.trader.trades)
        visualizer.save_html(str(output_file))

        print(f"\n시각화 파일 저장됨: {output_file}")
        print("브라우저에서 열어서 확인하세요!")

    # === 7. 리포트 저장 (옵션) ===
    if args.save_report:
        print("\n[Step 7] 리포트 저장...")

        report_dir = runner.save_report(args.report_dir)
        print(f"\n리포트 저장됨: {report_dir}")
        print("  - equity_curve.parquet: 누적 수익률 시계열")
        print("  - trades.parquet: 거래 내역")
        print("  - summary.parquet: 요약 지표")
        print("  - report.png: 시각화 리포트")


if __name__ == "__main__":
    main()

