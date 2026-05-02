"""
CrossSectionalMomentumStrategy 테스트
"""

import pytest
from datetime import datetime

from intraday.strategy import MarketState, Side, OrderType, PortfolioOrder
from intraday.strategies.multi.cross_momentum import CrossSectionalMomentumStrategy


def make_state(
    symbol: str = "BTCUSDT",
    panel: dict = None,
    positions: dict = None,
    close: float = 50000.0,
) -> MarketState:
    return MarketState(
        timestamp=datetime(2025, 3, 1),
        mid_price=close,
        imbalance=0.0,
        spread=0.0,
        spread_bps=0.0,
        best_bid=close,
        best_ask=close,
        best_bid_qty=1.0,
        best_ask_qty=1.0,
        position_side=None,
        position_qty=0.0,
        open=close,
        high=close * 1.001,
        low=close * 0.999,
        close=close,
        volume=100.0,
        vwap=close,
        symbol=symbol,
        panel=panel,
        positions=positions,
    )


class TestInit:
    def test_default_params(self):
        s = CrossSectionalMomentumStrategy(
            symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"],
        )
        assert s.lookback_bars == 24
        assert s.rebalance_bars == 24
        assert len(s.symbols) == 4

    def test_custom_params(self):
        s = CrossSectionalMomentumStrategy(
            symbols=["BTCUSDT", "ETHUSDT"],
            lookback_bars=12,
            rebalance_bars=6,
        )
        assert s.lookback_bars == 12
        assert s.rebalance_bars == 6


class TestNoSignalBeforeLookback:
    def test_returns_none_without_enough_history(self):
        """lookback 기간 전에는 주문 없음"""
        s = CrossSectionalMomentumStrategy(
            symbols=["BTCUSDT", "ETHUSDT"],
            lookback_bars=5,
            rebalance_bars=5,
        )

        panel = {
            "BTCUSDT": {"open": 50000, "high": 50100, "low": 49900, "close": 50050, "volume": 100, "vwap": 50025, "volume_imbalance": 0.1},
            "ETHUSDT": {"open": 3000, "high": 3010, "low": 2990, "close": 3005, "volume": 500, "vwap": 3002, "volume_imbalance": -0.1},
        }

        # 5번 미만 호출 → None
        for i in range(4):
            result = s.generate_order(make_state(panel=panel))
            assert result is None


class TestRebalancing:
    def test_generates_orders_at_rebalance(self):
        """리밸런싱 주기에 주문 생성"""
        s = CrossSectionalMomentumStrategy(
            symbols=["BTCUSDT", "ETHUSDT"],
            lookback_bars=3,
            rebalance_bars=3,
            quantity=0.01,
        )

        # BTC 상승, ETH 하락 (6번 호출하면 bar_count=6, 6%3==0, hist=4 → 리밸런싱)
        prices_btc = [50000, 50050, 50100, 50150, 50200, 50250]
        prices_eth = [3000, 2995, 2990, 2985, 2980, 2975]

        result = None
        for btc_p, eth_p in zip(prices_btc, prices_eth):
            panel = {
                "BTCUSDT": {"open": btc_p, "high": btc_p+10, "low": btc_p-10, "close": btc_p, "volume": 100, "vwap": btc_p, "volume_imbalance": 0.0},
                "ETHUSDT": {"open": eth_p, "high": eth_p+5, "low": eth_p-5, "close": eth_p, "volume": 500, "vwap": eth_p, "volume_imbalance": 0.0},
            }
            result = s.generate_order(make_state(panel=panel))

        # bar_count=6, 6%3==0, history=6 >= lookback+1=4 → 리밸런싱
        assert result is not None
        assert isinstance(result, PortfolioOrder)

    def test_long_strongest_short_weakest(self):
        """가장 강한 코인 LONG, 가장 약한 코인 SHORT"""
        s = CrossSectionalMomentumStrategy(
            symbols=["BTCUSDT", "ETHUSDT"],
            lookback_bars=3,
            rebalance_bars=3,
            quantity=0.01,
        )

        # BTC 꾸준히 상승, ETH 꾸준히 하락 (6번 호출)
        prices_btc = [50000, 50050, 50100, 50150, 50200, 50250]
        prices_eth = [3000, 2995, 2990, 2985, 2980, 2975]

        result = None
        for btc_p, eth_p in zip(prices_btc, prices_eth):
            panel = {
                "BTCUSDT": {"close": btc_p, "open": btc_p-50, "high": btc_p+10, "low": btc_p-10, "volume": 100, "vwap": btc_p, "volume_imbalance": 0},
                "ETHUSDT": {"close": eth_p, "open": eth_p+5, "high": eth_p+5, "low": eth_p-5, "volume": 500, "vwap": eth_p, "volume_imbalance": 0},
            }
            result = s.generate_order(make_state(panel=panel))

        assert result is not None
        # BTC 상승 → LONG
        btc_order = result["BTCUSDT"]
        assert btc_order is not None
        assert btc_order.side == Side.BUY

        # ETH 하락 → SHORT
        eth_order = result["ETHUSDT"]
        assert eth_order is not None
        assert eth_order.side == Side.SELL


