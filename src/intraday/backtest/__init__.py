"""Backtest package.

The public backtest surface is the portfolio tick runner. Tick data remains
the input format, but strategy implementations live under `strategies/multi`.
"""

from .multi_tick_runner import PortfolioTickBacktestRunner, PortfolioTickResult

__all__ = [
    "PortfolioTickBacktestRunner",
    "PortfolioTickResult",
]
