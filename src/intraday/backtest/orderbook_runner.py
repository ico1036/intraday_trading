"""
Orderbook 기반 백테스트 러너

히스토리컬 오더북 스냅샷을 사용하여 전략을 백테스트합니다.

교육 포인트:
    - ForwardRunner와 동일한 로직, 데이터 소스만 다름
    - Strategy, PaperTrader, OrderbookProcessor 모두 재사용
    - OBI 전략 등 오더북 불균형 기반 전략에 적합
"""

from datetime import datetime
from typing import Optional

from ..client import OrderbookSnapshot
from ..data.loader import OrderbookDataLoader
from ..orderbook import OrderbookProcessor
from ..paper_trader import PaperTrader, Trade
from ..performance import PerformanceReport, PerformanceCalculator
from ..strategy import Strategy, MarketState, Side


class OrderbookBacktestRunner:
    """
    오더북 기반 백테스터
    
    사용 예시:
        loader = OrderbookDataLoader(Path("./data/orderbook"))
        strategy = OBIStrategy(buy_threshold=0.3)
        
        runner = OrderbookBacktestRunner(
            strategy=strategy,
            data_loader=loader,
            initial_capital=10000.0,
        )
        
        report = runner.run()
        report.print_summary()
    
    교육 포인트:
        - ForwardRunner._on_orderbook()와 동일한 로직
        - 차이점: WebSocket 대신 파일에서 읽음
        - 장점: 과거 데이터로 전략 검증 가능
    """
    
    def __init__(
        self,
        strategy: Strategy,
        data_loader: OrderbookDataLoader,
        initial_capital: float = 10000.0,
        fee_rate: float = 0.001,
        symbol: str = "BTCUSDT",
    ):
        """
        Args:
            strategy: 실행할 전략 (Strategy Protocol 구현체)
            data_loader: 오더북 데이터 로더
            initial_capital: 초기 자본금 (USD)
            fee_rate: 수수료율 (기본 0.1%)
            symbol: 거래쌍 (리포트용)
        
        교육 포인트:
            - 전략은 Protocol로 정의되어 있어 교체가 용이
            - ForwardRunner에서 사용하던 전략을 그대로 사용
        """
        self.strategy = strategy
        self.data_loader = data_loader
        self.initial_capital = initial_capital
        self.fee_rate = fee_rate
        self.symbol = symbol
        
        # 내부 컴포넌트 (ForwardRunner와 동일)
        self._processor = OrderbookProcessor(max_history=1000)
        self._trader = PaperTrader(initial_capital, fee_rate)
        
        # 상태
        self._start_time: Optional[datetime] = None
        self._end_time: Optional[datetime] = None
        self._last_trade_price: float = 0.0
        
        # 통계
        self._snapshot_count = 0
        self._order_count = 0
        self._trade_count = 0
    
    def run(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        progress_interval: int = 10000,
    ) -> PerformanceReport:
        """
        백테스트 실행
        
        Args:
            start_time: 시작 시간 (None이면 처음부터)
            end_time: 종료 시간 (None이면 끝까지)
            progress_interval: 진행 상황 출력 간격 (스냅샷 수)
            
        Returns:
            성과 리포트
            
        교육 포인트:
            - 각 스냅샷마다 전략 실행
            - ForwardRunner와 달리 모든 데이터를 즉시 처리
            - 실시간보다 빠르게 백테스트 가능
        """
        print(f"[Backtest] Starting orderbook backtest...")
        print(f"[Backtest] Strategy: {self.strategy.__class__.__name__}")
        print(f"[Backtest] Initial Capital: ${self.initial_capital:,.2f}")
        
        self._snapshot_count = 0
        self._order_count = 0
        self._trade_count = 0
        
        # 데이터 순회
        for snapshot in self.data_loader.iter_snapshots(start_time, end_time):
            self._process_snapshot(snapshot)
            
            # 시작/종료 시간 기록
            if self._start_time is None:
                self._start_time = snapshot.timestamp
            self._end_time = snapshot.timestamp
            
            # 진행 상황 출력
            if self._snapshot_count % progress_interval == 0:
                self._print_progress()
        
        print(f"\n[Backtest] Completed!")
        print(f"[Backtest] Snapshots: {self._snapshot_count:,}, Orders: {self._order_count:,}, Trades: {self._trade_count:,}")
        
        return self.get_performance_report()
    
    def _process_snapshot(self, snapshot: OrderbookSnapshot) -> None:
        """
        단일 스냅샷 처리
        
        ForwardRunner._on_orderbook()와 거의 동일한 로직입니다.
        
        교육 포인트:
            1. Orderbook → OrderbookState로 변환
            2. OrderbookState → MarketState로 변환
            3. Strategy에 MarketState 전달하여 주문 생성
            4. 생성된 주문을 PaperTrader에 제출
            5. 가격 업데이트로 체결 확인
        """
        self._snapshot_count += 1
        
        # 1. Orderbook 처리
        ob_state = self._processor.update(snapshot)
        
        # 2. 호가 정보 추출
        best_bid = ob_state.best_bid[0]
        best_ask = ob_state.best_ask[0]
        mid_price = ob_state.mid_price
        
        # 3. 체결 확인 (mid_price를 시장가로 사용)
        executed_trade = self._trader.on_price_update(
            price=mid_price,
            best_bid=best_bid,
            best_ask=best_ask,
            timestamp=snapshot.timestamp,
        )
        
        if executed_trade:
            self._trade_count += 1
            self._last_trade_price = executed_trade.price
        
        # 4. MarketState 생성 (포지션 정보 포함)
        position = self._trader.position
        market_state = MarketState(
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
        
        # 5. 전략 실행
        order = self.strategy.generate_order(market_state)
        
        # 6. 주문 제출 (중복 방지)
        if order is not None:
            pending_sides = [po.order.side for po in self._trader.pending_orders]
            if order.side not in pending_sides:
                self._order_count += 1
                self._trader.submit_order(order)
        
        # 7. 미실현 손익 업데이트
        self._trader.update_unrealized_pnl(mid_price)
    
    def _print_progress(self) -> None:
        """진행 상황 출력"""
        position = self._trader.position
        position_str = "None"
        if position.side:
            position_str = f"{position.side.value} {position.quantity:.4f}"
        
        print(
            f"[Backtest] Progress: {self._snapshot_count:,} snapshots | "
            f"Orders: {self._order_count} | Trades: {self._trade_count} | "
            f"Position: {position_str} | PnL: ${self._trader.total_pnl:+.2f}"
        )
    
    def get_performance_report(self) -> PerformanceReport:
        """
        성과 리포트 반환
        
        교육 포인트:
            - ForwardRunner.get_performance_report()와 동일
            - PerformanceCalculator 재사용
        """
        return PerformanceCalculator.calculate(
            trades=self._trader.trades,
            initial_capital=self.initial_capital,
            strategy_name=self.strategy.__class__.__name__,
            symbol=self.symbol,
            start_time=self._start_time or datetime.now(),
            end_time=self._end_time or datetime.now(),
        )
    
    @property
    def trader(self) -> PaperTrader:
        """PaperTrader 인스턴스 (디버깅/모니터링용)"""
        return self._trader
    
    @property
    def snapshot_count(self) -> int:
        """처리된 스냅샷 수"""
        return self._snapshot_count





