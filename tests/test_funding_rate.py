"""
Funding Rate 테스트

TDD 방식으로 Funding Rate 기능을 검증합니다.
"""

import pytest
from datetime import datetime, timezone
from pathlib import Path

from intraday.funding import FundingRate, FundingRateLoader, FundingSettlement
from intraday.paper_trader import PaperTrader, Position
from intraday.strategy import Side, Order, OrderType


class TestFundingRateModel:
    """Funding Rate 데이터 모델 테스트"""

    def test_funding_rate_creation(self):
        """FundingRate 객체 생성"""
        fr = FundingRate(
            timestamp=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            symbol="BTCUSDT",
            funding_rate=0.0001,  # 0.01%
            mark_price=42000.0,
        )
        assert fr.funding_rate == 0.0001
        assert fr.symbol == "BTCUSDT"

    def test_funding_rate_to_annual_rate(self):
        """연환산 이율 계산 (8시간마다 × 3 × 365)"""
        fr = FundingRate(
            timestamp=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            symbol="BTCUSDT",
            funding_rate=0.0001,
            mark_price=42000.0,
        )
        # 0.01% × 3 × 365 = 10.95%
        assert abs(fr.annual_rate - 0.1095) < 0.001


class TestFundingSettlement:
    """Funding 정산 로직 테스트"""

    def test_settlement_times_utc(self):
        """정산 시간은 00:00, 08:00, 16:00 UTC"""
        settlement = FundingSettlement()
        assert settlement.FUNDING_HOURS == [0, 8, 16]

    def test_is_funding_time_at_exact_hour(self):
        """정확한 정산 시간에 True"""
        settlement = FundingSettlement()

        # 00:00 UTC
        t1 = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert settlement.is_funding_time(t1) is True

        # 08:00 UTC
        t2 = datetime(2024, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
        assert settlement.is_funding_time(t2) is True

        # 16:00 UTC
        t3 = datetime(2024, 1, 1, 16, 0, 0, tzinfo=timezone.utc)
        assert settlement.is_funding_time(t3) is True

    def test_is_not_funding_time(self):
        """정산 시간이 아니면 False"""
        settlement = FundingSettlement()

        t = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        assert settlement.is_funding_time(t) is False

    def test_should_settle_crossing_funding_time(self):
        """정산 시간을 지나면 정산해야 함"""
        settlement = FundingSettlement()

        last_check = datetime(2024, 1, 1, 7, 59, 0, tzinfo=timezone.utc)
        current = datetime(2024, 1, 1, 8, 1, 0, tzinfo=timezone.utc)

        assert settlement.should_settle(current, last_check) is True

    def test_should_not_settle_same_period(self):
        """같은 정산 기간 내에서는 정산하지 않음"""
        settlement = FundingSettlement()

        last_check = datetime(2024, 1, 1, 8, 1, 0, tzinfo=timezone.utc)
        current = datetime(2024, 1, 1, 8, 30, 0, tzinfo=timezone.utc)

        assert settlement.should_settle(current, last_check) is False

    def test_calculate_payment_long_positive_rate(self):
        """롱 포지션 + 양수 펀딩레이트 = 지불"""
        settlement = FundingSettlement()

        # 롱 1 BTC @ $50,000, 펀딩레이트 0.01%
        payment = settlement.calculate_payment(
            position_side=Side.BUY,
            position_size=1.0,
            mark_price=50000.0,
            funding_rate=0.0001,
        )

        # 50000 * 1.0 * 0.0001 = -5.0 (지불)
        assert payment == -5.0

    def test_calculate_payment_short_positive_rate(self):
        """숏 포지션 + 양수 펀딩레이트 = 수취"""
        settlement = FundingSettlement()

        payment = settlement.calculate_payment(
            position_side=Side.SELL,
            position_size=1.0,
            mark_price=50000.0,
            funding_rate=0.0001,
        )

        # 숏은 양수 펀딩레이트에서 수취
        assert payment == 5.0

    def test_calculate_payment_long_negative_rate(self):
        """롱 포지션 + 음수 펀딩레이트 = 수취"""
        settlement = FundingSettlement()

        payment = settlement.calculate_payment(
            position_side=Side.BUY,
            position_size=1.0,
            mark_price=50000.0,
            funding_rate=-0.0001,
        )

        assert payment == 5.0

    def test_calculate_payment_short_negative_rate(self):
        """숏 포지션 + 음수 펀딩레이트 = 지불"""
        settlement = FundingSettlement()

        payment = settlement.calculate_payment(
            position_side=Side.SELL,
            position_size=1.0,
            mark_price=50000.0,
            funding_rate=-0.0001,
        )

        assert payment == -5.0


class TestPaperTraderFunding:
    """PaperTrader Funding 정산 테스트"""

    def test_apply_funding_long_positive_rate(self):
        """롱 포지션에 양수 펀딩레이트 적용"""
        trader = PaperTrader(initial_capital=10000, leverage=10)

        # 롱 포지션 오픈
        order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order)
        trader.on_price_update(
            price=50000,
            best_bid=49990,
            best_ask=50000,
            timestamp=datetime.now(),
        )

        balance_before = trader.usd_balance

        # Funding 정산: 0.01% 지불
        trader.apply_funding(funding_rate=0.0001, mark_price=50000.0)

        # 0.1 BTC * 50000 * 0.0001 = 0.5 USD 지불
        assert trader.usd_balance == balance_before - 0.5

    def test_apply_funding_short_positive_rate(self):
        """숏 포지션에 양수 펀딩레이트 적용"""
        trader = PaperTrader(initial_capital=10000, leverage=10)

        # 숏 포지션 오픈
        order = Order(side=Side.SELL, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order)
        trader.on_price_update(
            price=50000,
            best_bid=50000,
            best_ask=50010,
            timestamp=datetime.now(),
        )

        balance_before = trader.usd_balance

        # Funding 정산: 0.01% 수취
        trader.apply_funding(funding_rate=0.0001, mark_price=50000.0)

        # 0.1 BTC * 50000 * 0.0001 = 0.5 USD 수취
        assert trader.usd_balance == balance_before + 0.5

    def test_apply_funding_no_position(self):
        """포지션 없으면 Funding 영향 없음"""
        trader = PaperTrader(initial_capital=10000, leverage=10)

        balance_before = trader.usd_balance

        trader.apply_funding(funding_rate=0.0001, mark_price=50000.0)

        assert trader.usd_balance == balance_before

    def test_apply_funding_spot_mode_no_effect(self):
        """현물 모드에서는 Funding 적용 안 함"""
        trader = PaperTrader(initial_capital=10000, leverage=1)  # 현물

        # 포지션 오픈
        order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order)
        trader.on_price_update(
            price=50000,
            best_bid=49990,
            best_ask=50000,
            timestamp=datetime.now(),
        )

        balance_before = trader.usd_balance

        trader.apply_funding(funding_rate=0.0001, mark_price=50000.0)

        # 현물 모드에서는 변화 없음
        assert trader.usd_balance == balance_before


