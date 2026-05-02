"""
Pair Trading 백테스트 러너

두 코인 간의 스프레드 트레이딩을 백테스트합니다.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from ..strategies.multi.pair import PairTradingStrategy, SpreadCalculator
from ..backtest.metrics import sharpe_daily_annualized


@dataclass
class PairTradeLog:
    """거래 로그"""
    entry_time: datetime
    exit_time: Optional[datetime] = None
    direction: str = ""  # "LONG_SPREAD" or "SHORT_SPREAD"
    entry_zscore: float = 0.0
    exit_zscore: Optional[float] = None
    entry_price_a: float = 0.0
    entry_price_b: float = 0.0
    exit_price_a: Optional[float] = None
    exit_price_b: Optional[float] = None
    pnl: float = 0.0


@dataclass
class PairBacktestResult:
    """Pair Trading 백테스트 결과"""
    initial_capital: float
    final_capital: float
    total_return: float
    sharpe_ratio: float
    max_drawdown: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    avg_trade_duration: float  # 평균 거래 기간 (분)
    equity_curve: pd.Series
    trade_log: list[PairTradeLog]
    
    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.winning_trades / self.total_trades
    
    def summary(self) -> str:
        return f"""
=== Pair Trading Backtest Result ===
Initial Capital: ${self.initial_capital:,.2f}
Final Capital:   ${self.final_capital:,.2f}
Total Return:    {self.total_return * 100:.2f}%
Sharpe Ratio:    {self.sharpe_ratio:.2f}
Max Drawdown:    {self.max_drawdown * 100:.2f}%
Total Trades:    {self.total_trades}
Win Rate:        {self.win_rate * 100:.1f}%
Avg Duration:    {self.avg_trade_duration:.1f} min
"""


class PairBacktestRunner:
    """
    Pair Trading 백테스트 러너
    """
    
    def __init__(
        self,
        strategy: PairTradingStrategy,
        initial_capital: float = 10000,
        position_size_pct: float = 0.5,  # 각 leg에 25%씩 = 총 50%
        fee_rate: float = 0.001,
    ):
        self.strategy = strategy
        self.initial_capital = initial_capital
        self.position_size_pct = position_size_pct
        self.fee_rate = fee_rate
        
        self.data_a: Optional[pd.DataFrame] = None
        self.data_b: Optional[pd.DataFrame] = None
    
    def load_data(
        self,
        data_a: pd.DataFrame,
        data_b: pd.DataFrame,
    ) -> None:
        """
        데이터 로드
        
        Args:
            data_a: 코인 A 데이터 (timestamp, price 컬럼)
            data_b: 코인 B 데이터
        """
        self.data_a = data_a.copy()
        self.data_b = data_b.copy()
        
        # timestamp를 인덱스로
        if "timestamp" in self.data_a.columns:
            self.data_a = self.data_a.set_index("timestamp")
        if "timestamp" in self.data_b.columns:
            self.data_b = self.data_b.set_index("timestamp")
    
    def run(self) -> PairBacktestResult:
        """백테스트 실행"""
        if self.data_a is None or self.data_b is None:
            raise ValueError("Data not loaded")
        
        # 시간 동기화
        common_idx = self.data_a.index.intersection(self.data_b.index)
        price_a = self.data_a.loc[common_idx, "price"]
        price_b = self.data_b.loc[common_idx, "price"]
        
        # Z-score 계산
        zscore = self.strategy.calculate_spread_zscore(price_a, price_b)
        
        # 시뮬레이션
        capital = self.initial_capital
        position = None
        trade_log: list[PairTradeLog] = []
        current_trade: Optional[PairTradeLog] = None
        equity_curve = []
        
        position_value = 0.0
        entry_price_a = 0.0
        entry_price_b = 0.0
        quantity_a = 0.0
        quantity_b = 0.0
        
        for ts in common_idx:
            z = zscore.loc[ts]
            p_a = price_a.loc[ts]
            p_b = price_b.loc[ts]
            
            if pd.isna(z):
                equity_curve.append(capital)
                continue
            
            signal = self.strategy.generate_signal(z, position)
            
            if signal in ("LONG_SPREAD", "SHORT_SPREAD") and position is None:
                # 진입
                position_value = capital * self.position_size_pct
                leg_value = position_value / 2
                
                quantity_a = leg_value / p_a
                quantity_b = leg_value / p_b
                
                fee = position_value * self.fee_rate
                capital -= fee
                
                entry_price_a = p_a
                entry_price_b = p_b
                position = signal
                
                current_trade = PairTradeLog(
                    entry_time=ts,
                    direction=signal,
                    entry_zscore=z,
                    entry_price_a=p_a,
                    entry_price_b=p_b,
                )
            
            elif signal == "EXIT" and position is not None:
                # 청산
                if position == "LONG_SPREAD":
                    # A 롱 청산, B 숏 청산
                    pnl_a = (p_a - entry_price_a) * quantity_a
                    pnl_b = (entry_price_b - p_b) * quantity_b
                else:  # SHORT_SPREAD
                    # A 숏 청산, B 롱 청산
                    pnl_a = (entry_price_a - p_a) * quantity_a
                    pnl_b = (p_b - entry_price_b) * quantity_b
                
                total_pnl = pnl_a + pnl_b
                fee = abs(total_pnl) * self.fee_rate + position_value * self.fee_rate
                capital += total_pnl - fee
                
                if current_trade:
                    current_trade.exit_time = ts
                    current_trade.exit_zscore = z
                    current_trade.exit_price_a = p_a
                    current_trade.exit_price_b = p_b
                    current_trade.pnl = total_pnl - fee
                    trade_log.append(current_trade)
                
                position = None
                current_trade = None
            
            # 미실현 PnL 포함 에쿼티
            if position is not None:
                if position == "LONG_SPREAD":
                    unrealized = (p_a - entry_price_a) * quantity_a + (entry_price_b - p_b) * quantity_b
                else:
                    unrealized = (entry_price_a - p_a) * quantity_a + (p_b - entry_price_b) * quantity_b
                equity_curve.append(capital + unrealized)
            else:
                equity_curve.append(capital)
        
        # 결과 계산
        equity_series = pd.Series(equity_curve)
        total_return = (capital - self.initial_capital) / self.initial_capital
        sharpe = sharpe_daily_annualized(equity_series, timestamps=common_idx)
        
        rolling_max = equity_series.cummax()
        drawdown = (equity_series - rolling_max) / rolling_max
        max_drawdown = drawdown.min()
        
        winning = len([t for t in trade_log if t.pnl > 0])
        losing = len([t for t in trade_log if t.pnl < 0])
        
        # 평균 거래 기간
        durations = []
        for t in trade_log:
            if t.exit_time:
                dur = (t.exit_time - t.entry_time).total_seconds() / 60
                durations.append(dur)
        avg_duration = np.mean(durations) if durations else 0
        
        return PairBacktestResult(
            initial_capital=self.initial_capital,
            final_capital=capital,
            total_return=total_return,
            sharpe_ratio=sharpe,
            max_drawdown=max_drawdown,
            total_trades=len(trade_log),
            winning_trades=winning,
            losing_trades=losing,
            avg_trade_duration=avg_duration,
            equity_curve=equity_series,
            trade_log=trade_log,
        )
