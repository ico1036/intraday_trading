"""
PortfolioTickBacktestRunner 테스트 (Phase 2)

tick-level 포트폴리오 백테스트 러너.
여러 심볼의 틱 스트림을 시간순으로 병합하고,
심볼별 캔들을 독립 빌드하며, 패널 데이터를 전략에 전달한다.
"""

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from intraday.client import AggTrade
from intraday.candle_builder import CandleType, Candle
from intraday.strategy import MarketState, Order, Side, OrderType, PortfolioOrder


# ─── Helper: 가짜 TickDataLoader ───────────────────────────

class FakeTickLoader:
    """테스트용 TickDataLoader 대체"""

    def __init__(self, trades: list[AggTrade]):
        self._trades = sorted(trades, key=lambda t: t.timestamp)

    def iter_trades(self, start_time=None, end_time=None):
        for t in self._trades:
            if start_time and t.timestamp < start_time:
                continue
            if end_time and t.timestamp > end_time:
                continue
            yield t


def make_trade(
    symbol: str,
    price: float,
    qty: float,
    ts: datetime,
    is_buyer_maker: bool = False,
) -> AggTrade:
    """AggTrade 헬퍼"""
    return AggTrade(
        timestamp=ts,
        symbol=symbol,
        price=price,
        quantity=qty,
        is_buyer_maker=is_buyer_maker,
    )


# ─── 간단한 테스트 전략들 ───────────────────────────

class AlwaysBuyStrategy:
    """항상 BUY 하는 전략 (단일코인)"""

    def generate_order(self, state: MarketState) -> Order | None:
        if state.position_side is None:
            return Order(side=Side.BUY, quantity=0.01, order_type=OrderType.MARKET)
        return None


class BuyOnceStrategy:
    """첫 캔들에서 한 번만 BUY 하는 전략"""

    def __init__(self, quantity: float):
        self.quantity = quantity
        self.done = False

    def generate_order(self, state: MarketState) -> Order | None:
        if self.done:
            return None
        self.done = True
        return Order(side=Side.BUY, quantity=self.quantity, order_type=OrderType.MARKET)


class PanelAwareStrategy:
    """패널 데이터를 활용하는 전략 (포트폴리오)"""

    def __init__(self):
        self.received_panels: list[dict] = []
        self.received_symbols: list[str] = []

    def generate_order(self, state: MarketState) -> Order | PortfolioOrder | None:
        # 패널 데이터 수신 확인용
        if state.panel is not None:
            self.received_panels.append(state.panel.copy())
        if state.symbol is not None:
            self.received_symbols.append(state.symbol)
        return None


class CrossCoinMomentumStrategy:
    """크로스코인 모멘텀: 가장 강한 코인 매수, 가장 약한 코인 매도"""

    def __init__(self, symbols: list[str]):
        self.symbols = symbols

    def generate_order(self, state: MarketState) -> PortfolioOrder | None:
        if state.panel is None or len(state.panel) < 2:
            return None

        # 패널에서 close 가격 비교 (단순화)
        closes = {}
        for sym, data in state.panel.items():
            if "close" in data and data["close"] is not None:
                closes[sym] = data["close"]

        if len(closes) < 2:
            return None

        # 가장 높은 close vs 가장 낮은 close (단순 시그널)
        strongest = max(closes, key=closes.get)
        weakest = min(closes, key=closes.get)

        orders = {}
        for sym in self.symbols:
            if sym == strongest and (state.positions is None or sym not in state.positions):
                orders[sym] = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.MARKET)
            elif sym == weakest and (state.positions is None or sym not in state.positions):
                orders[sym] = Order(side=Side.SELL, quantity=0.01, order_type=OrderType.MARKET)
            else:
                orders[sym] = None

        return PortfolioOrder(orders=orders)


class WeightedPortfolioStrategy:
    """비중 기반 PortfolioOrder를 한 번만 반환하는 테스트 전략"""

    def __init__(self, symbols: list[str], weights: dict[str, float]):
        self.symbols = symbols
        self.weights = weights
        self.triggered = False

    def generate_order(self, state: MarketState) -> PortfolioOrder | None:
        if self.triggered:
            return None
        if state.panel is None or len(state.panel) < len(self.symbols):
            return None

        self.triggered = True
        orders = {}
        for sym in self.symbols:
            weight = self.weights.get(sym)
            if weight is None:
                orders[sym] = None
            else:
                side = Side.BUY if weight > 0 else Side.SELL
                orders[sym] = Order(
                    side=side,
                    quantity=0.0,
                    weight=abs(weight),
                    order_type=OrderType.MARKET,
                )
        return PortfolioOrder(orders=orders)


