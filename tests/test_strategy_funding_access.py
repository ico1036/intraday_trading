"""
Test: Strategy can access FundingRateLoader directly

Validates that strategies can import and use FundingRateLoader in setup()
to make entry/exit decisions based on funding rate conditions.

This is the "workaround" pattern for strategies like [11] Funding Rate Filter
that need funding rate as a signal condition, not just for PnL settlement.
"""

from datetime import datetime, timezone

import pytest

from intraday.funding import FundingRate, FundingRateLoader
from intraday.strategies.base import MarketState, OrderType, Side, StrategyBase


class FundingFilterStrategy(StrategyBase):
    """
    Example strategy that uses FundingRateLoader directly.

    Entry condition:
    - Skip long if funding rate > 0.05% (expensive to hold longs)
    - Skip short if funding rate < -0.05% (expensive to hold shorts)
    """

    def setup(self) -> None:
        # Load funding data directly in strategy
        self.funding_loader: FundingRateLoader | None = self.params.get("funding_loader")
        self.buy_threshold = self.params.get("buy_threshold", 0.3)
        self.sell_threshold = self.params.get("sell_threshold", -0.3)
        self.max_funding_for_long = self.params.get("max_funding_for_long", 0.0005)  # 0.05%
        self.min_funding_for_short = self.params.get("min_funding_for_short", -0.0005)

    def _get_current_funding(self, state: MarketState) -> float | None:
        """Get funding rate at current timestamp."""
        if self.funding_loader is None:
            return None
        rate = self.funding_loader.get_latest_rate_before(state.timestamp)
        return rate.funding_rate if rate else None

    def should_buy(self, state: MarketState) -> bool:
        # Check funding rate first
        funding = self._get_current_funding(state)
        if funding is not None and funding > self.max_funding_for_long:
            return False  # Too expensive to hold long

        return state.imbalance > self.buy_threshold

    def should_sell(self, state: MarketState) -> bool:
        # For exit, we don't filter by funding (want to exit regardless)
        return state.imbalance < self.sell_threshold

    def get_order_type(self) -> OrderType:
        return OrderType.MARKET


def make_market_state(
    imbalance: float = 0.0,
    timestamp: datetime | None = None,
    **kwargs,
) -> MarketState:
    """Create MarketState with sensible defaults."""
    if timestamp is None:
        timestamp = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

    defaults = {
        "timestamp": timestamp,
        "mid_price": 50000.0,
        "imbalance": imbalance,
        "spread": 1.0,
        "spread_bps": 0.02,
        "best_bid": 49999.5,
        "best_ask": 50000.5,
        "best_bid_qty": 10.0,
        "best_ask_qty": 10.0,
        "position_side": None,
        "position_qty": 0.0,
    }
    defaults.update(kwargs)
    return MarketState(**defaults)


def make_funding_loader(rates: list[tuple[datetime, float]]) -> FundingRateLoader:
    """Create FundingRateLoader from simple (timestamp, rate) tuples."""
    funding_rates = [
        FundingRate(
            timestamp=ts,
            symbol="BTCUSDT",
            funding_rate=rate,
            mark_price=50000.0,
        )
        for ts, rate in rates
    ]
    return FundingRateLoader.from_list(funding_rates)


