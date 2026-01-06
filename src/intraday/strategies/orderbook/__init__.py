"""
Orderbook-based Strategies

OrderbookBacktestRunner 또는 ForwardRunner와 함께 사용하세요.

사용 가능한 데이터:
    - OBI (Order Book Imbalance)
    - Spread
    - Best bid/ask 가격 및 수량
"""

from .obi import OBIStrategy

__all__ = ["OBIStrategy"]
