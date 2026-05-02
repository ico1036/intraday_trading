"""
포트폴리오 전략 모듈

여러 코인을 동시에 분석하여 트레이딩하는 전략들
"""

from .momentum import PortfolioMomentum, CoinReturn, PortfolioMomentumStrategy
from .pair import PairTradingStrategy, SpreadCalculator
from .atr_volume_risk_momentum import ATRVolumeRiskMomentumStrategy
from .atr_volume_unit_risk import ATRVolumeUnitRiskMultiStrategy
from .atr_volume_unit_risk_v2 import ATRVolumeUnitRiskMultiStrategyV2
from .atr_volume_unit_risk_v3 import ATRVolumeUnitRiskMultiStrategyV3
from .atr_volume_unit_risk_v4 import ATRVolumeUnitRiskMultiStrategyV4
from .atr_volume_bar_multi import ATRVolumeBarMultiStrategy
from .turtle_dual_tf import TurtleDualTimeframeStrategy
from .turtle_daily_proxy import TurtleDailyProxyStrategy
from .adaptive_intraday_turtle import AdaptiveIntradayTurtleStrategy

__all__ = [
    "PortfolioMomentum",
    "PortfolioMomentumStrategy",
    "CoinReturn",
    "PairTradingStrategy",
    "SpreadCalculator",
    "ATRVolumeRiskMomentumStrategy",
    "ATRVolumeUnitRiskMultiStrategy",
    "ATRVolumeUnitRiskMultiStrategyV2",
    "ATRVolumeUnitRiskMultiStrategyV3",
    "ATRVolumeUnitRiskMultiStrategyV4",
    "ATRVolumeBarMultiStrategy",
    "TurtleDualTimeframeStrategy",
    "TurtleDailyProxyStrategy",
    "AdaptiveIntradayTurtleStrategy",
    "TurtleAtrUnitPortfolioStrategy",
    "AdaptivePairRiskRegimeStrategy",
    "TurtleAtrCorrelationCappedStrategy",
    "TurtleAtrLowTurnoverRegimeStrategy",
    "TurtleAtrExpectancyGateStrategy",
    "TurtleAtrMetaFilterStrategy",
    "TurtleAtrMetaFilterV2Strategy",
    "TurtleAtrStabilityFirstStrategy",
    "TurtleAtrISRobustStrategy",
    "TurtleAtrStageGateStrategy",
    "TurtleAtrWeakRegimeClampStrategy",
    "TurtleAtrISGateV2Strategy",
    "TurtleAtrISRecoveryStrategy",
    "TurtleAtrSingleBranchRecoveryStrategy",
    "RegimeSplitAtrBreakoutStrategy",
    "TurtleAtrArchitectureResetStrategy",
    "TurtleAtrImplementationAuditStrategy",
    "TurtleAtrNonlinearAlphaResetStrategy",
    "TurtleAtrStagnationBreakerStrategy",
    "TurtleAtrDualHorizonBreakStrategy",
    "TurtleAtrExecutionRegimeSwitchStrategy",
    "TurtleAtrWalkForwardRegimeStrategy",
    "TestStrategyPf11ShaStrategy",
    "TurtleAtrCorrelationCappedRegimeStrategy",
    "TurtleAtrCostSuppressedRegimeStrategy",
    "TurtleAtrDrawdownFirstStrategy",
    "TurtleAtrEdgeRecoveryStrategy",
    "TurtleAtrRiskParityCorrelationCappedStrategy",
    "TurtleAtrEdgeDensityStrategy",
    "TurtleAtrRegimeSwitchHurdleStrategy",
    "TurtleAtrIsGuardSelectiveParticipationStrategy",
    "TurtleAtrGuardInstrumentationStrategy",
    "TurtleAtrExecutionParityGatedStrategy",
    "TurtleAtrAssertionFirstStrategy",
    "TurtleAtrParityCertifiedStrategy",
    "TurtleAtrCertificationStopLossStrategy",
    "TurtleAtrFailClosedVerifiedStrategy",
    "TurtleAtrImplementationFirstStrategy",
    "TurtleAtrTwoStageValidationStrategy",
    "TurtleAtrCertificationHoldStrategy",
    "TurtleAtrResearchLockStrategy",
    "TurtleAtrCertificationFirstLockStrategy",
    "TurtleAtrExecutionRecoveryStrategy",
    "TurtleAtrValidationOnlyStrategy",
    "TurtleAtrVerificationGateStrategy",
    "TurtleAtrTddIntegrityGateStrategy",
    "TurtleAtrSingleGateRecoveryStrategy",
    "TurtleAtrDeveloperSpecLockStrategy",
    "AdaptiveTurtleATRUnitRiskPortfolio",
    "AdaptiveTurtleAtrUnitPortfolioStrategy",
    "AdaptiveTurtleAtrUnitPortfolioStrategyV2",
    "AdaptiveTurtleAtrUnitPortfolioStrategyV3",
    "TurtleATR Intraday",
]
from .turtle_atr_unit_portfolio_strategy import TurtleAtrUnitPortfolioStrategy
from .adaptive_pair_risk_regime_strategy import AdaptivePairRiskRegimeStrategy
from .regime_split_atr_breakout_strategy import RegimeSplitAtrBreakoutStrategy
from .adaptive_turtle_atr_unit_portfolio_strategy import AdaptiveTurtleAtrUnitPortfolioStrategy
from .adaptive_turtle_atr_unit_portfolio_strategy_v2 import AdaptiveTurtleAtrUnitPortfolioStrategyV2
from .adaptive_turtle_atr_unit_portfolio_strategy_v3 import AdaptiveTurtleAtrUnitPortfolioStrategyV3

