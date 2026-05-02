"""
Diagnostic test for VWAP calculation in VolumeImbalanceMomentumStrategy.

Purpose: Verify that:
1. state.vwap is not None
2. state.vwap does not always equal state.close (deviation = 0%)
3. ATR/BB filters are working correctly
4. Deviation calculation is correct
"""

import pytest
from datetime import datetime
from intraday.strategies.tick.volume_imbalance_momentum import VolumeImbalanceMomentumStrategy
from intraday.strategy import MarketState, Side, OrderType


def make_market_state(
    close: float = 50000.0,
    vwap: float | None = 50000.0,
    high: float | None = None,
    low: float | None = None,
    **overrides
) -> MarketState:
    """Create MarketState with sensible defaults for testing."""
    defaults = {
        "timestamp": datetime.now(),
        "mid_price": close,
        "imbalance": 0.0,
        "spread": 0.0,
        "spread_bps": 0.0,
        "best_bid": close,
        "best_ask": close,
        "best_bid_qty": 10.0,
        "best_ask_qty": 10.0,
        "position_side": None,
        "position_qty": 0.0,
        "open": close,
        "high": high if high is not None else close,
        "low": low if low is not None else close,
        "close": close,
        "volume": 1.0,
        "vwap": vwap,
    }
    defaults.update(overrides)
    return MarketState(**defaults)