class TestFundingRateLoader:
    """Funding Rate 데이터 로더 테스트"""

    def test_loader_from_list(self):
        """리스트에서 로더 생성"""
        rates = [
            FundingRate(
                timestamp=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                symbol="BTCUSDT",
                funding_rate=0.0001,
                mark_price=42000.0,
            ),
            FundingRate(
                timestamp=datetime(2024, 1, 1, 8, 0, 0, tzinfo=timezone.utc),
                symbol="BTCUSDT",
                funding_rate=0.00015,
                mark_price=42500.0,
            ),
        ]

        loader = FundingRateLoader.from_list(rates)
        assert len(loader) == 2

    def test_get_rate_at_exact_time(self):
        """정확한 시간의 펀딩레이트 조회"""
        rates = [
            FundingRate(
                timestamp=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                symbol="BTCUSDT",
                funding_rate=0.0001,
                mark_price=42000.0,
            ),
            FundingRate(
                timestamp=datetime(2024, 1, 1, 8, 0, 0, tzinfo=timezone.utc),
                symbol="BTCUSDT",
                funding_rate=0.00015,
                mark_price=42500.0,
            ),
        ]

        loader = FundingRateLoader.from_list(rates)

        rate = loader.get_rate_at(datetime(2024, 1, 1, 8, 0, 0, tzinfo=timezone.utc))
        assert rate is not None
        assert rate.funding_rate == 0.00015

    def test_get_rate_at_returns_none_if_not_found(self):
        """해당 시간에 데이터 없으면 None"""
        rates = [
            FundingRate(
                timestamp=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                symbol="BTCUSDT",
                funding_rate=0.0001,
                mark_price=42000.0,
            ),
        ]

        loader = FundingRateLoader.from_list(rates)

        rate = loader.get_rate_at(datetime(2024, 1, 1, 8, 0, 0, tzinfo=timezone.utc))
        assert rate is None

    def test_get_latest_rate_before(self):
        """특정 시간 이전의 최신 펀딩레이트 조회"""
        rates = [
            FundingRate(
                timestamp=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                symbol="BTCUSDT",
                funding_rate=0.0001,
                mark_price=42000.0,
            ),
            FundingRate(
                timestamp=datetime(2024, 1, 1, 8, 0, 0, tzinfo=timezone.utc),
                symbol="BTCUSDT",
                funding_rate=0.00015,
                mark_price=42500.0,
            ),
        ]

        loader = FundingRateLoader.from_list(rates)

        # 08:30에 조회하면 08:00 데이터 반환
        rate = loader.get_latest_rate_before(
            datetime(2024, 1, 1, 8, 30, 0, tzinfo=timezone.utc)
        )
        assert rate is not None
        assert rate.funding_rate == 0.00015