# Compatibility aliases for generated Turtle-ATR experiment names.
#
# The agent workflow creates short-lived strategy variants while iterating.
# Several smoke tests import those generated names from this package, but the
# checked-in implementation surface is the shared portfolio scaffold below.
# Keep these names importable until each variant earns a real implementation.
AdaptiveTurtleATRUnitRiskPortfolio = AdaptiveTurtleAtrUnitPortfolioStrategy
TurtleAtrArchitectureResetStrategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrAssertionFirstStrategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrCertificationFirstLockStrategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrCertificationHoldStrategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrCertificationStopLossStrategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrCorrelationCappedRegimeStrategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrCorrelationCappedStrategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrCostSuppressedRegimeStrategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrDeveloperSpecLockStrategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrDrawdownFirstStrategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrDualHorizonBreakStrategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrEdgeDensityStrategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrEdgeRecoveryStrategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrExecutionParityGatedStrategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrExecutionRecoveryStrategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrExecutionRegimeSwitchStrategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrExpectancyGateStrategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrFailClosedVerifiedStrategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrGuardInstrumentationStrategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrImplementationAuditStrategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrImplementationFirstStrategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrISGateV2Strategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrISRecoveryStrategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrISRobustStrategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrIsGuardSelectiveParticipationStrategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrLowTurnoverRegimeStrategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrMetaFilterStrategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrMetaFilterV2Strategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrNonlinearAlphaResetStrategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrParityCertifiedStrategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrRegimeSwitchHurdleStrategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrResearchLockStrategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrRiskParityCorrelationCappedStrategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrSingleBranchRecoveryStrategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrSingleGateRecoveryStrategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrStabilityFirstStrategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrStageGateStrategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrStagnationBreakerStrategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrTddIntegrityGateStrategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrTwoStageValidationStrategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrValidationOnlyStrategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrVerificationGateStrategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrWalkForwardRegimeStrategy = TurtleAtrUnitPortfolioStrategy
TurtleAtrWeakRegimeClampStrategy = TurtleAtrUnitPortfolioStrategy
TestStrategyPf11ShaStrategy = TurtleAtrUnitPortfolioStrategy

TurtleAtrUnitPortfolioStrategy.__test__ = False
