#!/usr/bin/env python3
"""
Orderbook 기반 백테스트 예제 스크립트

저장된 오더북 스냅샷 데이터를 사용하여 OBI 전략을 백테스트합니다.

사용법:
    # 1. 먼저 오더북 데이터 수집
    python scripts/record_orderbook.py
    
    # 2. 백테스트 실행 (텍스트 리포트만)
    python scripts/run_orderbook_backtest.py
    
    # 3. 백테스트 실행 (시각화 포함)
    python scripts/run_orderbook_backtest.py --visualize

교육 포인트:
    - 오더북 데이터는 Binance에서 제공하지 않으므로 직접 수집 필요
    - ForwardRunner와 동일한 전략을 과거 데이터로 테스트
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

# 프로젝트 루트 추가
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from intraday import (
    OrderbookDataLoader,
    OrderbookBacktestRunner,
    OBIStrategy,
    BacktestVisualizer,
)


def main():
    """Orderbook 백테스트 메인 함수"""
    
    # 인자 파싱
    parser = argparse.ArgumentParser(description="Orderbook 기반 백테스트")
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
    args = parser.parse_args()
    
    # === 설정 ===
    data_dir = Path("./data/orderbook")
    symbol = "btcusdt"
    
    # 전략 파라미터
    buy_threshold = 0.3
    sell_threshold = -0.3
    quantity = 0.01  # BTC
    
    # 백테스트 파라미터
    initial_capital = 10000.0
    
    print("=" * 60)
    print("Orderbook 기반 백테스트 예제")
    print("=" * 60)
    
    # === 1. 데이터 로드 ===
    print("\n[Step 1] 데이터 로드...")
    
    try:
        loader = OrderbookDataLoader(data_dir, symbol=symbol)
        print(f"로드된 파일 수: {loader.file_count}")
        print(f"호가 깊이: {loader.depth_levels} levels")
    except FileNotFoundError as e:
        print(f"데이터 파일을 찾을 수 없습니다: {e}")
        print("\n먼저 오더북 데이터를 수집하세요:")
        print("  python scripts/record_orderbook.py")
        return
    
    # === 2. 전략 생성 ===
    print("\n[Step 2] 전략 생성...")
    
    strategy = OBIStrategy(
        buy_threshold=buy_threshold,
        sell_threshold=sell_threshold,
        quantity=quantity,
    )
    print(f"전략: {strategy.__class__.__name__}")
    print(f"  - Buy Threshold: {buy_threshold}")
    print(f"  - Sell Threshold: {sell_threshold}")
    print(f"  - Quantity: {quantity} BTC")
    
    # === 3. 백테스트 실행 ===
    print("\n[Step 3] 백테스트 실행...")
    
    runner = OrderbookBacktestRunner(
        strategy=strategy,
        data_loader=loader,
        initial_capital=initial_capital,
        symbol=symbol.upper(),
    )
    
    report = runner.run(progress_interval=5000)
    
    # === 4. 결과 출력 ===
    print("\n[Step 4] 백테스트 결과")
    print("=" * 60)
    report.print_summary()
    
    # === 5. 시각화 (옵션) ===
    if args.visualize:
        print("\n[Step 5] 시각화 생성...")
        
        # 출력 디렉토리 생성
        results_dir = Path("./results")
        results_dir.mkdir(exist_ok=True)
        
        # 파일명 생성
        if args.output:
            output_file = Path(args.output)
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = results_dir / f"backtest_{symbol.upper()}_{timestamp}.html"
        
        visualizer = BacktestVisualizer(report, runner.trader.trades)
        visualizer.save_html(str(output_file))
        
        print(f"\n시각화 파일 저장됨: {output_file}")
        print("브라우저에서 열어서 확인하세요!")


if __name__ == "__main__":
    main()




