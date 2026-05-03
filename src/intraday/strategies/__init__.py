"""Strategy package.

New strategies live under `intraday.strategies.multi`.

The name `multi` means portfolio-style strategy, not "must trade many
symbols": a one-symbol `symbols` list is the single-instrument case.
"""

from .multi import (
    ATRVolumeRiskMomentumStrategy,
    CoinReturn,
    PairTradingStrategy,
    PortfolioMomentum,
    PortfolioMomentumStrategy,
    SpreadCalculator,
)

__all__ = [
    "ATRVolumeRiskMomentumStrategy",
    "CoinReturn",
    "PairTradingStrategy",
    "PortfolioMomentum",
    "PortfolioMomentumStrategy",
    "SpreadCalculator",
]