class TestTickBacktestRunnerFunding:
    """TickBacktestRunner Funding 정산 통합 테스트"""

    def test_runner_accepts_funding_loader_parameter(self):
        """Runner가 funding_loader 파라미터를 받아야 한다"""
        from unittest.mock import Mock
        from intraday.backtest.tick_runner import TickBacktestRunner

        mock_loader = Mock()
        mock_strategy = Mock()

        rates = [
            FundingRate(
                timestamp=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                symbol="BTCUSDT",
                funding_rate=0.0001,
                mark_price=42000.0,
            ),
        ]
        funding_loader = FundingRateLoader.from_list(rates)

        runner = TickBacktestRunner(
            strategy=mock_strategy,
            data_loader=mock_loader,
            leverage=10,
            funding_loader=funding_loader,
        )

        assert runner.funding_loader is funding_loader

    def test_runner_tracks_total_funding_paid(self):
        """Runner가 총 펀딩 지불액을 추적해야 한다"""
        from unittest.mock import Mock
        from intraday.backtest.tick_runner import TickBacktestRunner

        mock_loader = Mock()
        mock_strategy = Mock()

        runner = TickBacktestRunner(
            strategy=mock_strategy,
            data_loader=mock_loader,
            leverage=10,
        )

        assert hasattr(runner, '_total_funding_paid')
        assert runner._total_funding_paid == 0.0

    def test_runner_applies_funding_at_settlement_time(self):
        """Runner가 정산 시간에 펀딩을 적용해야 한다"""
        from unittest.mock import Mock
        from intraday.backtest.tick_runner import TickBacktestRunner
        from intraday.client import AggTrade

        mock_loader = Mock()
        mock_strategy = Mock()
        mock_strategy.generate_order.return_value = None

        # 08:00 UTC 펀딩레이트
        rates = [
            FundingRate(
                timestamp=datetime(2024, 1, 1, 8, 0, 0, tzinfo=timezone.utc),
                symbol="BTCUSDT",
                funding_rate=0.0001,
                mark_price=50000.0,
            ),
        ]
        funding_loader = FundingRateLoader.from_list(rates)

        runner = TickBacktestRunner(
            strategy=mock_strategy,
            data_loader=mock_loader,
            leverage=10,
            funding_loader=funding_loader,
        )

        # 롱 포지션 오픈
        order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        runner._trader.submit_order(order)
        runner._trader.on_price_update(
            price=50000,
            best_bid=49990,
            best_ask=50000,
            timestamp=datetime(2024, 1, 1, 7, 59, 0, tzinfo=timezone.utc),
        )

        balance_before = runner._trader.usd_balance

        # 08:01 틱 처리 (정산 시간 통과)
        tick = AggTrade(
            timestamp=datetime(2024, 1, 1, 8, 1, 0, tzinfo=timezone.utc),
            symbol="BTCUSDT",
            price=50000.0,
            quantity=0.01,
            is_buyer_maker=False,
        )

        # _last_funding_check 초기화
        runner._last_funding_check = datetime(2024, 1, 1, 7, 59, 0, tzinfo=timezone.utc)

        runner._process_tick(tick)

        # 0.1 BTC * 50000 * 0.0001 = 0.5 USD 지불
        assert runner._trader.usd_balance < balance_before
        assert runner._total_funding_paid != 0.0

    def test_runner_no_funding_without_loader(self):
        """funding_loader가 없으면 펀딩 정산 안 함"""
        from unittest.mock import Mock
        from intraday.backtest.tick_runner import TickBacktestRunner
        from intraday.client import AggTrade

        mock_loader = Mock()
        mock_strategy = Mock()
        mock_strategy.generate_order.return_value = None

        runner = TickBacktestRunner(
            strategy=mock_strategy,
            data_loader=mock_loader,
            leverage=10,
            funding_loader=None,
        )

        # 롱 포지션 오픈
        order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        runner._trader.submit_order(order)
        runner._trader.on_price_update(
            price=50000,
            best_bid=49990,
            best_ask=50000,
            timestamp=datetime(2024, 1, 1, 7, 59, 0, tzinfo=timezone.utc),
        )

        balance_before = runner._trader.usd_balance

        # 08:01 틱 처리
        tick = AggTrade(
            timestamp=datetime(2024, 1, 1, 8, 1, 0, tzinfo=timezone.utc),
            symbol="BTCUSDT",
            price=50000.0,
            quantity=0.01,
            is_buyer_maker=False,
        )

        runner._last_funding_check = datetime(2024, 1, 1, 7, 59, 0, tzinfo=timezone.utc)
        runner._process_tick(tick)

        # 잔액 변화 없음 (펀딩 정산 안 함)
        assert runner._trader.usd_balance == balance_before
        assert runner._total_funding_paid == 0.0

    def test_runner_no_funding_in_spot_mode(self):
        """현물 모드에서는 펀딩 정산 안 함"""
        from unittest.mock import Mock
        from intraday.backtest.tick_runner import TickBacktestRunner
        from intraday.client import AggTrade

        mock_loader = Mock()
        mock_strategy = Mock()
        mock_strategy.generate_order.return_value = None

        rates = [
            FundingRate(
                timestamp=datetime(2024, 1, 1, 8, 0, 0, tzinfo=timezone.utc),
                symbol="BTCUSDT",
                funding_rate=0.0001,
                mark_price=50000.0,
            ),
        ]
        funding_loader = FundingRateLoader.from_list(rates)

        runner = TickBacktestRunner(
            strategy=mock_strategy,
            data_loader=mock_loader,
            leverage=1,  # 현물 모드
            funding_loader=funding_loader,
        )

        # 포지션 오픈
        order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        runner._trader.submit_order(order)
        runner._trader.on_price_update(
            price=50000,
            best_bid=49990,
            best_ask=50000,
            timestamp=datetime(2024, 1, 1, 7, 59, 0, tzinfo=timezone.utc),
        )

        balance_before = runner._trader.usd_balance

        # 08:01 틱 처리
        tick = AggTrade(
            timestamp=datetime(2024, 1, 1, 8, 1, 0, tzinfo=timezone.utc),
            symbol="BTCUSDT",
            price=50000.0,
            quantity=0.01,
            is_buyer_maker=False,
        )

        runner._last_funding_check = datetime(2024, 1, 1, 7, 59, 0, tzinfo=timezone.utc)
        runner._process_tick(tick)

        # 잔액 변화 없음 (현물 모드)
        assert runner._trader.usd_balance == balance_before


