"""Intraday Trading Education - Binance Orderbook Analysis"""

__version__ = "0.1.0"

# Client
from .client import BinanceWebSocketClient, OrderbookSnapshot, AggTrade, BinanceCombinedClient

# Orderbook
from .orderbook import OrderbookProcessor, OrderbookState

# Metrics
from .metrics import MetricsCalculator, MetricsSnapshot

# Strategy
from .strategy import Side, OrderType, Order, MarketState, Strategy, OBIStrategy

# Paper Trading
from .paper_trader import Trade, Position, PaperTrader

# Performance
from .performance import PerformanceReport, PerformanceCalculator

# Runner
from .runner import ForwardRunner

__all__ = [
    # Client
    "BinanceWebSocketClient",
    "OrderbookSnapshot",
    "AggTrade",
    "BinanceCombinedClient",
    # Orderbook
    "OrderbookProcessor",
    "OrderbookState",
    # Metrics
    "MetricsCalculator",
    "MetricsSnapshot",
    # Strategy
    "Side",
    "OrderType",
    "Order",
    "MarketState",
    "Strategy",
    "OBIStrategy",
    # Paper Trading
    "Trade",
    "Position",
    "PaperTrader",
    # Performance
    "PerformanceReport",
    "PerformanceCalculator",
    # Runner
    "ForwardRunner",
]