class TestStrategyFundingAccess:
    """Test that strategies can access funding data directly."""

    def test_strategy_can_import_funding_loader(self):
        """Verify FundingRateLoader can be imported in strategy."""
        # This import should work
        from intraday.funding import FundingRateLoader
        assert FundingRateLoader is not None

    def test_strategy_receives_funding_loader_via_params(self):
        """Strategy can receive FundingRateLoader through params."""
        funding_loader = make_funding_loader([
            (datetime(2024, 1, 15, 8, 0, tzinfo=timezone.utc), 0.0001),
        ])

        strategy = FundingFilterStrategy(
            quantity=0.01,
            funding_loader=funding_loader,
        )

        assert strategy.funding_loader is funding_loader
        assert len(strategy.funding_loader) == 1

    def test_strategy_buys_when_funding_low(self):
        """Strategy should buy when imbalance high AND funding rate acceptable."""
        funding_loader = make_funding_loader([
            (datetime(2024, 1, 15, 8, 0, tzinfo=timezone.utc), 0.0001),  # 0.01% - low
        ])

        strategy = FundingFilterStrategy(
            quantity=0.01,
            funding_loader=funding_loader,
            buy_threshold=0.3,
            max_funding_for_long=0.0005,  # 0.05% max
        )

        state = make_market_state(
            imbalance=0.5,  # Above buy threshold
            timestamp=datetime(2024, 1, 15, 12, 0, tzinfo=timezone.utc),
        )

        assert strategy.should_buy(state) is True

    def test_strategy_skips_buy_when_funding_high(self):
        """Strategy should NOT buy when funding rate too high (expensive for longs)."""
        funding_loader = make_funding_loader([
            (datetime(2024, 1, 15, 8, 0, tzinfo=timezone.utc), 0.001),  # 0.1% - high!
        ])

        strategy = FundingFilterStrategy(
            quantity=0.01,
            funding_loader=funding_loader,
            buy_threshold=0.3,
            max_funding_for_long=0.0005,  # 0.05% max
        )

        state = make_market_state(
            imbalance=0.5,  # Above buy threshold
            timestamp=datetime(2024, 1, 15, 12, 0, tzinfo=timezone.utc),
        )

        # Should skip buy because funding too high
        assert strategy.should_buy(state) is False

    def test_strategy_uses_latest_funding_before_timestamp(self):
        """Strategy should use the most recent funding rate before current time."""
        funding_loader = make_funding_loader([
            (datetime(2024, 1, 15, 0, 0, tzinfo=timezone.utc), 0.0001),   # Old: low
            (datetime(2024, 1, 15, 8, 0, tzinfo=timezone.utc), 0.001),    # Recent: high
        ])

        strategy = FundingFilterStrategy(
            quantity=0.01,
            funding_loader=funding_loader,
            max_funding_for_long=0.0005,
        )

        # At 12:00, should use 08:00 rate (0.001 - high)
        state = make_market_state(
            imbalance=0.5,
            timestamp=datetime(2024, 1, 15, 12, 0, tzinfo=timezone.utc),
        )
        assert strategy.should_buy(state) is False

        # At 04:00, should use 00:00 rate (0.0001 - low)
        state_early = make_market_state(
            imbalance=0.5,
            timestamp=datetime(2024, 1, 15, 4, 0, tzinfo=timezone.utc),
        )
        assert strategy.should_buy(state_early) is True

    def test_strategy_works_without_funding_loader(self):
        """Strategy should work even if funding_loader not provided."""
        strategy = FundingFilterStrategy(
            quantity=0.01,
            buy_threshold=0.3,
            # No funding_loader provided
        )

        state = make_market_state(imbalance=0.5)

        # Should still buy based on imbalance alone
        assert strategy.should_buy(state) is True

    def test_negative_funding_allows_longs(self):
        """Negative funding rate means longs get paid - always allow."""
        funding_loader = make_funding_loader([
            (datetime(2024, 1, 15, 8, 0, tzinfo=timezone.utc), -0.001),  # -0.1% negative
        ])

        strategy = FundingFilterStrategy(
            quantity=0.01,
            funding_loader=funding_loader,
            buy_threshold=0.3,
            max_funding_for_long=0.0005,  # Negative is always < max
        )

        state = make_market_state(
            imbalance=0.5,
            timestamp=datetime(2024, 1, 15, 12, 0, tzinfo=timezone.utc),
        )

        # Negative funding means longs receive payment - should buy
        assert strategy.should_buy(state) is True


class TestFundingLoaderIntegration:
    """Integration tests for FundingRateLoader usage patterns."""

    def test_create_loader_from_list(self):
        """FundingRateLoader.from_list() factory method works."""
        rates = [
            FundingRate(
                timestamp=datetime(2024, 1, 15, 8, 0, tzinfo=timezone.utc),
                symbol="BTCUSDT",
                funding_rate=0.0001,
                mark_price=50000.0,
            ),
        ]

        loader = FundingRateLoader.from_list(rates)

        assert len(loader) == 1

    def test_get_latest_rate_before(self):
        """get_latest_rate_before returns correct rate."""
        rates = [
            FundingRate(
                timestamp=datetime(2024, 1, 15, 0, 0, tzinfo=timezone.utc),
                symbol="BTCUSDT",
                funding_rate=0.0001,
                mark_price=50000.0,
            ),
            FundingRate(
                timestamp=datetime(2024, 1, 15, 8, 0, tzinfo=timezone.utc),
                symbol="BTCUSDT",
                funding_rate=0.0002,
                mark_price=50000.0,
            ),
        ]

        loader = FundingRateLoader.from_list(rates)

        # Before first rate
        rate = loader.get_latest_rate_before(
            datetime(2024, 1, 14, 23, 0, tzinfo=timezone.utc)
        )
        assert rate is None

        # Between rates
        rate = loader.get_latest_rate_before(
            datetime(2024, 1, 15, 4, 0, tzinfo=timezone.utc)
        )
        assert rate is not None
        assert rate.funding_rate == 0.0001

        # After second rate
        rate = loader.get_latest_rate_before(
            datetime(2024, 1, 15, 12, 0, tzinfo=timezone.utc)
        )
        assert rate is not None
        assert rate.funding_rate == 0.0002

    def test_iter_rates(self):
        """iter_rates allows iterating over funding history."""
        rates = [
            FundingRate(
                timestamp=datetime(2024, 1, 15, 0, 0, tzinfo=timezone.utc),
                symbol="BTCUSDT",
                funding_rate=0.0001,
                mark_price=50000.0,
            ),
            FundingRate(
                timestamp=datetime(2024, 1, 15, 8, 0, tzinfo=timezone.utc),
                symbol="BTCUSDT",
                funding_rate=0.0002,
                mark_price=50000.0,
            ),
            FundingRate(
                timestamp=datetime(2024, 1, 15, 16, 0, tzinfo=timezone.utc),
                symbol="BTCUSDT",
                funding_rate=0.0003,
                mark_price=50000.0,
            ),
        ]

        loader = FundingRateLoader.from_list(rates)

        # Iterate with time range
        result = list(loader.iter_rates(
            start=datetime(2024, 1, 15, 4, 0, tzinfo=timezone.utc),
            end=datetime(2024, 1, 15, 12, 0, tzinfo=timezone.utc),
        ))

        assert len(result) == 1
        assert result[0].funding_rate == 0.0002