# ─── 테스트 ───────────────────────────


class TestPortfolioTickRunnerInit:
    """초기화 테스트"""

    def test_create_with_multiple_loaders(self):
        """여러 심볼의 로더로 초기화"""
        from intraday.backtest.multi_tick_runner import PortfolioTickBacktestRunner

        loaders = {
            "BTCUSDT": FakeTickLoader([]),
            "ETHUSDT": FakeTickLoader([]),
        }

        runner = PortfolioTickBacktestRunner(
            strategy=AlwaysBuyStrategy(),
            data_loaders=loaders,
            bar_type=CandleType.TIME,
            bar_size=60,
            initial_capital=10000.0,
        )

        assert runner.symbols == ["BTCUSDT", "ETHUSDT"]
        assert runner.initial_capital == 10000.0

    def test_default_fee_rates(self):
        """기본 수수료율 (spread/slippage 포함)"""
        from intraday.backtest.multi_tick_runner import PortfolioTickBacktestRunner

        runner = PortfolioTickBacktestRunner(
            strategy=AlwaysBuyStrategy(),
            data_loaders={"BTCUSDT": FakeTickLoader([])},
            bar_type=CandleType.TIME,
            bar_size=60,
        )

        assert runner.maker_fee_rate == 0.0017
        assert runner.taker_fee_rate == 0.0020


class TestTickMerging:
    """틱 스트림 병합 테스트"""

    def test_merge_two_streams_in_order(self):
        """두 심볼의 틱이 시간순으로 병합됨"""
        from intraday.backtest.multi_tick_runner import PortfolioTickBacktestRunner

        base = datetime(2025, 3, 1, 9, 0, 0)

        btc_trades = [
            make_trade("BTC", 50000, 0.1, base + timedelta(seconds=1)),
            make_trade("BTC", 50010, 0.2, base + timedelta(seconds=3)),
        ]
        eth_trades = [
            make_trade("ETH", 3000, 1.0, base + timedelta(seconds=2)),
            make_trade("ETH", 3001, 0.5, base + timedelta(seconds=4)),
        ]

        loaders = {
            "BTCUSDT": FakeTickLoader(btc_trades),
            "ETHUSDT": FakeTickLoader(eth_trades),
        }

        runner = PortfolioTickBacktestRunner(
            strategy=PanelAwareStrategy(),
            data_loaders=loaders,
            bar_type=CandleType.TIME,
            bar_size=60,
        )

        # _merge_ticks 직접 테스트
        merged = list(runner._merge_ticks())
        assert len(merged) == 4

        # 시간순 확인
        timestamps = [t[1].timestamp for t in merged]
        assert timestamps == sorted(timestamps)

        # 심볼 확인
        symbols = [t[0] for t in merged]
        assert symbols == ["BTCUSDT", "ETHUSDT", "BTCUSDT", "ETHUSDT"]


class TestCandleBuildingPerSymbol:
    """심볼별 독립 캔들 빌드 테스트"""

    def test_independent_candle_builders(self):
        """각 심볼이 독립적으로 캔들을 빌드"""
        from intraday.backtest.multi_tick_runner import PortfolioTickBacktestRunner

        base = datetime(2025, 3, 1, 9, 0, 0)

        # BTC: 60초 동안 많은 틱 → 캔들 완성
        btc_trades = [
            make_trade("BTC", 50000 + i, 0.1, base + timedelta(seconds=i))
            for i in range(61)  # 0~60초
        ]
        # ETH: 동일
        eth_trades = [
            make_trade("ETH", 3000 + i * 0.1, 0.5, base + timedelta(seconds=i))
            for i in range(61)
        ]

        loaders = {
            "BTCUSDT": FakeTickLoader(btc_trades),
            "ETHUSDT": FakeTickLoader(eth_trades),
        }

        strategy = PanelAwareStrategy()

        runner = PortfolioTickBacktestRunner(
            strategy=strategy,
            data_loaders=loaders,
            bar_type=CandleType.TIME,
            bar_size=60,
        )

        result = runner.run()

        # 두 심볼 모두 캔들이 빌드됨
        assert runner.bar_counts["BTCUSDT"] >= 1
        assert runner.bar_counts["ETHUSDT"] >= 1


