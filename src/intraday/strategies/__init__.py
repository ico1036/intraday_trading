"""
Strategies Module

=== 구조 ===
strategies/
├── base.py                 # 공통 베이스 클래스
├── orderbook/              # Orderbook 기반 전략 (OrderbookBacktestRunner용)
│   ├── _template.py        # Orderbook 전략 템플릿
│   └── obi.py              # OBI 전략
└── tick/                   # Tick 기반 전략 (TickBacktestRunner용)
    ├── _template.py        # Tick 전략 템플릿
    └── volume_imbalance.py # Volume Imbalance 전략

=== 새 전략 개발 ===
1. 데이터 소스 선택: orderbook/ 또는 tick/
2. 해당 디렉토리의 _template.py 복사
3. StrategyBase 상속하여 should_buy(), should_sell() 구현

=== 사용 예시 ===
# Orderbook 전략
from intraday.strategies.orderbook import OBIStrategy
runner = OrderbookBacktestRunner(strategy=OBIStrategy(), ...)

# Tick 전략
from intraday.strategies.tick import VolumeImbalanceStrategy
runner = TickBacktestRunner(strategy=VolumeImbalanceStrategy(), ...)
"""

# Base
from .base import StrategyBase, MarketState, Order, Side, OrderType

# Orderbook strategies
from .orderbook import OBIStrategy

# Tick strategies
from .tick import VolumeImbalanceStrategy

__all__ = [
    # Base
    "StrategyBase",
    "MarketState",
    "Order",
    "Side",
    "OrderType",
    # Orderbook strategies
    "OBIStrategy",
    # Tick strategies
    "VolumeImbalanceStrategy",
]