class TestPerformanceReportFunding:
    """PerformanceReport Funding 정보 테스트"""

    def test_performance_report_has_funding_paid_field(self):
        """PerformanceReport에 total_funding_paid 필드가 있어야 한다"""
        from intraday.performance import PerformanceReport

        report = PerformanceReport(
            strategy_name="TestStrategy",
            symbol="BTCUSDT",
            start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_time=datetime(2024, 1, 2, tzinfo=timezone.utc),
            initial_capital=10000.0,
            final_capital=10050.0,
            total_return=0.5,
            total_trades=10,
            winning_trades=6,
            losing_trades=4,
            win_rate=60.0,
            profit_factor=1.5,
            avg_win=10.0,
            avg_loss=-5.0,
            max_drawdown=2.0,
            sharpe_ratio=1.5,
            total_fees=5.0,
            total_funding_paid=-2.5,  # 새 필드
        )

        assert hasattr(report, "total_funding_paid")
        assert report.total_funding_paid == -2.5

    def test_performance_report_funding_default_zero(self):
        """total_funding_paid 기본값은 0이어야 한다"""
        from intraday.performance import PerformanceReport

        report = PerformanceReport(
            strategy_name="TestStrategy",
            symbol="BTCUSDT",
            start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_time=datetime(2024, 1, 2, tzinfo=timezone.utc),
            initial_capital=10000.0,
            final_capital=10050.0,
            total_return=0.5,
            total_trades=10,
            winning_trades=6,
            losing_trades=4,
            win_rate=60.0,
            profit_factor=1.5,
            avg_win=10.0,
            avg_loss=-5.0,
            max_drawdown=2.0,
            sharpe_ratio=1.5,
            total_fees=5.0,
        )

        assert report.total_funding_paid == 0.0

    def test_performance_report_print_includes_funding(self, capsys):
        """print_summary에 펀딩 정보가 포함되어야 한다"""
        from intraday.performance import PerformanceReport

        report = PerformanceReport(
            strategy_name="TestStrategy",
            symbol="BTCUSDT",
            start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_time=datetime(2024, 1, 2, tzinfo=timezone.utc),
            initial_capital=10000.0,
            final_capital=10050.0,
            total_return=0.5,
            total_trades=10,
            winning_trades=6,
            losing_trades=4,
            win_rate=60.0,
            profit_factor=1.5,
            avg_win=10.0,
            avg_loss=-5.0,
            max_drawdown=2.0,
            sharpe_ratio=1.5,
            total_fees=5.0,
            total_funding_paid=-2.5,
        )

        report.print_summary()

        captured = capsys.readouterr()
        assert "펀딩" in captured.out or "Funding" in captured.out