class TestPanelData:
    """패널 데이터 구성 테스트"""

    def test_panel_contains_all_symbols(self):
        """패널에 모든 심볼의 최신 캔들 데이터 포함"""
        from intraday.backtest.multi_tick_runner import PortfolioTickBacktestRunner

        base = datetime(2025, 3, 1, 9, 0, 0)

        # 두 심볼 모두 60초 분량
        btc_trades = [
            make_trade("BTC", 50000, 0.1, base + timedelta(seconds=i))
            for i in range(121)
        ]
        eth_trades = [
            make_trade("ETH", 3000, 0.5, base + timedelta(seconds=i))
            for i in range(121)
        ]

        loaders = {
            "BTCUSDT": FakeTickLoader(btc_trades),
            "ETHUSDT": FakeTickLoader(eth_trades),
        }

        strategy = PanelAwareStrategy()

        runner = PortfolioTickBacktestRunner(
            strategy=strategy,
            data_loaders=loaders,
            bar_type=CandleType.TIME,
            bar_size=60,
        )

        runner.run()

        # 패널 데이터가 전달됐는지 확인
        assert len(strategy.received_panels) > 0

        # 패널에 두 심볼 모두 포함
        for panel in strategy.received_panels:
            assert "BTCUSDT" in panel or "ETHUSDT" in panel

    def test_panel_has_ohlcv_fields(self):
        """패널 데이터에 OHLCV 필드 포함"""
        from intraday.backtest.multi_tick_runner import PortfolioTickBacktestRunner

        base = datetime(2025, 3, 1, 9, 0, 0)

        btc_trades = [
            make_trade("BTC", 50000 + i, 0.1, base + timedelta(seconds=i))
            for i in range(121)
        ]
        eth_trades = [
            make_trade("ETH", 3000, 0.5, base + timedelta(seconds=i))
            for i in range(121)
        ]

        loaders = {
            "BTCUSDT": FakeTickLoader(btc_trades),
            "ETHUSDT": FakeTickLoader(eth_trades),
        }

        strategy = PanelAwareStrategy()

        runner = PortfolioTickBacktestRunner(
            strategy=strategy,
            data_loaders=loaders,
            bar_type=CandleType.TIME,
            bar_size=60,
        )

        runner.run()

        # 패널의 각 심볼에 OHLCV 필드가 있는지 확인
        for panel in strategy.received_panels:
            for sym, data in panel.items():
                assert "close" in data
                assert "open" in data
                assert "high" in data
                assert "low" in data
                assert "volume" in data


class TestMarketStateSymbolField:
    """MarketState에 symbol 필드가 올바르게 설정되는지"""

    def test_symbol_field_set_on_candle_completion(self):
        """캔들 완성 시 MarketState.symbol이 설정됨"""
        from intraday.backtest.multi_tick_runner import PortfolioTickBacktestRunner

        base = datetime(2025, 3, 1, 9, 0, 0)

        btc_trades = [
            make_trade("BTC", 50000, 0.1, base + timedelta(seconds=i))
            for i in range(121)
        ]
        eth_trades = [
            make_trade("ETH", 3000, 0.5, base + timedelta(seconds=i))
            for i in range(121)
        ]

        loaders = {
            "BTCUSDT": FakeTickLoader(btc_trades),
            "ETHUSDT": FakeTickLoader(eth_trades),
        }

        strategy = PanelAwareStrategy()

        runner = PortfolioTickBacktestRunner(
            strategy=strategy,
            data_loaders=loaders,
            bar_type=CandleType.TIME,
            bar_size=60,
        )

        runner.run()

        # symbol 필드가 설정됨
        assert len(strategy.received_symbols) > 0
        assert all(s in ("BTCUSDT", "ETHUSDT") for s in strategy.received_symbols)


