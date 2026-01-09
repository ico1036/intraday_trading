#!/usr/bin/env python3
"""
Tick 기반 Forward Test 실행 스크립트

실시간 aggTrade 데이터로 틱/캔들 기반 전략을 테스트합니다.

사용법:
    # BB Squeeze 전략 (4분봉)
    python scripts/run_tick_forward_test.py --strategy bb_squeeze --duration 3600

    # VPIN 전략 (100 BTC 볼륨바)
    python scripts/run_tick_forward_test.py --strategy vpin --candle-type volume --candle-size 100

    # 사용 가능한 전략 목록
    python scripts/run_tick_forward_test.py --list-strategies
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from intraday import TickForwardRunner, CandleType


# 사용 가능한 전략들
STRATEGIES = {
    "bb_squeeze": {
        "module": "intraday.strategies.tick.bb_squeeze",
        "class": "BBSqueezeStrategy",
        "default_candle_type": "time",
        "default_candle_size": 240,  # 4분봉
        "default_params": {
            "quantity": 0.01,
            "bb_period": 20,
            "bb_std_mult": 2.0,
            "squeeze_percentile": 10,
            "take_profit_pct": 0.6,
            "stop_loss_pct": 0.3,
            "use_long": True,
            "use_short": False,
        },
        "description": "Bollinger Band Squeeze Breakout (4분봉)",
    },
    "vpin": {
        "module": "intraday.strategies.tick.vpin_breakout",
        "class": "VPINBreakoutStrategy",
        "default_candle_type": "volume",
        "default_candle_size": 100,  # 100 BTC
        "default_params": {"quantity": 0.01},
        "description": "VPIN Breakout (볼륨바)",
    },
    "volume_imbalance": {
        "module": "intraday.strategy_volume",
        "class": "VolumeImbalanceStrategy",
        "default_candle_type": "volume",
        "default_candle_size": 10,  # 10 BTC
        "default_params": {"quantity": 0.01},
        "description": "Volume Imbalance (볼륨바)",
    },
    "ofi_vpin": {
        "module": "intraday.strategies.tick.ofi_vpin_explosion",
        "class": "OfiVpinExplosionStrategy",
        "default_candle_type": "volume",
        "default_candle_size": 200,  # 200 BTC
        "default_params": {"quantity": 0.01},
        "description": "OFI + VPIN Explosion (볼륨바)",
    },
}


def list_strategies():
    """사용 가능한 전략 목록 출력"""
    print("\n사용 가능한 전략:")
    print("=" * 60)
    for name, config in STRATEGIES.items():
        print(f"  {name:<20} - {config['description']}")
        print(f"                       Candle: {config['default_candle_type']} ({config['default_candle_size']})")
    print("=" * 60)
    print("\n예시:")
    print("  python scripts/run_tick_forward_test.py --strategy bb_squeeze --duration 300")
    print()


def load_strategy(name: str, params: dict = None):
    """전략 동적 로드"""
    if name not in STRATEGIES:
        print(f"Error: Unknown strategy '{name}'")
        list_strategies()
        sys.exit(1)

    config = STRATEGIES[name]
    module_name = config["module"]
    class_name = config["class"]

    # 동적 import
    import importlib
    module = importlib.import_module(module_name)
    strategy_class = getattr(module, class_name)

    # 파라미터 병합
    final_params = config["default_params"].copy()
    if params:
        final_params.update(params)

    return strategy_class(**final_params)


def parse_candle_type(value: str) -> CandleType:
    """캔들 타입 파싱"""
    mapping = {
        "time": CandleType.TIME,
        "volume": CandleType.VOLUME,
        "tick": CandleType.TICK,
        "dollar": CandleType.DOLLAR,
    }
    if value.lower() not in mapping:
        raise ValueError(f"Unknown candle type: {value}")
    return mapping[value.lower()]


async def main():
    parser = argparse.ArgumentParser(description="Run Tick Forward Test")
    parser.add_argument("--strategy", "-s", default="bb_squeeze", help="Strategy name (default: bb_squeeze)")
    parser.add_argument("--list-strategies", "-l", action="store_true", help="List available strategies")
    parser.add_argument("--symbol", default="btcusdt", help="Trading symbol (default: btcusdt)")
    parser.add_argument("--capital", type=float, default=10000, help="Initial capital (default: 10000)")
    parser.add_argument("--fee-rate", type=float, default=0.001, help="Fee rate (default: 0.001)")
    parser.add_argument("--leverage", type=int, default=1, help="Leverage (default: 1)")
    parser.add_argument("--candle-type", default=None, help="Candle type: time, volume, tick, dollar")
    parser.add_argument("--candle-size", type=float, default=None, help="Candle size")
    parser.add_argument("--quantity", type=float, default=None, help="Trade quantity")
    parser.add_argument("--duration", type=float, default=None, help="Test duration in seconds")

    args = parser.parse_args()

    # 전략 목록 출력
    if args.list_strategies:
        list_strategies()
        return

    # 전략 로드
    strategy_config = STRATEGIES.get(args.strategy, {})
    params = {}
    if args.quantity:
        params["quantity"] = args.quantity

    strategy = load_strategy(args.strategy, params)

    # 캔들 설정 (전략 기본값 또는 CLI 인자)
    candle_type_str = args.candle_type or strategy_config.get("default_candle_type", "time")
    candle_type = parse_candle_type(candle_type_str)
    candle_size = args.candle_size or strategy_config.get("default_candle_size", 60)

    # 러너 생성
    runner = TickForwardRunner(
        strategy=strategy,
        symbol=args.symbol,
        candle_type=candle_type,
        candle_size=candle_size,
        initial_capital=args.capital,
        fee_rate=args.fee_rate,
        leverage=args.leverage,
    )

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
