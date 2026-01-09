"""
VPIN Breakout Strategy 비교: Market vs Limit Order

동일 전략을 Market Order와 Limit Order로 실행하여 수수료 영향 비교.

예상 결과:
- Limit Order: 수수료 60% 절감 (0.05% → 0.02%)
- 체결률은 낮아질 수 있음
"""

import sys
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from intraday.strategies.tick.vpin_breakout import VPINBreakoutStrategy
from intraday.strategies.tick.vpin_breakout_limit import VPINBreakoutLimitStrategy
from intraday.backtest.tick_runner import TickBacktestRunner
from intraday.data.loader import TickDataLoader
from intraday.candle_builder import CandleType


def run_backtest(strategy, loader, name: str):
    """백테스트 실행 및 결과 반환"""
    runner = TickBacktestRunner(
        strategy=strategy,
        data_loader=loader,
        bar_type=CandleType.VOLUME,
        bar_size=10.0,  # 10 BTC per bar
        initial_capital=10000.0,
        leverage=5,
        # Maker/Taker 수수료 (Binance Futures)
        maker_fee_rate=0.0002,  # 0.02%
        taker_fee_rate=0.0005,  # 0.05%
    )

    print(f"\n{'='*60}")
    print(f"Running: {name}")
    print(f"{'='*60}")

    report = runner.run(
        start_time=datetime(2024, 3, 1),
        end_time=datetime(2024, 3, 8),
    )

    return report, runner


def print_comparison(market_report, market_runner, limit_report, limit_runner):
    """두 전략 결과 비교"""
    print("\n" + "=" * 70)
    print("COMPARISON: Market Order vs Limit Order")
    print("=" * 70)

    print(f"\n{'Metric':<25} {'Market Order':>20} {'Limit Order':>20}")
    print("-" * 70)

    # 수익률
    print(f"{'Total Return':<25} {market_report.total_return:>+19.2f}% {limit_report.total_return:>+19.2f}%")

    # 거래 수
    print(f"{'Total Trades':<25} {market_report.total_trades:>20} {limit_report.total_trades:>20}")

    # 승률
    print(f"{'Win Rate':<25} {market_report.win_rate:>19.1f}% {limit_report.win_rate:>19.1f}%")

    # 수수료
    print(f"{'Total Fees':<25} ${market_report.total_fees:>18.2f} ${limit_report.total_fees:>18.2f}")

    # 수수료 비율 (수익 대비)
    market_fee_ratio = (market_report.total_fees / market_report.initial_capital) * 100
    limit_fee_ratio = (limit_report.total_fees / limit_report.initial_capital) * 100
    print(f"{'Fee / Capital':<25} {market_fee_ratio:>19.2f}% {limit_fee_ratio:>19.2f}%")

    # 거래당 평균 수수료
    if market_report.total_trades > 0:
        market_avg_fee = market_report.total_fees / market_report.total_trades
    else:
        market_avg_fee = 0
    if limit_report.total_trades > 0:
        limit_avg_fee = limit_report.total_fees / limit_report.total_trades
    else:
        limit_avg_fee = 0
    print(f"{'Avg Fee per Trade':<25} ${market_avg_fee:>18.4f} ${limit_avg_fee:>18.4f}")

    # Max Drawdown
    print(f"{'Max Drawdown':<25} {market_report.max_drawdown:>19.2f}% {limit_report.max_drawdown:>19.2f}%")

    # Sharpe Ratio
    print(f"{'Sharpe Ratio':<25} {market_report.sharpe_ratio:>20.2f} {limit_report.sharpe_ratio:>20.2f}")

    # Profit Factor
    print(f"{'Profit Factor':<25} {market_report.profit_factor:>20.2f} {limit_report.profit_factor:>20.2f}")

    # 수수료 절감 분석
    print("\n" + "-" * 70)
    print("FEE SAVINGS ANALYSIS")
    print("-" * 70)

    if market_report.total_fees > 0:
        fee_saved = market_report.total_fees - limit_report.total_fees
        fee_saved_pct = (fee_saved / market_report.total_fees) * 100
        print(f"Fee Saved: ${fee_saved:.2f} ({fee_saved_pct:.1f}%)")

    # 순수익 비교 (수수료 제외)
    market_gross = (market_report.final_capital - market_report.initial_capital) + market_report.total_fees
    limit_gross = (limit_report.final_capital - limit_report.initial_capital) + limit_report.total_fees
    print(f"Gross P&L (before fees): Market ${market_gross:+.2f}, Limit ${limit_gross:+.2f}")

    # 수수료가 수익에 미치는 영향
    market_net = market_report.final_capital - market_report.initial_capital
    limit_net = limit_report.final_capital - limit_report.initial_capital
    print(f"Net P&L (after fees): Market ${market_net:+.2f}, Limit ${limit_net:+.2f}")

    print("\n" + "=" * 70)


def main():
    DATA_PATH = Path("./data/futures_ticks")

    if not DATA_PATH.exists():
        print(f"Error: Data path not found: {DATA_PATH}")
        return

    # 데이터 로더 (공유)
    loader = TickDataLoader(DATA_PATH)

    # 공통 전략 파라미터
    strategy_params = {
        "quantity": 0.01,
        "n_buckets": 50,
        "breakout_lookback": 20,
        "vpin_threshold": 0.4,
    }

    # 1. Market Order 버전
    market_strategy = VPINBreakoutStrategy(**strategy_params)
    market_report, market_runner = run_backtest(
        market_strategy, loader, "VPIN Breakout (Market Order)"
    )

    # 2. Limit Order 버전
    limit_strategy = VPINBreakoutLimitStrategy(
        **strategy_params,
        limit_offset_ratio=0.5,  # 스프레드의 50%
    )
    limit_report, limit_runner = run_backtest(
        limit_strategy, loader, "VPIN Breakout (Limit Order)"
    )

    # 비교 출력
    print_comparison(market_report, market_runner, limit_report, limit_runner)


if __name__ == "__main__":
    main()