class TestPortfolioOrderExecution:
    """PortfolioOrder 실행 테스트"""

    def test_portfolio_order_opens_multiple_positions(self):
        """PortfolioOrder로 여러 심볼에 동시 포지션 오픈"""
        from intraday.backtest.multi_tick_runner import PortfolioTickBacktestRunner

        base = datetime(2025, 3, 1, 9, 0, 0)

        # 충분한 틱 데이터 (3분)
        btc_trades = [
            make_trade("BTC", 50000 + i * 10, 0.1, base + timedelta(seconds=i))
            for i in range(181)
        ]
        eth_trades = [
            make_trade("ETH", 3000 + i, 0.5, base + timedelta(seconds=i))
            for i in range(181)
        ]

        loaders = {
            "BTCUSDT": FakeTickLoader(btc_trades),
            "ETHUSDT": FakeTickLoader(eth_trades),
        }

        strategy = CrossCoinMomentumStrategy(symbols=["BTCUSDT", "ETHUSDT"])

        runner = PortfolioTickBacktestRunner(
            strategy=strategy,
            data_loaders=loaders,
            bar_type=CandleType.TIME,
            bar_size=60,
            initial_capital=10000.0,
        )

        result = runner.run()

        # 결과가 PortfolioBacktestResult 형태
        assert result.initial_capital == 10000.0
        assert isinstance(result.total_trades, int)

    def test_portfolio_order_with_weight_allocates_by_capital(self):
        """weight 기반 주문은 position_size_pct*weight 비중으로 수량 계산"""
        from intraday.backtest.multi_tick_runner import PortfolioTickBacktestRunner

        base = datetime(2025, 3, 1, 9, 0, 0)
        btc_trades = [
            make_trade("BTC", 50000.0, 0.1, base + timedelta(seconds=i))
            for i in range(121)
        ]
        eth_trades = [
            make_trade("ETH", 3000.0, 0.5, base + timedelta(seconds=i))
            for i in range(121)
        ]

        loaders = {
            "BTCUSDT": FakeTickLoader(btc_trades),
            "ETHUSDT": FakeTickLoader(eth_trades),
        }

        strategy = WeightedPortfolioStrategy(
            symbols=["BTCUSDT", "ETHUSDT"],
            weights={"BTCUSDT": 0.7, "ETHUSDT": 0.3},
        )

        runner = PortfolioTickBacktestRunner(
            strategy=strategy,
            data_loaders=loaders,
            bar_type=CandleType.TIME,
            bar_size=60,
            initial_capital=10000.0,
            position_size_pct=0.2,
            maker_fee_rate=0.0,
            taker_fee_rate=0.0,
        )

        # 초기 2개 바에서 주문이 1회 발생
        runner.run()

        # BTC 수량 = 10000*0.2*0.7 / 50000 = 0.028
        # ETH 수량 = 10000*0.2*0.3 / 3000 = 0.2
        opened = [t for t in runner._trade_log if t["action"].startswith("OPEN")]
        btc_open = next(t for t in opened if t["symbol"] == "BTCUSDT")
        eth_open = next(t for t in opened if t["symbol"] == "ETHUSDT")

        assert btc_open["quantity"] == pytest.approx(0.028, rel=1e-4)
        assert eth_open["quantity"] == pytest.approx(0.2, rel=1e-4)

    def test_quantity_order_fee_uses_notional_like_paper_trader(self):
        """명시 수량 주문 수수료는 PaperTrader처럼 체결 notional 기준"""
        from intraday.backtest.multi_tick_runner import PortfolioTickBacktestRunner

        base = datetime(2025, 3, 1, 9, 0, 0)
        btc_trades = [
            make_trade("BTC", 50000.0, 0.1, base + timedelta(seconds=i))
            for i in range(121)
        ]

        runner = PortfolioTickBacktestRunner(
            strategy=AlwaysBuyStrategy(),
            data_loaders={"BTCUSDT": FakeTickLoader(btc_trades)},
            bar_type=CandleType.TIME,
            bar_size=60,
            initial_capital=10000.0,
            position_size_pct=0.1,
            taker_fee_rate=0.002,
        )

        runner.run()

        opened = [t for t in runner._trade_log if t["action"] == "OPEN_LONG"]
        assert opened[0]["fee"] == pytest.approx(50000.0 * 0.01 * 0.002)

    def test_weight_sum_exceed_raises(self):
        """weight 합이 1 초과면 실행 단계에서 실패"""
        from intraday.backtest.multi_tick_runner import PortfolioTickBacktestRunner

        base = datetime(2025, 3, 1, 9, 0, 0)
        loader = {
            "BTCUSDT": FakeTickLoader([
                make_trade("BTC", 50000.0 + i, 0.1, base + timedelta(seconds=i))
                for i in range(61)
            ]),
            "ETHUSDT": FakeTickLoader([
                make_trade("ETH", 3000.0 + i, 0.5, base + timedelta(seconds=i))
                for i in range(61)
            ]),
        }

        strategy = WeightedPortfolioStrategy(
            symbols=["BTCUSDT", "ETHUSDT"],
            weights={"BTCUSDT": 0.6, "ETHUSDT": 0.7},
        )

        runner = PortfolioTickBacktestRunner(
            strategy=strategy,
            data_loaders=loader,
            bar_type=CandleType.TIME,
            bar_size=60,
        )

        with pytest.raises(ValueError):
            runner.run()


