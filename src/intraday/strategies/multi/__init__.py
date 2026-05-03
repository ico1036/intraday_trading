"""Portfolio alpha strategies.

The primary extension point is `_alpha_template.py`: copy it to a new module
and implement one `PortfolioOrder` target-weight alpha for either one symbol
or many symbols.
"""

from .atr_volume_risk_momentum import ATRVolumeRiskMomentumStrategy
from .momentum import CoinReturn, PortfolioMomentum, PortfolioMomentumStrategy
from .pair import PairTradingStrategy, SpreadCalculator

__all__ = [
    "ATRVolumeRiskMomentumStrategy",
    "CoinReturn",
    "PortfolioMomentum",
    "PortfolioMomentumStrategy",
    "PairTradingStrategy",
    "SpreadCalculator",
]