class TestFundingWithVolumeCandleIndependence:
    """펀딩피 정산과 볼륨 캔들 독립성 테스트

    핵심 검증 포인트:
        - 펀딩피 정산은 틱의 timestamp 기준으로 발생
        - 볼륨 캔들 완성 여부와 무관하게 정산됨
        - 캔들 타입(볼륨바, 시간바 등)에 영향받지 않음
    """

    def test_funding_settles_on_tick_not_candle(self):
        """펀딩피는 틱 기준으로 정산되고 캔들 완성과 무관하다"""
        from unittest.mock import Mock
        from intraday.backtest.tick_runner import TickBacktestRunner
        from intraday.candle_builder import CandleType
        from intraday.client import AggTrade

        mock_loader = Mock()
        mock_strategy = Mock()
        mock_strategy.generate_order.return_value = None

        # 08:00 UTC 펀딩레이트
        rates = [
            FundingRate(
                timestamp=datetime(2024, 1, 1, 8, 0, 0, tzinfo=timezone.utc),
                symbol="BTCUSDT",
                funding_rate=0.0001,
                mark_price=50000.0,
            ),
        ]
        funding_loader = FundingRateLoader.from_list(rates)

        # 볼륨 바 크기를 매우 크게 설정 (100 BTC → 캔들 완성 안 됨)
        runner = TickBacktestRunner(
            strategy=mock_strategy,
            data_loader=mock_loader,
            leverage=10,
            funding_loader=funding_loader,
            bar_type=CandleType.VOLUME,
            bar_size=100.0,  # 100 BTC마다 캔들 생성 (테스트에서 도달 안 함)
        )

        # 롱 포지션 오픈
        order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        runner._trader.submit_order(order)
        runner._trader.on_price_update(
            price=50000,
            best_bid=49990,
            best_ask=50000,
            timestamp=datetime(2024, 1, 1, 7, 59, 0, tzinfo=timezone.utc),
        )

        balance_before = runner._trader.usd_balance

        # 08:01 틱 (작은 볼륨 → 캔들 완성 안 됨)
        tick = AggTrade(
            timestamp=datetime(2024, 1, 1, 8, 1, 0, tzinfo=timezone.utc),
            symbol="BTCUSDT",
            price=50000.0,
            quantity=0.001,  # 매우 작은 볼륨
            is_buyer_maker=False,
        )

        runner._last_funding_check = datetime(2024, 1, 1, 7, 59, 0, tzinfo=timezone.utc)
        runner._process_tick(tick)

        # 캔들 완성 안 됨 확인
        assert runner.bar_count == 0

        # 하지만 펀딩피는 정산됨!
        assert runner._trader.usd_balance < balance_before
        assert runner._total_funding_paid != 0.0

    def test_funding_timing_across_different_candle_types(self):
        """다른 캔들 타입에서도 펀딩 타이밍이 동일하다"""
        from unittest.mock import Mock
        from intraday.backtest.tick_runner import TickBacktestRunner
        from intraday.candle_builder import CandleType
        from intraday.client import AggTrade

        # 동일한 펀딩레이트
        rates = [
            FundingRate(
                timestamp=datetime(2024, 1, 1, 8, 0, 0, tzinfo=timezone.utc),
                symbol="BTCUSDT",
                funding_rate=0.0001,
                mark_price=50000.0,
            ),
        ]
        funding_loader = FundingRateLoader.from_list(rates)

        funding_amounts = []

        # 볼륨바, 틱바 두 가지 타입으로 테스트
        for candle_type in [CandleType.VOLUME, CandleType.TICK]:
            mock_loader = Mock()
            mock_strategy = Mock()
            mock_strategy.generate_order.return_value = None

            runner = TickBacktestRunner(
                strategy=mock_strategy,
                data_loader=mock_loader,
                leverage=10,
                funding_loader=funding_loader,
                bar_type=candle_type,
                bar_size=1000.0,  # 캔들 완성 안 되게 큰 값
            )

            # 동일한 포지션 오픈
            order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
            runner._trader.submit_order(order)
            runner._trader.on_price_update(
                price=50000,
                best_bid=49990,
                best_ask=50000,
                timestamp=datetime(2024, 1, 1, 7, 59, 0, tzinfo=timezone.utc),
            )

            balance_before = runner._trader.usd_balance

            # 동일한 틱 처리
            tick = AggTrade(
                timestamp=datetime(2024, 1, 1, 8, 1, 0, tzinfo=timezone.utc),
                symbol="BTCUSDT",
                price=50000.0,
                quantity=0.01,
                is_buyer_maker=False,
            )

            runner._last_funding_check = datetime(2024, 1, 1, 7, 59, 0, tzinfo=timezone.utc)
            runner._process_tick(tick)

            funding_amounts.append(runner._total_funding_paid)

        # 캔들 타입과 무관하게 동일한 펀딩 정산액
        assert funding_amounts[0] == funding_amounts[1]
        assert all(amount != 0 for amount in funding_amounts)

    def test_funding_uses_tick_timestamp_not_candle_timestamp(self):
        """펀딩 정산은 틱 timestamp를 사용하고 캔들 timestamp가 아니다"""
        from unittest.mock import Mock
        from intraday.backtest.tick_runner import TickBacktestRunner
        from intraday.candle_builder import CandleType
        from intraday.client import AggTrade

        mock_loader = Mock()
        mock_strategy = Mock()
        mock_strategy.generate_order.return_value = None

        rates = [
            FundingRate(
                timestamp=datetime(2024, 1, 1, 8, 0, 0, tzinfo=timezone.utc),
                symbol="BTCUSDT",
                funding_rate=0.0001,
                mark_price=50000.0,
            ),
        ]
        funding_loader = FundingRateLoader.from_list(rates)

        # 시간바 5분 (캔들이 05분마다 완성)
        runner = TickBacktestRunner(
            strategy=mock_strategy,
            data_loader=mock_loader,
            leverage=10,
            funding_loader=funding_loader,
            bar_type=CandleType.TIME,
            bar_size=300,  # 5분 = 300초
        )

        # 포지션 오픈 @ 07:57
        order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        runner._trader.submit_order(order)
        runner._trader.on_price_update(
            price=50000,
            best_bid=49990,
            best_ask=50000,
            timestamp=datetime(2024, 1, 1, 7, 57, 0, tzinfo=timezone.utc),
        )

        runner._last_funding_check = datetime(2024, 1, 1, 7, 57, 0, tzinfo=timezone.utc)
        balance_before = runner._trader.usd_balance

        # 틱 @ 08:01 (틱 시간 기준 정산 시간 통과)
        # 하지만 5분봉은 08:05에 완성됨
        tick = AggTrade(
            timestamp=datetime(2024, 1, 1, 8, 1, 0, tzinfo=timezone.utc),
            symbol="BTCUSDT",
            price=50000.0,
            quantity=0.01,
            is_buyer_maker=False,
        )

        runner._process_tick(tick)

        # 캔들은 아직 완성 안 됨 (08:05에 완성)
        # 하지만 펀딩은 08:01 틱에서 이미 정산됨
        assert runner._trader.usd_balance < balance_before
        assert runner._total_funding_paid != 0.0