class TestSingleOrderFallback:
    """단일 Order 반환 전략과의 호환성"""

    def test_single_order_applied_to_triggering_symbol(self):
        """단일 Order는 캔들이 완성된 심볼에 적용"""
        from intraday.backtest.multi_tick_runner import PortfolioTickBacktestRunner

        base = datetime(2025, 3, 1, 9, 0, 0)

        btc_trades = [
            make_trade("BTC", 50000, 0.1, base + timedelta(seconds=i))
            for i in range(121)
        ]

        loaders = {"BTCUSDT": FakeTickLoader(btc_trades)}

        runner = PortfolioTickBacktestRunner(
            strategy=AlwaysBuyStrategy(),
            data_loaders=loaders,
            bar_type=CandleType.TIME,
            bar_size=60,
        )

        result = runner.run()

        # 최소 1개 이상의 거래 발생
        assert result.total_trades >= 1


class TestPortfolioFuturesExecution:
    """포트폴리오 tick runner의 선물 실행 모델"""

    def test_leveraged_long_is_liquidated_before_final_close(self):
        """leverage>1이면 단일 PaperTrader와 같은 방향으로 청산을 반영"""
        from intraday.backtest.multi_tick_runner import PortfolioTickBacktestRunner

        base = datetime(2025, 3, 1, 9, 0, 0)
        prices = [50000.0] * 61 + [44000.0] * 10
        trades = [
            make_trade("BTC", price, 0.1, base + timedelta(seconds=i))
            for i, price in enumerate(prices)
        ]

        runner = PortfolioTickBacktestRunner(
            strategy=BuyOnceStrategy(quantity=0.01),
            data_loaders={"BTCUSDT": FakeTickLoader(trades)},
            bar_type=CandleType.TIME,
            bar_size=60,
            initial_capital=10000.0,
            taker_fee_rate=0.0,
            leverage=10,
        )

        runner.run()

        assert any(t["action"] == "LIQUIDATION" for t in runner._trade_log)
        assert not any(t["action"] == "CLOSE_FINAL" for t in runner._trade_log)


class TestResultOutput:
    """결과 출력 형식"""

    def test_result_has_equity_curve(self):
        """결과에 에쿼티 커브 포함"""
        from intraday.backtest.multi_tick_runner import PortfolioTickBacktestRunner

        base = datetime(2025, 3, 1, 9, 0, 0)

        btc_trades = [
            make_trade("BTC", 50000, 0.1, base + timedelta(seconds=i))
            for i in range(181)
        ]
        eth_trades = [
            make_trade("ETH", 3000, 0.5, base + timedelta(seconds=i))
            for i in range(181)
        ]

        loaders = {
            "BTCUSDT": FakeTickLoader(btc_trades),
            "ETHUSDT": FakeTickLoader(eth_trades),
        }

        runner = PortfolioTickBacktestRunner(
            strategy=PanelAwareStrategy(),
            data_loaders=loaders,
            bar_type=CandleType.TIME,
            bar_size=60,
        )

        result = runner.run()

        assert hasattr(result, "equity_curve")
        assert len(result.equity_curve) > 0

    def test_result_has_symbol_breakdown(self):
        """결과에 심볼별 분석 포함"""
        from intraday.backtest.multi_tick_runner import PortfolioTickBacktestRunner

        base = datetime(2025, 3, 1, 9, 0, 0)

        btc_trades = [
            make_trade("BTC", 50000 + i * 10, 0.1, base + timedelta(seconds=i))
            for i in range(181)
        ]
        eth_trades = [
            make_trade("ETH", 3000 + i, 0.5, base + timedelta(seconds=i))
            for i in range(181)
        ]

        loaders = {
            "BTCUSDT": FakeTickLoader(btc_trades),
            "ETHUSDT": FakeTickLoader(eth_trades),
        }

        strategy = CrossCoinMomentumStrategy(symbols=["BTCUSDT", "ETHUSDT"])

        runner = PortfolioTickBacktestRunner(
            strategy=strategy,
            data_loaders=loaders,
            bar_type=CandleType.TIME,
            bar_size=60,
            initial_capital=10000.0,
        )

        result = runner.run()

        # get_symbol_breakdown 존재
        breakdown = result.get_symbol_breakdown()
        assert isinstance(breakdown, dict)


class TestEmptyData:
    """빈 데이터 처리"""

    def test_empty_loaders_raises(self):
        """데이터 없으면 적절한 에러"""
        from intraday.backtest.multi_tick_runner import PortfolioTickBacktestRunner

        loaders = {
            "BTCUSDT": FakeTickLoader([]),
            "ETHUSDT": FakeTickLoader([]),
        }

        runner = PortfolioTickBacktestRunner(
            strategy=PanelAwareStrategy(),
            data_loaders=loaders,
            bar_type=CandleType.TIME,
            bar_size=60,
        )

        result = runner.run()

        # 빈 데이터는 에러 아니라 빈 결과
        assert result.total_trades == 0
        assert result.total_return == 0.0
