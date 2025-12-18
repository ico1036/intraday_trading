"""
Performance 모듈

전략 성과 지표를 계산하고 리포트를 생성합니다.
교육 목적으로 상세한 주석을 포함합니다.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import List

from .paper_trader import Trade


@dataclass
class PerformanceReport:
    """
    전략 성과 리포트
    
    교육 포인트:
        - 수익률만으로는 전략 평가 불가
        - 리스크 조정 수익률 (Sharpe)이 중요
        - 최대 낙폭(Drawdown)은 실제 운용 시 심리적 영향
    """
    
    # 기본 정보
    strategy_name: str
    symbol: str
    start_time: datetime
    end_time: datetime
    
    # 수익 지표
    initial_capital: float
    final_capital: float
    total_return: float  # 총 수익률 (%)
    
    # 거래 통계
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float  # 승률 (%)
    
    # 손익 분석
    profit_factor: float  # 총이익 / 총손실
    avg_win: float
    avg_loss: float
    
    # 리스크 지표
    max_drawdown: float  # 최대 낙폭 (%)
    sharpe_ratio: float  # 샤프 비율
    
    # 비용
    total_fees: float
    
    def print_summary(self) -> None:
        """콘솔에 성과 요약 출력"""
        print("=" * 50)
        print(f"전략: {self.strategy_name} | 심볼: {self.symbol}")
        print(f"기간: {self.start_time} ~ {self.end_time}")
        print("-" * 50)
        print(f"초기 자본: ${self.initial_capital:,.2f}")
        print(f"최종 자본: ${self.final_capital:,.2f}")
        print(f"총 수익률: {self.total_return:+.2f}%")
        print("-" * 50)
        print(f"총 거래: {self.total_trades}")
        print(f"승: {self.winning_trades} / 패: {self.losing_trades}")
        print(f"승률: {self.win_rate:.1f}%")
        print(f"Profit Factor: {self.profit_factor:.2f}")
        print(f"평균 이익: ${self.avg_win:.2f}")
        print(f"평균 손실: ${self.avg_loss:.2f}")
        print("-" * 50)
        print(f"최대 낙폭: {self.max_drawdown:.2f}%")
        print(f"샤프 비율: {self.sharpe_ratio:.2f}")
        print(f"총 수수료: ${self.total_fees:.2f}")
        print("=" * 50)


class PerformanceCalculator:
    """
    성과 지표 계산기
    
    거래 내역을 분석하여 다양한 성과 지표를 계산합니다.
    
    교육 포인트:
        - 지표는 과거 성과만 보여줌 (미래 보장 X)
        - 다양한 시장 상황에서 검증 필요
        - 통계적으로 유의미한 거래 수 필요 (최소 30회 이상)
    """
    
    @staticmethod
    def calculate(
        trades: List[Trade],
        initial_capital: float,
        strategy_name: str,
        symbol: str,
        start_time: datetime,
        end_time: datetime,
    ) -> PerformanceReport:
        """
        거래 내역으로부터 성과 리포트 생성
        
        Args:
            trades: 거래 내역 리스트
            initial_capital: 초기 자본금
            strategy_name: 전략 이름
            symbol: 거래 심볼
            start_time: 시작 시간
            end_time: 종료 시간
            
        Returns:
            PerformanceReport: 계산된 성과 리포트
        """
        # 빈 거래 처리
        if not trades:
            return PerformanceReport(
                strategy_name=strategy_name,
                symbol=symbol,
                start_time=start_time,
                end_time=end_time,
                initial_capital=initial_capital,
                final_capital=initial_capital,
                total_return=0.0,
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate=0.0,
                profit_factor=0.0,
                avg_win=0.0,
                avg_loss=0.0,
                max_drawdown=0.0,
                sharpe_ratio=0.0,
                total_fees=0.0,
            )
        
        # 기본 통계 계산
        total_trades = len(trades)
        total_fees = sum(t.fee for t in trades)
        
        # 손익 거래 분리 (pnl != 0인 거래만 집계)
        pnl_trades = [t for t in trades if t.pnl != 0]
        winning = [t for t in pnl_trades if t.pnl > 0]
        losing = [t for t in pnl_trades if t.pnl < 0]
        
        winning_trades = len(winning)
        losing_trades = len(losing)
        
        # 승률 계산
        total_pnl_trades = winning_trades + losing_trades
        win_rate = (winning_trades / total_pnl_trades * 100) if total_pnl_trades > 0 else 0.0
        
        # 이익/손실 합계
        total_profit = sum(t.pnl for t in winning)
        total_loss = abs(sum(t.pnl for t in losing))
        
        # Profit Factor
        profit_factor = (total_profit / total_loss) if total_loss > 0 else float("inf") if total_profit > 0 else 0.0
        
        # 평균 이익/손실
        avg_win = (total_profit / winning_trades) if winning_trades > 0 else 0.0
        avg_loss = (total_loss / losing_trades) if losing_trades > 0 else 0.0
        
        # 최종 자본 및 수익률
        total_pnl = sum(t.pnl for t in trades)
        final_capital = initial_capital + total_pnl
        total_return = ((final_capital - initial_capital) / initial_capital * 100) if initial_capital > 0 else 0.0
        
        # 최대 낙폭 계산
        max_drawdown = PerformanceCalculator._calculate_max_drawdown(trades, initial_capital)
        
        # 샤프 비율 계산 (단순화: 일일 수익률 기준)
        sharpe_ratio = PerformanceCalculator._calculate_sharpe_ratio(trades, initial_capital)
        
        return PerformanceReport(
            strategy_name=strategy_name,
            symbol=symbol,
            start_time=start_time,
            end_time=end_time,
            initial_capital=initial_capital,
            final_capital=final_capital,
            total_return=total_return,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            profit_factor=profit_factor,
            avg_win=avg_win,
            avg_loss=avg_loss,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe_ratio,
            total_fees=total_fees,
        )
    
    @staticmethod
    def _calculate_max_drawdown(trades: List[Trade], initial_capital: float) -> float:
        """
        최대 낙폭 계산
        
        Args:
            trades: 거래 내역
            initial_capital: 초기 자본
            
        Returns:
            최대 낙폭 (%)
        
        교육 포인트:
            - 낙폭 = (고점 - 현재) / 고점
            - 최대 낙폭은 투자 기간 중 가장 큰 하락 폭
            - 10% 이상이면 심리적으로 유지하기 어려움
        """
        if not trades:
            return 0.0
        
        # 누적 자본 추적
        capital = initial_capital
        peak = initial_capital
        max_dd = 0.0
        
        for trade in trades:
            capital += trade.pnl
            if capital > peak:
                peak = capital
            
            if peak > 0:
                drawdown = (peak - capital) / peak * 100
                max_dd = max(max_dd, drawdown)
        
        return max_dd
    
    @staticmethod
    def _calculate_sharpe_ratio(trades: List[Trade], initial_capital: float) -> float:
        """
        샤프 비율 계산 (단순화된 버전)
        
        Args:
            trades: 거래 내역
            initial_capital: 초기 자본
            
        Returns:
            샤프 비율
        
        교육 포인트:
            - 샤프 비율 = (평균 수익률 - 무위험 수익률) / 수익률 표준편차
            - 무위험 수익률은 0으로 가정 (단순화)
            - 1.0 이상이면 양호, 2.0 이상이면 우수
        """
        pnl_values = [t.pnl for t in trades if t.pnl != 0]
        
        if len(pnl_values) < 2:
            return 0.0
        
        import statistics
        
        try:
            mean_pnl = statistics.mean(pnl_values)
            std_pnl = statistics.stdev(pnl_values)
            
            if std_pnl == 0:
                return 0.0
            
            # 연환산하지 않은 단순 샤프
            sharpe = mean_pnl / std_pnl
            return sharpe
        except statistics.StatisticsError:
            return 0.0

