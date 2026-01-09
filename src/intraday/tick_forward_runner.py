"""
Tick 기반 Forward Test 러너

실시간 aggTrade 데이터를 받아 캔들을 빌드하고 전략을 실행합니다.
BB Squeeze, VPIN 등 틱/캔들 기반 전략에 사용합니다.

사용 예시:
    from intraday import TickForwardRunner, CandleType
    from intraday.strategies.tick.bb_squeeze import BBSqueezeStrategy

    strategy = BBSqueezeStrategy(quantity=0.01)
    runner = TickForwardRunner(
        strategy=strategy,
        symbol="btcusdt",
        candle_type=CandleType.TIME,
        candle_size=240,  # 4분봉
    )
    await runner.run(duration_seconds=3600)
"""

import asyncio
from datetime import datetime
from typing import Optional

from .client import BinanceCombinedClient, OrderbookSnapshot, AggTrade
from .candle_builder import CandleBuilder, CandleType, Candle
from .paper_trader import PaperTrader
from .performance import PerformanceReport, PerformanceCalculator
from .strategy import Strategy, MarketState, Side


class TickForwardRunner:
    """
    틱 기반 실시간 Forward Test 러너

    실시간 aggTrade 웹소켓에서 틱 데이터를 받아:
    1. CandleBuilder로 캔들 빌드 (TIME, VOLUME, TICK, DOLLAR)
    2. 캔들 완성 시 전략 실행
    3. PaperTrader로 가상 매매

    사용 예시:
        strategy = BBSqueezeStrategy(quantity=0.5)
        runner = TickForwardRunner(
            strategy=strategy,
            symbol="btcusdt",
            candle_type=CandleType.TIME,
            candle_size=240,  # 4분봉
            leverage=10,
        )
        await runner.run(duration_seconds=3600)
        report = runner.get_performance_report()
    """

    def __init__(
        self,
        strategy: Strategy,
        symbol: str = "btcusdt",
        candle_type: CandleType = CandleType.TIME,
        candle_size: float = 240.0,
        initial_capital: float = 10000.0,
        fee_rate: float = 0.001,
        leverage: int = 1,
    ):
        """
        Args:
            strategy: 실행할 전략 (Strategy Protocol 구현체)
            symbol: 거래쌍 (예: btcusdt)
            candle_type: 캔들 타입 (TIME, VOLUME, TICK, DOLLAR)
            candle_size: 캔들 크기
                - TIME: 초 (예: 240 = 4분)
                - VOLUME: BTC (예: 10.0 = 10 BTC)
                - TICK: 틱 수 (예: 100)
                - DOLLAR: USD (예: 1000000 = 100만 달러)
            initial_capital: 초기 자본금 (USD)
            fee_rate: 수수료율 (기본 0.1%)
            leverage: 레버리지 (1=현물, 2+=선물)
        """
        self.strategy = strategy
        self.symbol = symbol
        self.candle_type = candle_type
        self.candle_size = candle_size
        self.initial_capital = initial_capital
        self.fee_rate = fee_rate
        self.leverage = leverage

        # 내부 컴포넌트
        self._client = BinanceCombinedClient(symbol)
        self._candle_builder = CandleBuilder(candle_type, candle_size)
        self._trader = PaperTrader(initial_capital, fee_rate, leverage=leverage)

        # 상태
        self._running = False
        self._start_time: Optional[datetime] = None
        self._end_time: Optional[datetime] = None
        self._last_trade_price: float = 0.0
        self._current_candle: Optional[Candle] = None

        # 통계
        self._tick_count = 0
        self._candle_count = 0
        self._order_count = 0
        self._trade_count = 0

    @property
    def is_running(self) -> bool:
        """실행 중 여부"""
        return self._running

    @property
    def last_trade_price(self) -> float:
        """마지막 체결가"""
        return self._last_trade_price

    @property
    def current_candle(self) -> Optional[Candle]:
        """현재 진행 중인 캔들"""
        return self._candle_builder.current_candle

    async def run(self, duration_seconds: Optional[float] = None) -> None:
        """
        Forward Test 실행

        Args:
            duration_seconds: 실행 시간 (초). None이면 stop()까지 실행
        """
        self._running = True
        self._start_time = datetime.now()

        print("=" * 60)
        print("Tick Forward Test Configuration")
        print("=" * 60)
        print(f"Symbol: {self.symbol.upper()}")
        print(f"Strategy: {self.strategy.__class__.__name__}")
        print(f"Candle Type: {self.candle_type.value}")
        print(f"Candle Size: {self.candle_size}")
        print(f"Initial Capital: ${self.initial_capital:,.2f}")
        print(f"Leverage: {self.leverage}x")
        print(f"Fee Rate: {self.fee_rate * 100:.2f}%")
        print(f"Duration: {duration_seconds}s" if duration_seconds else "Duration: Infinite (Ctrl+C to stop)")
        print("=" * 60)
        print()

        # 타이머 태스크 (duration 지정 시)
        if duration_seconds:
            asyncio.create_task(self._stop_after(duration_seconds))

        # WebSocket 연결 및 데이터 수신
        await self._client.connect(
            on_orderbook=self._on_orderbook,
            on_trade=self._on_trade,
            on_error=self._on_error,
        )

        self._end_time = datetime.now()
        print(f"\n[TickForward] Test ended.")
        print(f"[TickForward] Ticks: {self._tick_count:,}, Candles: {self._candle_count:,}")
        print(f"[TickForward] Orders: {self._order_count}, Trades: {self._trade_count}")

    async def _stop_after(self, seconds: float) -> None:
        """지정 시간 후 중지"""
        await asyncio.sleep(seconds)
        if self._running:
            print(f"\n[TickForward] Duration reached ({seconds}s). Stopping...")
            await self.stop()

    async def stop(self) -> None:
        """테스트 중지"""
        self._running = False
        self._end_time = datetime.now()
        await self._client.disconnect()

    def _on_orderbook(self, snapshot: OrderbookSnapshot) -> None:
        """
        Orderbook 업데이트 처리

        틱 기반 러너에서는 Orderbook을 직접 사용하지 않지만,
        체결 판단을 위해 best bid/ask 정보를 유지합니다.
        """
        # 체결 판단용 호가 정보만 저장
        pass

    def _on_trade(self, trade: AggTrade) -> None:
        """
        체결 데이터 처리

        1. 틱으로 CandleBuilder 업데이트
        2. 캔들 완성 시 전략 실행
        3. 체결 확인
        """
        self._tick_count += 1
        self._last_trade_price = trade.price

        # 시작 시간 기록
        if self._start_time is None:
            self._start_time = trade.timestamp

        # 1. 체결 확인
        executed_trade = self._trader.on_price_update(
            price=trade.price,
            best_bid=trade.price,
            best_ask=trade.price,
            timestamp=trade.timestamp,
        )

        if executed_trade:
            self._trade_count += 1
            side_str = executed_trade.side.value
            pnl_str = f" PnL: ${executed_trade.pnl:+.2f}" if executed_trade.pnl != 0 else ""
            print(f"[TickForward] Trade: {side_str} @ ${executed_trade.price:,.2f}{pnl_str}")

        # 2. CandleBuilder 업데이트
        completed_candle = self._candle_builder.update(trade)

        # 3. 캔들 완성 시 전략 실행
        if completed_candle:
            self._candle_count += 1
            self._current_candle = completed_candle
            self._execute_strategy(completed_candle, trade.timestamp)

        # 4. 미실현 손익 업데이트
        self._trader.update_unrealized_pnl(trade.price)

    def _execute_strategy(self, candle: Candle, timestamp: datetime) -> None:
        """
        캔들 완성 시 전략 실행
        """
        # 포지션 정보
        position = self._trader.position

        # MarketState 생성 (캔들 정보 기반)
        market_state = MarketState(
            timestamp=timestamp,
            mid_price=candle.close,
            imbalance=candle.volume_imbalance,
            spread=0.0,
            spread_bps=0.0,
            best_bid=candle.close,
            best_ask=candle.close,
            best_bid_qty=candle.buy_volume,
            best_ask_qty=candle.sell_volume,
            position_side=position.side,
            position_qty=position.quantity,
            # OHLCV 필드
            open=candle.open,
            high=candle.high,
            low=candle.low,
            close=candle.close,
            volume=candle.volume,
            vwap=candle.vwap,
        )

        # 전략 실행
        order = self.strategy.generate_order(market_state)

        # 주문 제출 (중복 방지)
        if order is not None:
            pending_sides = [po.order.side for po in self._trader.pending_orders]
            if order.side not in pending_sides:
                self._order_count += 1
                self._trader.submit_order(order, timestamp=timestamp)

                # 로그 출력
                price_str = f"@ ${order.limit_price:,.2f}" if order.limit_price else "MARKET"
                print(f"[TickForward] Order: {order.side.value} {order.quantity:.4f} {price_str}")

    def _on_error(self, error: Exception) -> None:
        """에러 처리"""
        print(f"[TickForward] Error: {error}")

    def get_performance_report(self) -> PerformanceReport:
        """성과 리포트 반환"""
        return PerformanceCalculator.calculate(
            trades=self._trader.trades,
            initial_capital=self.initial_capital,
            strategy_name=self.strategy.__class__.__name__,
            symbol=self.symbol.upper(),
            start_time=self._start_time or datetime.now(),
            end_time=self._end_time or datetime.now(),
        )

    @property
    def trader(self) -> PaperTrader:
        """PaperTrader 인스턴스"""
        return self._trader

    @property
    def tick_count(self) -> int:
        """처리된 틱 수"""
        return self._tick_count

    @property
    def candle_count(self) -> int:
        """완성된 캔들 수"""
        return self._candle_count
