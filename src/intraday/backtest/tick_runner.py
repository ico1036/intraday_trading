"""
Tick 기반 백테스트 러너

히스토리컬 틱 데이터를 사용하여 전략을 백테스트합니다.
볼륨바, 틱바, 시간바, 달러바 등 다양한 샘플링 방식을 지원합니다.

교육 포인트:
    - 틱 데이터: 개별 체결 기록
    - 볼륨바: 일정 거래량마다 캔들 생성 (불규칙 시간)
    - 틱바: 일정 체결 횟수마다 캔들 생성
    - 시간바: 일정 시간마다 캔들 생성 (전통적 방식)
    - 달러바: 일정 거래대금마다 캔들 생성
"""

from datetime import datetime
from typing import Optional

from ..client import AggTrade
from ..candle_builder import CandleBuilder, CandleType, Candle
from ..data.loader import TickDataLoader
from ..paper_trader import PaperTrader
from ..performance import PerformanceReport, PerformanceCalculator, EquityPoint, ReportSaver
from ..strategy import Strategy, MarketState, Side


# 하위 호환성을 위한 alias
BarType = CandleType
Bar = Candle


class TickBacktestRunner:
    """
    틱 기반 백테스터
    
    사용 예시:
        loader = TickDataLoader(Path("./data/ticks"))
        strategy = VolumeImbalanceStrategy()
        
        runner = TickBacktestRunner(
            strategy=strategy,
            data_loader=loader,
            bar_type=CandleType.VOLUME,
            bar_size=1.0,  # 1 BTC마다 바 생성
        )
        
        report = runner.run()
        report.print_summary()
    
    교육 포인트:
        - 볼륨바는 시장 활동에 따라 바 생성 빈도가 달라짐
        - 변동성 높은 시장에서 더 많은 바 → 더 빠른 반응
        - 틱바/볼륨바는 시간바보다 정보 효율이 높다는 연구 결과
    """
    
    def __init__(
        self,
        strategy: Strategy,
        data_loader: TickDataLoader,
        bar_type: CandleType = CandleType.VOLUME,
        bar_size: float = 1.0,
        initial_capital: float = 10000.0,
        fee_rate: float = 0.001,
        symbol: str = "BTCUSDT",
        latency_ms: float = 50.0,
    ):
        """
        Args:
            strategy: 실행할 전략 (Strategy Protocol 구현체)
            data_loader: 틱 데이터 로더
            bar_type: 바 타입 (VOLUME, TICK, TIME, DOLLAR)
            bar_size: 바 크기 (거래량, 틱 수, 초, 또는 달러)
            initial_capital: 초기 자본금 (USD)
            fee_rate: 수수료율 (기본 0.1%)
            symbol: 거래쌍 (리포트용)
            latency_ms: 주문 전송 지연 시간 (밀리초, 기본 50ms)
                        주문 제출 후 이 시간이 지나야 체결 시도.
                        현실적인 네트워크 지연 시뮬레이션에 사용.
        
        교육 포인트:
            - VOLUME 바: bar_size = 1.0 → 1 BTC 거래마다 바 생성
            - TICK 바: bar_size = 100 → 100틱마다 바 생성
            - TIME 바: bar_size = 60 → 60초마다 바 생성
            - DOLLAR 바: bar_size = 1000000 → 100만 달러마다 바 생성
            - latency_ms: 50ms = Binance API 평균 RTT 기준
        """
        self.strategy = strategy
        self.data_loader = data_loader
        self.bar_type = bar_type
        self.bar_size = bar_size
        self.initial_capital = initial_capital
        self.fee_rate = fee_rate
        self.symbol = symbol
        self.latency_ms = latency_ms
        
        # CandleBuilder 사용 (중복 제거)
        self._candle_builder = CandleBuilder(bar_type, bar_size)
        self._trader = PaperTrader(initial_capital, fee_rate)
        
        # 상태
        self._start_time: Optional[datetime] = None
        self._end_time: Optional[datetime] = None
        self._current_candle: Optional[Candle] = None
        self._last_trade_price: float = 0.0
        
        # 통계
        self._tick_count = 0
        self._bar_count = 0
        self._order_count = 0
        self._trade_count = 0

        # Equity curve 추적
        self._equity_curve: list[EquityPoint] = []
        self._peak_equity = initial_capital
    
    def run(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        progress_interval: int = 100000,
    ) -> PerformanceReport:
        """
        백테스트 실행
        
        Args:
            start_time: 시작 시간 (None이면 처음부터)
            end_time: 종료 시간 (None이면 끝까지)
            progress_interval: 진행 상황 출력 간격 (틱 수)
            
        Returns:
            성과 리포트
        """
        print(f"[Backtest] Starting tick backtest...")
        print(f"[Backtest] Strategy: {self.strategy.__class__.__name__}")
        print(f"[Backtest] Bar Type: {self.bar_type.value}, Size: {self.bar_size}")
        print(f"[Backtest] Initial Capital: ${self.initial_capital:,.2f}")
        print(f"[Backtest] Latency: {self.latency_ms:.1f}ms")
        
        # 상태 초기화
        self._candle_builder._reset()
        self._tick_count = 0
        self._bar_count = 0
        self._order_count = 0
        self._trade_count = 0
        self._equity_curve = []
        self._peak_equity = self.initial_capital
        
        # 틱 순회
        for trade in self.data_loader.iter_trades(start_time, end_time):
            self._process_tick(trade)
            
            # 시작/종료 시간 기록
            if self._start_time is None:
                self._start_time = trade.timestamp
            self._end_time = trade.timestamp
            
            # 진행 상황 출력
            if self._tick_count % progress_interval == 0:
                self._print_progress()
        
        print(f"\n[Backtest] Completed!")
        print(f"[Backtest] Ticks: {self._tick_count:,}, Bars: {self._bar_count:,}")
        print(f"[Backtest] Orders: {self._order_count}, Trades: {self._trade_count}")
        
        return self.get_performance_report()
    
    def _process_tick(self, trade: AggTrade) -> None:
        """
        단일 틱 처리
        
        교육 포인트:
            1. 틱으로 CandleBuilder 업데이트
            2. 캔들 완성 시 전략 실행
            3. 체결 확인 (latency 고려)
        """
        self._tick_count += 1
        self._last_trade_price = trade.price
        
        # 1. 체결 확인 (각 틱마다, latency 고려)
        executed_trade = self._trader.on_price_update(
            price=trade.price,
            best_bid=trade.price,
            best_ask=trade.price,
            timestamp=trade.timestamp,
            latency_ms=self.latency_ms,
        )
        
        if executed_trade:
            self._trade_count += 1
            # Equity curve 기록
            self._record_equity_point(trade.timestamp)
        
        # 2. CandleBuilder 업데이트 (스트리밍 모드)
        completed_candle = self._candle_builder.update(trade)
        
        # 3. 캔들 완성 시 전략 실행
        if completed_candle:
            self._bar_count += 1
            self._current_candle = completed_candle
            self._execute_strategy_on_candle(completed_candle, trade.timestamp)
        
        # 4. 미실현 손익 업데이트
        self._trader.update_unrealized_pnl(trade.price)
    
    def _execute_strategy_on_candle(self, candle: Candle, timestamp: datetime) -> None:
        """
        캔들 완성 시 전략 실행
        
        교육 포인트:
            - 캔들 정보를 MarketState로 변환
            - 틱 기반에서는 스프레드 정보가 없으므로 0으로 설정
            - imbalance는 볼륨 불균형으로 대체
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
            # OHLCV 필드 추가
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
                # 백테스트 시간 사용 (latency 시뮬레이션을 위해)
                self._trader.submit_order(order, timestamp=timestamp)
    
    def _print_progress(self) -> None:
        """진행 상황 출력"""
        position = self._trader.position
        position_str = "None"
        if position.side:
            position_str = f"{position.side.value} {position.quantity:.4f}"
        
        print(
            f"[Backtest] Progress: {self._tick_count:,} ticks, {self._bar_count:,} bars | "
            f"Orders: {self._order_count} | Trades: {self._trade_count} | "
            f"Position: {position_str} | PnL: ${self._trader.total_pnl:+.2f}"
        )
    
    def get_performance_report(self) -> PerformanceReport:
        """성과 리포트 반환"""
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
        """PaperTrader 인스턴스"""
        return self._trader
    
    @property
    def tick_count(self) -> int:
        """처리된 틱 수"""
        return self._tick_count
    
    @property
    def bar_count(self) -> int:
        """생성된 바 수"""
        return self._bar_count
    
    @property
    def current_bar(self) -> Optional[Candle]:
        """마지막으로 완성된 바"""
        return self._current_candle
    
    @property
    def current_candle(self) -> Optional[Candle]:
        """마지막으로 완성된 캔들 (current_bar의 alias)"""
        return self._current_candle

    @property
    def equity_curve(self) -> list[EquityPoint]:
        """Equity curve 데이터"""
        return self._equity_curve.copy()

    def _record_equity_point(self, timestamp: datetime) -> None:
        """Equity curve에 현재 상태 기록"""
        # 현재 equity 계산 (실현 손익 기준)
        equity = self.initial_capital + self._trader.realized_pnl

        # Peak 업데이트 및 drawdown 계산
        if equity > self._peak_equity:
            self._peak_equity = equity

        drawdown = 0.0
        if self._peak_equity > 0:
            drawdown = (self._peak_equity - equity) / self._peak_equity * 100

        # 누적 PnL 및 수익률
        cumulative_pnl = equity - self.initial_capital
        cumulative_return_pct = cumulative_pnl / self.initial_capital * 100 if self.initial_capital > 0 else 0.0

        self._equity_curve.append(EquityPoint(
            timestamp=timestamp,
            equity=equity,
            drawdown=drawdown,
            cumulative_pnl=cumulative_pnl,
            cumulative_return_pct=cumulative_return_pct,
        ))

    def save_report(self, output_dir: str = "./reports") -> str:
        """
        백테스트 결과를 파일로 저장

        Args:
            output_dir: 저장 디렉토리

        Returns:
            리포트 디렉토리 경로
        """
        report = self.get_performance_report()
        saver = ReportSaver(
            report=report,
            trades=self._trader.trades,
            equity_curve=self._equity_curve,
            output_dir=output_dir,
        )
        return str(saver.save_all())
