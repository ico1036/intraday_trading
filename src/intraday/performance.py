"""
Performance 모듈

전략 성과 지표를 계산하고 리포트를 생성합니다.
교육 목적으로 상세한 주석을 포함합니다.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import pandas as pd

from .paper_trader import Trade


@dataclass
class EquityPoint:
    """Equity curve의 단일 포인트"""
    timestamp: datetime
    equity: float
    drawdown: float  # %
    cumulative_pnl: float
    cumulative_return_pct: float


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


class ReportSaver:
    """
    백테스트 결과 저장기

    Parquet 파일로 데이터를 저장하고 PNG 리포트를 생성합니다.

    저장 구조:
        reports/{strategy_name}_{timestamp}/
        ├── equity_curve.parquet    # 시계열: timestamp, equity, drawdown, pnl
        ├── trades.parquet          # 거래 내역
        ├── summary.parquet         # 요약 지표 (1행 테이블)
        └── report.png              # 시각화 리포트

    교육 포인트:
        - Parquet은 컬럼 기반으로 분석에 최적
        - 누적 수익률 그래프로 전략 특성 파악
        - 요약 지표로 빠른 성과 비교
    """

    def __init__(
        self,
        report: PerformanceReport,
        trades: List[Trade],
        equity_curve: List[EquityPoint],
        output_dir: str = "./reports",
    ):
        """
        Args:
            report: 성과 리포트
            trades: 거래 내역
            equity_curve: Equity curve 데이터
            output_dir: 저장 디렉토리
        """
        self.report = report
        self.trades = trades
        self.equity_curve = equity_curve
        self.output_dir = Path(output_dir)

        # 리포트 디렉토리 생성
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.report_dir = self.output_dir / f"{report.strategy_name}_{timestamp}"
        self.report_dir.mkdir(parents=True, exist_ok=True)

    def save_all(self) -> Path:
        """
        모든 데이터 저장

        Returns:
            리포트 디렉토리 경로
        """
        self.save_equity_curve()
        self.save_trades()
        self.save_summary()
        self.save_report_png()

        print(f"[ReportSaver] 리포트 저장 완료: {self.report_dir}")
        return self.report_dir

    def save_equity_curve(self) -> Path:
        """Equity curve를 parquet으로 저장"""
        if not self.equity_curve:
            print("[ReportSaver] Warning: Empty equity curve")
            return self.report_dir / "equity_curve.parquet"

        df = pd.DataFrame([
            {
                "timestamp": ep.timestamp,
                "equity": ep.equity,
                "drawdown": ep.drawdown,
                "cumulative_pnl": ep.cumulative_pnl,
                "cumulative_return_pct": ep.cumulative_return_pct,
            }
            for ep in self.equity_curve
        ])

        filepath = self.report_dir / "equity_curve.parquet"
        df.to_parquet(filepath, index=False)
        return filepath

    def save_trades(self) -> Path:
        """거래 내역을 parquet으로 저장"""
        if not self.trades:
            print("[ReportSaver] Warning: Empty trades")
            return self.report_dir / "trades.parquet"

        df = pd.DataFrame([
            {
                "timestamp": t.timestamp,
                "side": t.side.value,
                "price": t.price,
                "quantity": t.quantity,
                "fee": t.fee,
                "pnl": t.pnl,
            }
            for t in self.trades
        ])

        filepath = self.report_dir / "trades.parquet"
        df.to_parquet(filepath, index=False)
        return filepath

    def save_summary(self) -> Path:
        """요약 지표를 parquet으로 저장"""
        df = pd.DataFrame([{
            "strategy_name": self.report.strategy_name,
            "symbol": self.report.symbol,
            "start_time": self.report.start_time,
            "end_time": self.report.end_time,
            "initial_capital": self.report.initial_capital,
            "final_capital": self.report.final_capital,
            "total_return_pct": self.report.total_return,
            "total_trades": self.report.total_trades,
            "winning_trades": self.report.winning_trades,
            "losing_trades": self.report.losing_trades,
            "win_rate_pct": self.report.win_rate,
            "profit_factor": self.report.profit_factor,
            "avg_win": self.report.avg_win,
            "avg_loss": self.report.avg_loss,
            "max_drawdown_pct": self.report.max_drawdown,
            "sharpe_ratio": self.report.sharpe_ratio,
            "total_fees": self.report.total_fees,
        }])

        filepath = self.report_dir / "summary.parquet"
        df.to_parquet(filepath, index=False)
        return filepath

    def save_report_png(self) -> Path:
        """PNG 리포트 생성"""
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates

        # 한글 폰트 설정 (macOS)
        plt.rcParams['font.family'] = ['Arial Unicode MS', 'sans-serif']
        plt.rcParams['axes.unicode_minus'] = False

        fig, axes = plt.subplots(3, 1, figsize=(12, 10), gridspec_kw={'height_ratios': [3, 2, 1]})
        fig.suptitle(
            f"{self.report.strategy_name} | {self.report.symbol}\n"
            f"{self.report.start_time.strftime('%Y-%m-%d %H:%M')} ~ "
            f"{self.report.end_time.strftime('%Y-%m-%d %H:%M')}",
            fontsize=14,
            fontweight='bold'
        )

        # 1. Equity Curve
        ax1 = axes[0]
        if self.equity_curve:
            timestamps = [ep.timestamp for ep in self.equity_curve]
            equities = [ep.equity for ep in self.equity_curve]
            ax1.plot(timestamps, equities, 'b-', linewidth=1)
            ax1.fill_between(timestamps, self.report.initial_capital, equities, alpha=0.3)
            ax1.axhline(y=self.report.initial_capital, color='gray', linestyle='--', alpha=0.5)
        ax1.set_ylabel('Equity ($)')
        ax1.set_title('Equity Curve')
        ax1.grid(True, alpha=0.3)
        ax1.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d %H:%M'))

        # 2. Drawdown
        ax2 = axes[1]
        if self.equity_curve:
            timestamps = [ep.timestamp for ep in self.equity_curve]
            drawdowns = [-ep.drawdown for ep in self.equity_curve]  # 음수로 표시
            ax2.fill_between(timestamps, 0, drawdowns, color='red', alpha=0.5)
            ax2.plot(timestamps, drawdowns, 'r-', linewidth=0.5)
        ax2.set_ylabel('Drawdown (%)')
        ax2.set_title('Drawdown')
        ax2.grid(True, alpha=0.3)
        ax2.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d %H:%M'))

        # 3. Summary Table
        ax3 = axes[2]
        ax3.axis('off')

        # 요약 데이터
        summary_data = [
            ['Total Return', f"{self.report.total_return:+.2f}%"],
            ['Win Rate', f"{self.report.win_rate:.1f}%"],
            ['Total Trades', f"{self.report.total_trades}"],
            ['Profit Factor', f"{self.report.profit_factor:.2f}"],
            ['Max Drawdown', f"{self.report.max_drawdown:.2f}%"],
            ['Sharpe Ratio', f"{self.report.sharpe_ratio:.2f}"],
            ['Avg Win', f"${self.report.avg_win:.2f}"],
            ['Avg Loss', f"${self.report.avg_loss:.2f}"],
            ['Total Fees', f"${self.report.total_fees:.2f}"],
        ]

        # 2열로 나누어 표시
        col1_data = summary_data[:5]
        col2_data = summary_data[5:]

        table1 = ax3.table(
            cellText=col1_data,
            colLabels=['Metric', 'Value'],
            loc='center left',
            cellLoc='left',
            colWidths=[0.15, 0.1],
        )
        table1.auto_set_font_size(False)
        table1.set_fontsize(10)
        table1.scale(1.2, 1.5)

        table2 = ax3.table(
            cellText=col2_data,
            colLabels=['Metric', 'Value'],
            loc='center right',
            cellLoc='left',
            colWidths=[0.15, 0.1],
        )
        table2.auto_set_font_size(False)
        table2.set_fontsize(10)
        table2.scale(1.2, 1.5)

        plt.tight_layout()

        filepath = self.report_dir / "report.png"
        plt.savefig(filepath, dpi=150, bbox_inches='tight')
        plt.close()

        return filepath

