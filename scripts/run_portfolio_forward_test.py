#!/usr/bin/env python3
"""포트폴리오 Forward Test 실행 스크립트"""

import argparse
import asyncio
import json
import signal
from datetime import datetime
import sys
from pathlib import Path

# Add local src to import path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from intraday import CandleType
from intraday.strategies.multi import PortfolioMomentum, PairTradingStrategy, ATRVolumeRiskMomentumStrategy
from intraday.strategies.tick.vpin_top5_rebalance import VPINTop5RebalanceStrategy
from intraday.multi_forward_runner import PortfolioForwardRunner


def parse_candle_type(value: str) -> CandleType:
    mapping = {
        "time": CandleType.TIME,
        "volume": CandleType.VOLUME,
        "tick": CandleType.TICK,
        "dollar": CandleType.DOLLAR,
    }
    v = value.lower()
    if v not in mapping:
        raise ValueError(f"Unknown candle type: {value}")
    return mapping[v]


def parse_vpin_params(text: str | None) -> dict:
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid --strategy-params JSON: {exc}")


def default_run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Portfolio Forward Test")
    parser.add_argument(
        "--strategy",
        choices=["momentum", "pair", "vpin_top5", "atr_risk_momentum"],
        default="momentum",
        help="strategy (momentum, pair, vpin_top5, atr_risk_momentum)",
    )
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"])
    parser.add_argument("--coin-a", default="BTCUSDT", help="Pair Trading: coin A")
    parser.add_argument("--coin-b", default="ETHUSDT", help="Pair Trading: coin B")
    parser.add_argument("--candle-size", type=float, default=300, help="Candle size")
    parser.add_argument("--candle-type", default="time", help="Candle type: time/volume/tick/dollar")
    parser.add_argument("--lookback", type=int, default=60, help="Momentum lookback")
    parser.add_argument("--rebalance", type=int, default=60, help="Rebalance minutes")
    parser.add_argument("--capital", type=float, default=10000)
    parser.add_argument("--position-size", type=float, default=0.3)
    parser.add_argument("--duration", type=float, default=None, help="duration seconds")
    parser.add_argument("--top-n", type=int, default=1)
    parser.add_argument("--bottom-n", type=int, default=1)
    parser.add_argument("--entry-z", type=float, default=2.5)
    parser.add_argument("--exit-z", type=float, default=0.0)
    parser.add_argument("--fee-rate", type=float, default=0.002, help="Per-side fee")
    parser.add_argument(
        "--strategy-params",
        type=str,
        default=None,
        help='JSON for VPIN top5 params, ex: {"top_n":5,"rebalance_minutes":60,"vpin_lookback":24}',
    )
    parser.add_argument("--run-id", default=None, help="Run identifier for logs (default: timestamp)")
    parser.add_argument(
        "--status-interval",
        type=float,
        default=60,
        help="Status print interval (seconds)",
    )
    parser.add_argument(
        "--save-interval",
        type=float,
        default=None,
        help="Auto print status heartbeat interval (seconds)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="output/forward_runs",
        help="Directory to persist forward run files (parquet + csv)",
    )
    parser.add_argument(
        "--close-on-stop",
        action="store_true",
        help="Force close all open positions before finalizing",
    )
    return parser.parse_args()


def build_strategy(args: argparse.Namespace):
    if args.strategy == "momentum":
        max_side_n = max(1, len(args.symbols) - 1)
        top_n = min(args.top_n, max(1, len(args.symbols)))
        bottom_n = 0 if len(args.symbols) <= 1 else min(args.bottom_n, max_side_n)
        if args.top_n > len(args.symbols):
            top_n = len(args.symbols)
        return PortfolioMomentum(
            symbols=args.symbols,
            lookback_minutes=args.lookback,
            top_n=top_n,
            bottom_n=bottom_n,
        )
    if args.strategy == "pair":
        return PairTradingStrategy(
            coin_a=args.coin_a,
            coin_b=args.coin_b,
            zscore_entry=args.entry_z,
            zscore_exit=args.exit_z,
            lookback=args.lookback,
        )

    if args.strategy == "atr_risk_momentum":
        return ATRVolumeRiskMomentumStrategy(
            symbols=[s.upper() for s in args.symbols],
            lookback_minutes=args.lookback,
            top_n=args.top_n,
            bottom_n=args.bottom_n,
        )

    vpin_params = parse_vpin_params(args.strategy_params)
    defaults = {
        "top_n": args.top_n,
        "rebalance_minutes": args.rebalance,
        "vpin_lookback": 24,
    }
    defaults.update(vpin_params)
    return VPINTop5RebalanceStrategy(**defaults)


def runner_symbols(args: argparse.Namespace) -> list[str]:
    if args.strategy == "pair":
        return [args.coin_a, args.coin_b]
    return [s.upper() for s in args.symbols]


def summarize_status(runner: PortfolioForwardRunner, init_capital: float) -> str:
    status = runner.get_status()
    ret = (status["equity"] - init_capital) / init_capital * 100 if init_capital else 0
    return (
        f"\n\n{'=' * 60}\n"
        f"📊 Final Result\n"
        f"{'=' * 60}\n"
        f"Run ID:       {status['run_id']}\n"
        f"Capital:      ${status['capital']:,.2f}\n"
        f"Unrealized:   ${status['unrealized_pnl']:,.2f}\n"
        f"Equity:       ${status['equity']:,.2f}\n"
        f"Return:       {ret:+.2f}%\n"
        f"Trades(total): {status['trades']}\n"
        f"Trades(realized): {status['trades_with_pnl']}\n"
        f"Positions:    {status['positions']}\n"
        f"{'=' * 60}\n"
    )


def main() -> None:
    args = parse_args()

    candle_type = parse_candle_type(args.candle_type)
    strategy = build_strategy(args)
    symbols = runner_symbols(args)

    runner = PortfolioForwardRunner(
        strategy=strategy,
        symbols=symbols,
        candle_type=candle_type,
        candle_size=args.candle_size,
        initial_capital=args.capital,
        position_size_pct=args.position_size,
        fee_rate=args.fee_rate,
        rebalance_minutes=args.rebalance,
        status_print_interval=args.status_interval,
        run_id=args.run_id or default_run_id(),
        close_on_stop=args.close_on_stop,
        auto_save_interval_seconds=args.save_interval,
    )

    stop_requested = False

    def handle_sigterm(signum, frame):
        nonlocal stop_requested
        stop_requested = True
        # asyncio loop not yet running in this branch? handled by KeyboardInterrupt fallback
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, handle_sigterm)

    try:
        asyncio.run(runner.run(duration_seconds=args.duration))
    except KeyboardInterrupt:
        stop_requested = True
        print("\n[Interrupted by user]")
    except Exception as exc:
        print(f"[ERROR] Forward run failed: {exc}")
        raise

    status = runner.get_status()
    print(summarize_status(runner, args.capital))

    out_dir = Path(args.output_dir)
    try:
        saved = runner.save_report(out_dir)
    except Exception as exc:  # pragma: no cover - persistence failure should not break run
        print(f"[warn] failed to save report: {exc}")
    else:
        print(f"[saved] summary: {saved['state']}")
        print(f"[saved] events:  {saved['events']}")
        print(f"[saved] weights: {saved['weights']}")
        print(f"[saved] nav:     {saved['portfolio']}")
        print(f"[saved] csv:     {saved['summary_csv']}")

    if stop_requested:
        print("[notice] stopped by user (or signal).")


if __name__ == "__main__":
    main()