class TestNoRebalanceWhenUnchanged:
    def test_no_order_when_positions_match(self):
        """이미 올바른 포지션이면 주문 없음"""
        s = CrossSectionalMomentumStrategy(
            symbols=["BTCUSDT", "ETHUSDT"],
            lookback_bars=3,
            rebalance_bars=3,
            quantity=0.01,
        )

        panels = [
            {"BTCUSDT": {"close": 50000, "open": 50000, "high": 50000, "low": 50000, "volume": 100, "vwap": 50000, "volume_imbalance": 0},
             "ETHUSDT": {"close": 3000, "open": 3000, "high": 3000, "low": 3000, "volume": 500, "vwap": 3000, "volume_imbalance": 0}},
            {"BTCUSDT": {"close": 50100, "open": 50000, "high": 50100, "low": 50000, "volume": 100, "vwap": 50050, "volume_imbalance": 0},
             "ETHUSDT": {"close": 2990, "open": 3000, "high": 3000, "low": 2990, "volume": 500, "vwap": 2995, "volume_imbalance": 0}},
            {"BTCUSDT": {"close": 50200, "open": 50100, "high": 50200, "low": 50100, "volume": 100, "vwap": 50150, "volume_imbalance": 0},
             "ETHUSDT": {"close": 2980, "open": 2990, "high": 2990, "low": 2980, "volume": 500, "vwap": 2985, "volume_imbalance": 0}},
        ]

        # 첫 리밸런싱까지 주문 생성
        for p in panels:
            s.generate_order(make_state(panel=p))

        # 이미 LONG BTC, SHORT ETH → 같은 방향 유지 시 주문 없음
        positions = {
            "BTCUSDT": {"side": "LONG", "qty": 0.01, "entry_price": 50000},
            "ETHUSDT": {"side": "SHORT", "qty": 0.01, "entry_price": 3000},
        }

        # 동일 추세 지속 (BTC 계속 상승, ETH 계속 하락)
        more_panels = [
            {"BTCUSDT": {"close": 50300, "open": 50200, "high": 50300, "low": 50200, "volume": 100, "vwap": 50250, "volume_imbalance": 0},
             "ETHUSDT": {"close": 2970, "open": 2980, "high": 2980, "low": 2970, "volume": 500, "vwap": 2975, "volume_imbalance": 0}},
            {"BTCUSDT": {"close": 50400, "open": 50300, "high": 50400, "low": 50300, "volume": 100, "vwap": 50350, "volume_imbalance": 0},
             "ETHUSDT": {"close": 2960, "open": 2970, "high": 2970, "low": 2960, "volume": 500, "vwap": 2965, "volume_imbalance": 0}},
            {"BTCUSDT": {"close": 50500, "open": 50400, "high": 50500, "low": 50400, "volume": 100, "vwap": 50450, "volume_imbalance": 0},
             "ETHUSDT": {"close": 2950, "open": 2960, "high": 2960, "low": 2950, "volume": 500, "vwap": 2955, "volume_imbalance": 0}},
        ]

        result = None
        for p in more_panels:
            result = s.generate_order(make_state(panel=p, positions=positions))

        # 같은 방향 유지 → 주문 없음 (None)
        assert result is None


class TestPanelNone:
    def test_returns_none_without_panel(self):
        """패널 데이터 없으면 None"""
        s = CrossSectionalMomentumStrategy(symbols=["BTCUSDT", "ETHUSDT"])
        result = s.generate_order(make_state(panel=None))
        assert result is None

    def test_returns_none_without_symbol(self):
        """symbol 없으면 None"""
        s = CrossSectionalMomentumStrategy(symbols=["BTCUSDT", "ETHUSDT"])
        state = make_state()
        state.symbol = None
        result = s.generate_order(state)
        assert result is None


class TestFourCoins:
    def test_only_top_and_bottom_get_orders(self):
        """4개 코인 중 1위와 꼴찌만 주문, 중간 2개는 없음"""
        s = CrossSectionalMomentumStrategy(
            symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"],
            lookback_bars=3,
            rebalance_bars=3,
            quantity=0.01,
        )

        # SOL 가장 강함, BTC 가장 약함, ETH/BNB 중간
        # 7개 패널 (lookback+1=4, 6번째에서 리밸런싱)
        def p(btc, eth, sol, bnb):
            return {
                "BTCUSDT": {"close": btc, "open": btc, "high": btc, "low": btc, "volume": 100, "vwap": btc, "volume_imbalance": 0},
                "ETHUSDT": {"close": eth, "open": eth, "high": eth, "low": eth, "volume": 500, "vwap": eth, "volume_imbalance": 0},
                "SOLUSDT": {"close": sol, "open": sol, "high": sol, "low": sol, "volume": 1000, "vwap": sol, "volume_imbalance": 0},
                "BNBUSDT": {"close": bnb, "open": bnb, "high": bnb, "low": bnb, "volume": 200, "vwap": bnb, "volume_imbalance": 0},
            }

        panels = [
            p(50000, 3000, 100, 600),     # base
            p(49900, 3002, 100.5, 600.5), # BTC down, others up
            p(49800, 3004, 101.0, 601.0),
            p(49700, 3006, 101.5, 601.5),
            p(49600, 3008, 102.0, 602.0),
            p(49500, 3010, 102.5, 602.5), # 6th call: BTC -1%, ETH +0.3%, SOL +2.5%, BNB +0.8%
        ]

        result = None
        for panel in panels:
            result = s.generate_order(make_state(panel=panel))

        assert result is not None
        assert isinstance(result, PortfolioOrder)

        # SOL 가장 강함 → LONG
        sol_order = result["SOLUSDT"]
        assert sol_order is not None
        assert sol_order.side == Side.BUY

        # BTC 가장 약함 → SHORT
        btc_order = result["BTCUSDT"]
        assert btc_order is not None
        assert btc_order.side == Side.SELL
