"""
ForwardRunner 모듈

포워드 테스트를 실행하는 오케스트레이터입니다.
교육 목적으로 상세한 주석을 포함합니다.
"""

import asyncio
from datetime import datetime
from typing import Optional, Protocol

from .client import BinanceCombinedClient, OrderbookSnapshot, AggTrade
from .orderbook import OrderbookProcessor
from .strategy import Strategy, MarketState
from .paper_trader import PaperTrader
from .performance import PerformanceReport, PerformanceCalculator


class ForwardRunner:
    """
    포워드 테스트 실행기
    
    실시간 시장 데이터를 받아 전략을 실행하고 가상 거래를 수행합니다.
    
    교육 포인트:
        - 포워드 테스트는 백테스트와 달리 실시간 데이터로 테스트
        - 실제 거래 없이 전략의 성능을 평가할 수 있음
        - 백테스트에서 놓친 문제점(슬리피지, 레이턴시 등)을 발견
    
    사용 예시:
        strategy = OBIStrategy(buy_threshold=0.3)
        runner = ForwardRunner(strategy, symbol="btcusdt")
        await runner.run(duration_seconds=3600)  # 1시간 실행
        report = runner.get_performance_report()
        report.print_summary()
    """
    
    def __init__(
        self,
        strategy: Strategy,
        symbol: str = "btcusdt",
        initial_capital: float = 10000.0,
        fee_rate: float = 0.001,
    ):
        """
        Args:
            strategy: 실행할 전략 (Strategy Protocol 구현체)
            symbol: 거래쌍 (예: btcusdt)
            initial_capital: 초기 자본금 (USD)
            fee_rate: 수수료율 (기본 0.1%)
        
        교육 포인트:
            - 전략은 Protocol로 정의되어 있어 교체가 용이
            - 동일한 Runner로 다양한 전략을 테스트 가능
        
        Note:
            슬리피지 버퍼는 실제 거래소에서 필요하지만,
            시뮬레이터에서는 레이턴시가 없으므로 불필요함.
            실제 거래 시 별도로 적용 필요.
        """
        self.strategy = strategy
        self.symbol = symbol
        self.initial_capital = initial_capital
        self.fee_rate = fee_rate
        
        # 내부 컴포넌트
        self._client = BinanceCombinedClient(symbol)
        self._processor = OrderbookProcessor(max_history=1000)
        self._trader = PaperTrader(initial_capital, fee_rate)
        
        # 상태
        self._running = False
        self._start_time: Optional[datetime] = None
        self._end_time: Optional[datetime] = None
        self._last_orderbook: Optional[OrderbookSnapshot] = None
        self._current_market_state: Optional[MarketState] = None
        self._last_trade_price: float = 0.0  # 마지막 체결가
        
        # OB 기준 스냅샷용 버퍼
        # Trade 데이터를 모아뒀다가 다음 Orderbook 도착 시 일괄 처리
        self._trade_buffer: list[AggTrade] = []
        
        # 성능 측정용
        self._orderbook_count = 0
        self._trade_count = 0
        self._order_count = 0
    
    @property
    def is_running(self) -> bool:
        """실행 중 여부"""
        return self._running
    
    @property
    def market_state(self) -> Optional[MarketState]:
        """현재 시장 상태"""
        return self._current_market_state
    
    @property
    def last_trade_price(self) -> float:
        """마지막 체결가 (aggTrade에서)"""
        return self._last_trade_price
    
    async def run(self, duration_seconds: Optional[float] = None) -> None:
        """
        포워드 테스트 실행
        
        Args:
            duration_seconds: 실행 시간 (초). None이면 stop()까지 실행
        
        교육 포인트:
            - WebSocket으로 실시간 데이터 수신
            - Orderbook 업데이트마다 전략 실행
            - 체결 데이터로 LIMIT 주문 체결 판단
        """
        self._running = True
        self._start_time = datetime.now()
        
        print(f"[Runner] Starting forward test for {self.symbol.upper()}...")
        print(f"[Runner] Strategy: {self.strategy.__class__.__name__}")
        print(f"[Runner] Initial Capital: ${self.initial_capital:,.2f}")
        
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
        print(f"[Runner] Forward test ended.")
        print(f"[Runner] Orderbooks: {self._orderbook_count}, Trades: {self._trade_count}, Orders: {self._order_count}")
    
    async def _stop_after(self, seconds: float) -> None:
        """지정 시간 후 중지"""
        await asyncio.sleep(seconds)
        if self._running:
            print(f"[Runner] Duration reached ({seconds}s). Stopping...")
            await self.stop()
    
    async def stop(self) -> None:
        """테스트 중지"""
        self._running = False
        self._end_time = datetime.now()
        await self._client.disconnect()
    
    def _on_orderbook(self, snapshot: OrderbookSnapshot) -> None:
        """
        Orderbook 업데이트 처리 (OB 기준 스냅샷 방식)
        
        교육 포인트:
            1. 버퍼에 쌓인 Trade 데이터를 현재 Orderbook 기준으로 일괄 처리
            2. Orderbook → OrderbookState로 변환
            3. OrderbookState → MarketState로 변환
            4. Strategy에 MarketState 전달하여 주문 생성
            5. 생성된 주문을 PaperTrader에 제출
        
        OB 기준 스냅샷 방식:
            - Trade 데이터가 도착하면 버퍼에 저장만 함
            - Orderbook 도착 시 버퍼의 Trade를 최신 Orderbook 기준으로 처리
            - 이렇게 하면 오래된 Orderbook으로 체결 판단하는 문제 해결
        """
        self._orderbook_count += 1
        self._last_orderbook = snapshot
        
        # 1. Orderbook 처리
        ob_state = self._processor.update(snapshot)
        
        # 2. 버퍼에 쌓인 Trade 일괄 처리 (최신 Orderbook 기준)
        best_bid = ob_state.best_bid[0]
        best_ask = ob_state.best_ask[0]
        
        for trade in self._trade_buffer:
            executed_trade = self._trader.on_price_update(
                price=trade.price,
                best_bid=best_bid,
                best_ask=best_ask,
                timestamp=trade.timestamp,
            )
            
            if executed_trade:
                side_str = executed_trade.side.value
                pnl_str = f" PnL: ${executed_trade.pnl:+.2f}" if executed_trade.pnl != 0 else ""
                print(f"[Runner] Trade Executed: {side_str} @ ${executed_trade.price:,.2f}{pnl_str}")
        
        # 버퍼 비우기
        self._trade_buffer.clear()
        
        # 3. MarketState 생성 (포지션 정보 포함)
        position = self._trader.position
        self._current_market_state = MarketState(
            timestamp=ob_state.timestamp,
            mid_price=ob_state.mid_price,
            imbalance=ob_state.imbalance,
            spread=ob_state.spread,
            spread_bps=ob_state.spread_bps,
            best_bid=best_bid,
            best_ask=best_ask,
            best_bid_qty=ob_state.best_bid[1],
            best_ask_qty=ob_state.best_ask[1],
            position_side=position.side,
            position_qty=position.quantity,
        )
        
        # 4. 전략 실행
        order = self.strategy.generate_order(self._current_market_state)
        
        # 5. 주문 제출 (중복 방지)
        if order is not None:
            # pending orders에 같은 방향 주문이 있으면 제출 안 함
            pending_sides = [po.order.side for po in self._trader.pending_orders]
            if order.side in pending_sides:
                return  # 이미 같은 방향 주문 대기 중
            
            self._order_count += 1
            order_id = self._trader.submit_order(order)
            
            # 로그 출력
            print(f"[Runner] Order Submitted: {order.side.value} {order.quantity:.4f} @ ${order.limit_price:,.2f}")
    
    def _on_trade(self, trade: AggTrade) -> None:
        """
        체결 데이터 처리 (OB 기준 스냅샷 방식)
        
        교육 포인트:
            - Trade 데이터는 버퍼에 저장만 함
            - 실제 체결 판단은 다음 Orderbook 도착 시 수행
            - 이렇게 하면 최신 Orderbook 기준으로 체결 판단 가능
        
        OB 기준 스냅샷 방식:
            ┌─────────────────────────────────────────┐
            │  Trade 도착 → 📦 버퍼에 보관             │
            │  Orderbook 도착 → 📦 버퍼 열어서 처리    │
            └─────────────────────────────────────────┘
        """
        self._trade_count += 1
        self._last_trade_price = trade.price  # 마지막 체결가 업데이트
        
        # 첫 OB 도착 전 Trade는 무시 (기준 호가창이 없으므로)
        if self._last_orderbook is None:
            return
        
        # 버퍼에 저장만 (처리는 _on_orderbook에서)
        self._trade_buffer.append(trade)
        
        # 미실현 손익 업데이트 (실시간 모니터링용)
        self._trader.update_unrealized_pnl(trade.price)
    
    def _on_error(self, error: Exception) -> None:
        """에러 처리"""
        print(f"[Runner] Error: {error}")
    
    def get_performance_report(self) -> PerformanceReport:
        """
        성과 리포트 반환
        
        교육 포인트:
            - 포워드 테스트 종료 후 성과 분석
            - 승률, 수익률, 최대 낙폭 등 핵심 지표 확인
        """
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
        """PaperTrader 인스턴스 (디버깅/모니터링용)"""
        return self._trader

