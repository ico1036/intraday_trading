"""
MA Crossover Strategy 백테스트 실행 스크립트

설정:
- 전략: MA Crossover (fast=5, slow=20)
- 캔들: Volume Bar (10 BTC)
- 레버리지: 5x (보수적)
- 기간: 7일 (충분한 신호 발생)
- 수수료: 0.05% (바이낸스 선물 테이커)
"""

import sys
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from intraday.strategies.tick.ma_crossover import MACrossoverStrategy
from intraday.backtest.tick_runner import TickBacktestRunner
from intraday.data.loader import TickDataLoader
from intraday.candle_builder import CandleType


def main():
    # 설정
    DATA_PATH = Path("./data/futures_ticks")
    START_DATE = datetime(2024, 3, 1)  # 3월 (변동성 높은 시기)
    END_DATE = datetime(2024, 3, 8)    # 7일간

    # 전략 파라미터
    QUANTITY = 0.01  # 0.01 BTC
    FAST_PERIOD = 10   # 단기 MA (10 bars)
    SLOW_PERIOD = 50   # 장기 MA (50 bars)

    # 백테스트 설정
    LEVERAGE = 3       # 보수적 레버리지
    FEE_RATE = 0.0005  # 0.05%
    BAR_SIZE = 10.0   # 10 BTC per bar

    print("=" * 60)
    print("MA Crossover Strategy Backtest")
    print("=" * 60)
    print(f"Period: {START_DATE.date()} ~ {END_DATE.date()}")
    print(f"Fast MA: {FAST_PERIOD}, Slow MA: {SLOW_PERIOD}")
    print(f"Leverage: {LEVERAGE}x, Fee: {FEE_RATE * 100:.2f}%")
    print(f"Bar Size: {BAR_SIZE} BTC per candle")
    print("=" * 60)

    # 전략 생성
    strategy = MACrossoverStrategy(
        quantity=QUANTITY,
        fast_period=FAST_PERIOD,
        slow_period=SLOW_PERIOD,
    )

    # 데이터 로더
    loader = TickDataLoader(DATA_PATH)

    # 백테스트 러너
    runner = TickBacktestRunner(
        strategy=strategy,
        data_loader=loader,
        bar_type=CandleType.VOLUME,
        bar_size=BAR_SIZE,
        initial_capital=10000.0,
        fee_rate=FEE_RATE,
        leverage=LEVERAGE,
    )

    # 실행
    print("\nRunning backtest...")
    report = runner.run(start_time=START_DATE, end_time=END_DATE)

    # 결과 출력
    print("\n" + "=" * 60)
    print("BACKTEST RESULTS")
    print("=" * 60)

    print(f"\n## Summary")
    print(f"Strategy: {report.strategy_name}")
    print(f"Period: {report.start_time} ~ {report.end_time}")
    print(f"Initial Capital: ${report.initial_capital:,.2f}")
    print(f"Final Capital: ${report.final_capital:,.2f}")
    print(f"Total Return: {report.total_return:+.2f}%")

    print(f"\n## Trading Statistics")
    print(f"Total Trades: {report.total_trades}")
    print(f"Win Rate: {report.win_rate:.1f}%")
    print(f"Winning Trades: {report.winning_trades}")
    print(f"Losing Trades: {report.losing_trades}")
    print(f"Profit Factor: {report.profit_factor:.2f}")
    print(f"Avg Win: ${report.avg_win:.2f}")
    print(f"Avg Loss: ${report.avg_loss:.2f}")

    print(f"\n## Risk Metrics")
    print(f"Max Drawdown: {report.max_drawdown:.2f}%")
    print(f"Sharpe Ratio: {report.sharpe_ratio:.2f}")

    print(f"\n## Costs")
    print(f"Total Fees: ${report.total_fees:.2f}")

    print(f"\n## Execution")
    print(f"Ticks Processed: {runner.tick_count:,}")
    print(f"Bars Generated: {runner.bar_count:,}")

    # 개별 거래 출력
    trades = runner._trader.trades
    if trades:
        print(f"\n## Trade Details (showing first 20)")
        print("-" * 80)
        print(f"{'#':>3} | {'Time':^19} | {'Side':^4} | {'Price':>10} | {'Qty':>8} | {'Fee':>8} | {'PnL':>10}")
        print("-" * 80)

        for i, trade in enumerate(trades[:20]):
            pnl_str = f"${trade.pnl:+.2f}" if trade.pnl != 0 else "-"
            print(f"{i+1:>3} | {str(trade.timestamp)[:19]} | {trade.side.name:^4} | ${trade.price:>9,.2f} | {trade.quantity:>8.4f} | ${trade.fee:>7.2f} | {pnl_str:>10}")

        if len(trades) > 20:
            print(f"... and {len(trades) - 20} more trades")

    print("\n" + "=" * 60)

    return report


if __name__ == "__main__":
    main()
