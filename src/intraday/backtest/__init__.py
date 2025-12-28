"""
백테스트 모듈

히스토리컬 데이터를 사용하여 전략을 백테스트합니다.

교육 포인트:
    - OrderbookBacktestRunner: 오더북 기반 전략 백테스트 (OBI 등)
    - TickBacktestRunner: 틱 기반 전략 백테스트 (볼륨바, 틱바 지원)
    - 기존 Strategy, PaperTrader, PerformanceCalculator 재사용
"""

from .orderbook_runner import OrderbookBacktestRunner
from .tick_runner import TickBacktestRunner, BarType

__all__ = [
    "OrderbookBacktestRunner",
    "TickBacktestRunner",
    "BarType",
]