class TestVWAPDiagnostic:
    """Diagnostic tests for VWAP calculation issues."""

    def test_vwap_none_detection(self):
        """Test 1: Detect if VWAP is None (calculation broken)."""
        strategy = VolumeImbalanceMomentumStrategy(
            quantity=0.01,
            vwap_deviation_entry=1.2,
            warmup_bars=1,  # Minimal warmup for testing
        )

        # Create state with VWAP = None
        state = make_market_state(close=50000.0, vwap=None)

        # Warm up strategy
        for _ in range(30):
            strategy.generate_order(state)

        # should_buy should return False if VWAP is None
        result = strategy.should_buy(state)
        assert result is False, "should_buy must return False when VWAP is None"

    def test_vwap_equals_close_detection(self):
        """Test 2: Detect if VWAP always equals close (deviation = 0%)."""
        strategy = VolumeImbalanceMomentumStrategy(
            quantity=0.01,
            vwap_deviation_entry=1.2,
            warmup_bars=1,
        )

        # Create state with VWAP = close (deviation = 0%)
        state = make_market_state(close=50000.0, vwap=50000.0, high=50100.0, low=49900.0)

        # Warm up strategy (30 bars for ATR/BB calculation)
        for _ in range(30):
            strategy.generate_order(state)

        # should_buy should return False if deviation = 0%
        result = strategy.should_buy(state)
        assert result is False, "should_buy must return False when VWAP = close (deviation = 0%)"

    def test_vwap_below_threshold(self):
        """Test 3: Verify entry logic when price below VWAP but within threshold."""
        strategy = VolumeImbalanceMomentumStrategy(
            quantity=0.01,
            vwap_deviation_entry=1.2,  # 1.2% threshold
            atr_threshold=999.0,  # Disable ATR filter
            bb_width_threshold=999.0,  # Disable BB filter
            warmup_bars=1,
        )

        # Create state: close = 49900, vwap = 50000
        # Deviation = (50000 - 49900) / 50000 * 100 = 0.2% (BELOW threshold)
        state = make_market_state(close=49900.0, vwap=50000.0, high=50100.0, low=49900.0)

        # Warm up strategy
        for _ in range(30):
            strategy.generate_order(state)

        # should_buy should return False (deviation < 1.2%)
        result = strategy.should_buy(state)
        assert result is False, "should_buy must return False when deviation < 1.2%"

    def test_vwap_above_threshold(self):
        """Test 4: Verify entry logic when price below VWAP and above threshold."""
        strategy = VolumeImbalanceMomentumStrategy(
            quantity=0.01,
            vwap_deviation_entry=1.2,  # 1.2% threshold
            atr_threshold=999.0,  # Disable ATR filter
            bb_width_threshold=999.0,  # Disable BB filter
            warmup_bars=1,
        )

        # Create state: close = 49400, vwap = 50000
        # Deviation = (50000 - 49400) / 50000 * 100 = 1.2% (AT threshold)
        state = make_market_state(close=49400.0, vwap=50000.0, high=50100.0, low=49400.0)

        # Warm up strategy
        for _ in range(30):
            strategy.generate_order(state)

        # should_buy should return False (deviation <= 1.2%, not >)
        result = strategy.should_buy(state)
        assert result is False, "should_buy must return False when deviation = 1.2% (not >)"

    def test_vwap_significantly_above_threshold(self):
        """Test 5: Verify entry logic when price significantly below VWAP."""
        strategy = VolumeImbalanceMomentumStrategy(
            quantity=0.01,
            vwap_deviation_entry=1.2,  # 1.2% threshold
            atr_threshold=999.0,  # Disable ATR filter
            bb_width_threshold=999.0,  # Disable BB filter
            warmup_bars=1,
        )

        # Create state: close = 49300, vwap = 50000
        # Deviation = (50000 - 49300) / 50000 * 100 = 1.4% (ABOVE threshold)
        state = make_market_state(close=49300.0, vwap=50000.0, high=50100.0, low=49300.0)

        # Warm up strategy (need full lookback for ATR/BB, but filters disabled)
        for _ in range(30):
            strategy.generate_order(state)

        # should_buy should return TRUE (deviation > 1.2%, filters disabled)
        result = strategy.should_buy(state)
        assert result is True, "should_buy must return True when deviation > 1.2% and filters disabled"

    def test_regime_filter_blocks_entry(self):
        """Test 6: Verify regime filters block entry when violated."""
        strategy = VolumeImbalanceMomentumStrategy(
            quantity=0.01,
            vwap_deviation_entry=1.2,
            atr_threshold=2.5,  # Enable ATR filter
            bb_width_threshold=5.0,  # Enable BB filter
            warmup_bars=1,
        )

        # Create state with HIGH volatility (to trigger ATR filter)
        # Use large high-low range to create high ATR
        state = make_market_state(close=49300.0, vwap=50000.0, high=52000.0, low=48000.0)

        # Warm up strategy with volatile bars (ATR will be > 2.5%)
        for _ in range(30):
            volatile_state = make_market_state(close=50000.0, vwap=50000.0, high=52000.0, low=48000.0)
            strategy.generate_order(volatile_state)

        # Now test entry with deviation > 1.2%
        state = make_market_state(close=49300.0, vwap=50000.0, high=52000.0, low=48000.0)
        result = strategy.should_buy(state)

        # should_buy should return False (ATR filter blocks entry)
        # ATR% = (52000 - 48000) / 50000 * 100 = 8% > 2.5%
        assert result is False, "should_buy must return False when ATR > 2.5%"

    def test_deviation_calculation_formula(self):
        """Test 7: Verify VWAP deviation formula is correct."""
        strategy = VolumeImbalanceMomentumStrategy(
            quantity=0.01,
            vwap_deviation_entry=1.2,
            atr_threshold=999.0,
            bb_width_threshold=999.0,
            warmup_bars=1,
        )

        # Test case 1: Price below VWAP
        # close = 49400, vwap = 50000
        # Expected deviation = (50000 - 49400) / 50000 * 100 = 1.2%
        state1 = make_market_state(close=49400.0, vwap=50000.0, high=50100.0, low=49400.0)
        for _ in range(30):
            strategy.generate_order(state1)

        # Deviation = 1.2%, threshold = 1.2%, so deviation <= threshold → False
        assert strategy.should_buy(state1) is False

        # Test case 2: Price significantly below VWAP
        # close = 49300, vwap = 50000
        # Expected deviation = (50000 - 49300) / 50000 * 100 = 1.4%
        state2 = make_market_state(close=49300.0, vwap=50000.0, high=50100.0, low=49300.0)
        strategy.generate_order(state2)  # Update state

        # Deviation = 1.4% > threshold = 1.2% → True
        assert strategy.should_buy(state2) is True

    def test_order_type_is_limit(self):
        """Test 8: Verify strategy uses LIMIT orders."""
        strategy = VolumeImbalanceMomentumStrategy(quantity=0.01)
        assert strategy.get_order_type() == OrderType.LIMIT, "Strategy must use LIMIT orders"

    def test_limit_price_uses_close(self):
        """Test 9: Verify limit price uses close (as specified in algorithm)."""
        strategy = VolumeImbalanceMomentumStrategy(quantity=0.01)
        state = make_market_state(close=49300.0, vwap=50000.0)

        limit_price = strategy.get_limit_price(state, Side.BUY)
        assert limit_price == 49300.0, f"Limit price should use close (49300), got {limit_price}"


class TestVWAPRealWorldSimulation:
    """Simulate real-world VWAP scenarios to detect issues."""

    def test_simulate_ranging_market_with_vwap_deviations(self):
        """Test 10: Simulate 100 bars of ranging market with VWAP deviations."""
        strategy = VolumeImbalanceMomentumStrategy(
            quantity=0.01,
            vwap_deviation_entry=1.2,
            atr_threshold=2.5,
            bb_width_threshold=5.0,
            warmup_bars=30,
        )

        # Simulate 100 bars with realistic VWAP deviations
        # Base price: 50000, VWAP oscillates around it
        base_price = 50000.0
        trade_count = 0

        for i in range(100):
            # Simulate price oscillating around VWAP
            # Every 10 bars, create a deviation > 1.2%
            if i % 10 == 0 and i >= 30:
                # Price below VWAP by 1.5%
                close = base_price * 0.985
                vwap = base_price
            elif i % 10 == 5 and i >= 30:
                # Price above VWAP by 1.5%
                close = base_price * 1.015
                vwap = base_price
            else:
                # Normal ranging (deviation < 1.2%)
                close = base_price + (i % 5 - 2) * 100  # +/- 200 range
                vwap = base_price

            # Create state with small volatility (ATR < 2.5%)
            state = make_market_state(
                close=close,
                vwap=vwap,
                high=close + 50,
                low=close - 50,
            )

            order = strategy.generate_order(state)
            if order is not None:
                trade_count += 1

        # Expected: ~14 trades (7 deviations * 2 directions)
        # But if VWAP is broken, trade_count = 0
        print(f"\n[DIAGNOSTIC] Simulated 100 bars, generated {trade_count} trades")
        print(f"[DIAGNOSTIC] Expected: ~10-20 trades (if VWAP working)")
        print(f"[DIAGNOSTIC] If 0 trades: VWAP calculation is BROKEN")

        # Assert we got at least SOME trades
        # If this fails, VWAP calculation is broken
        assert trade_count > 0, (
            f"Expected >0 trades in ranging market simulation, got {trade_count}. "
            f"This indicates VWAP calculation is broken or filters are too strict."
        )


def test_vwap_none_early_detection():
    """Critical test: Detect VWAP=None immediately (first bar)."""
    strategy = VolumeImbalanceMomentumStrategy(quantity=0.01, warmup_bars=1)
    state = make_market_state(close=50000.0, vwap=None)

    # First bar should handle None gracefully
    order = strategy.generate_order(state)
    assert order is None, "Strategy should handle VWAP=None without crashing"


def test_vwap_zero_detection():
    """Critical test: Detect VWAP=0 (invalid)."""
    strategy = VolumeImbalanceMomentumStrategy(quantity=0.01, warmup_bars=1)
    state = make_market_state(close=50000.0, vwap=0.0)

    # Warm up
    for _ in range(30):
        strategy.generate_order(state)

    # should_buy should return False (avoid division by zero)
    assert strategy.should_buy(state) is False, "Strategy must handle VWAP=0 gracefully"


if __name__ == "__main__":
    # Run diagnostic tests with verbose output
    pytest.main([__file__, "-v", "-s"])
