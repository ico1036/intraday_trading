"""
백테스팅 결과 시각화 모듈

PerformanceReport를 받아서 Plotly 차트로 시각화합니다.

교육 포인트:
    - Equity Curve: 자본 곡선 (시간에 따른 자본 변화)
    - Drawdown Chart: 낙폭 차트 (손실 구간 시각화)
    - Trade Distribution: 거래 손익 분포
    - Monthly Returns: 월별 수익률 히트맵
"""

from datetime import datetime
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .performance import PerformanceReport
from .paper_trader import Trade


class BacktestVisualizer:
    """
    백테스팅 결과 시각화기
    
    사용 예시:
        report = runner.run()
        visualizer = BacktestVisualizer(report, runner.trader.trades)
        
        # HTML 파일로 저장
        visualizer.save_html("backtest_result.html")
        
        # 브라우저에서 열기
        visualizer.show()
    
    교육 포인트:
        - 시각화는 숫자보다 직관적으로 이해하기 쉬움
        - Drawdown은 심리적 영향이 크므로 중요
        - 거래 분포로 전략의 일관성 확인
    """
    
    # 다크 테마 색상
    COLORS = {
        "background": "#0d1117",
        "card": "#161b22",
        "text": "#c9d1d9",
        "text_muted": "#8b949e",
        "profit": "#00D4AA",
        "loss": "#FF6B6B",
        "accent": "#58a6ff",
        "border": "#30363d",
    }
    
    def __init__(self, report: PerformanceReport, trades: list[Trade]):
        """
        Args:
            report: PerformanceReport 객체
            trades: 거래 내역 리스트
        """
        self.report = report
        self.trades = trades
    
    def create_equity_curve(self) -> go.Figure:
        """
        자본 곡선 (Equity Curve) 생성
        
        시간에 따른 자본 변화를 보여줍니다.
        """
        if not self.trades:
            return self._empty_figure("No trades")
        
        # 누적 자본 계산 - 시작점 포함
        timestamps = [self.report.start_time]
        capitals = [self.report.initial_capital]
        
        capital = self.report.initial_capital
        for trade in self.trades:
            capital += trade.pnl
            timestamps.append(trade.timestamp)
            capitals.append(capital)
        
        # 마지막 시간 추가 (end_time이 마지막 trade 이후라면)
        if self.report.end_time and self.report.end_time > timestamps[-1]:
            timestamps.append(self.report.end_time)
            capitals.append(capital)  # 마지막 capital 유지
        
        fig = go.Figure()
        
        # 자본 곡선
        fig.add_trace(go.Scatter(
            x=timestamps,
            y=capitals,
            mode="lines",
            name="Equity",
            line=dict(color=self.COLORS["accent"], width=2),
            fill="tozeroy",
            fillcolor="rgba(88, 166, 255, 0.1)",
            hovertemplate="Time: %{x}<br>Capital: $%{y:,.2f}<extra></extra>"
        ))
        
        # 초기 자본 라인
        fig.add_hline(
            y=self.report.initial_capital,
            line_dash="dash",
            line_color=self.COLORS["text_muted"],
            annotation_text=f"Initial: ${self.report.initial_capital:,.2f}",
            annotation_font_color=self.COLORS["text_muted"],
        )
        
        # 최종 자본 라인
        if self.report.final_capital != self.report.initial_capital:
            color = self.COLORS["profit"] if self.report.final_capital > self.report.initial_capital else self.COLORS["loss"]
            fig.add_hline(
                y=self.report.final_capital,
                line_dash="dash",
                line_color=color,
                annotation_text=f"Final: ${self.report.final_capital:,.2f}",
                annotation_font_color=color,
            )
        
        fig.update_layout(
            title="Equity Curve (자본 곡선)",
            xaxis_title="Time",
            yaxis_title="Capital ($)",
            paper_bgcolor=self.COLORS["card"],
            plot_bgcolor=self.COLORS["card"],
            font_color=self.COLORS["text"],
            hovermode="x unified",
            height=400,
        )
        
        return fig
    
    def create_drawdown_chart(self) -> go.Figure:
        """
        Drawdown 차트 생성
        
        시간에 따른 낙폭을 보여줍니다.
        """
        if not self.trades:
            return self._empty_figure("No trades")
        
        # 누적 자본 및 낙폭 계산 - 시작점 포함
        timestamps = [self.report.start_time]
        drawdowns = [0.0]  # 시작 시 drawdown은 0
        
        capital = self.report.initial_capital
        peak = self.report.initial_capital
        
        for trade in self.trades:
            capital += trade.pnl
            if capital > peak:
                peak = capital
            
            if peak > 0:
                dd = (peak - capital) / peak * 100
            else:
                dd = 0.0
            
            timestamps.append(trade.timestamp)
            drawdowns.append(dd)
        
        # 마지막 시간 추가 (end_time이 마지막 trade 이후라면)
        if self.report.end_time and self.report.end_time > timestamps[-1]:
            timestamps.append(self.report.end_time)
            drawdowns.append(dd)  # 마지막 drawdown 유지
        
        fig = go.Figure()
        
        # Drawdown 영역
        fig.add_trace(go.Scatter(
            x=timestamps,
            y=drawdowns,
            mode="lines",
            name="Drawdown",
            line=dict(color=self.COLORS["loss"], width=2),
            fill="tozeroy",
            fillcolor="rgba(255, 107, 107, 0.2)",
            hovertemplate="Time: %{x}<br>Drawdown: %{y:.2f}%<extra></extra>"
        ))
        
        # 최대 낙폭 라인
        if self.report.max_drawdown > 0:
            fig.add_hline(
                y=self.report.max_drawdown,
                line_dash="dash",
                line_color=self.COLORS["loss"],
                annotation_text=f"Max DD: {self.report.max_drawdown:.2f}%",
                annotation_font_color=self.COLORS["loss"],
            )
        
        fig.update_layout(
            title="Drawdown Chart (낙폭 차트)",
            xaxis_title="Time",
            yaxis_title="Drawdown (%)",
            paper_bgcolor=self.COLORS["card"],
            plot_bgcolor=self.COLORS["card"],
            font_color=self.COLORS["text"],
            hovermode="x unified",
            height=300,
        )
        
        return fig
    
    def create_trade_distribution(self) -> go.Figure:
        """
        거래 손익 분포 차트 생성
        
        각 거래의 손익을 히스토그램으로 보여줍니다.
        """
        if not self.trades:
            return self._empty_figure("No trades")
        
        pnl_values = [t.pnl for t in self.trades if t.pnl != 0]
        
        if not pnl_values:
            return self._empty_figure("No PnL trades")
        
        # 손익 분리
        profits = [p for p in pnl_values if p > 0]
        losses = [p for p in pnl_values if p < 0]
        
        fig = go.Figure()
        
        # 수익 거래
        if profits:
            fig.add_trace(go.Histogram(
                x=profits,
                name="Profit",
                marker_color=self.COLORS["profit"],
                opacity=0.7,
                nbinsx=30,
                hovertemplate="PnL: $%{x:.2f}<br>Count: %{y}<extra></extra>"
            ))
        
        # 손실 거래
        if losses:
            fig.add_trace(go.Histogram(
                x=losses,
                name="Loss",
                marker_color=self.COLORS["loss"],
                opacity=0.7,
                nbinsx=30,
                hovertemplate="PnL: $%{x:.2f}<br>Count: %{y}<extra></extra>"
            ))
        
        fig.update_layout(
            title="Trade PnL Distribution (거래 손익 분포)",
            xaxis_title="PnL ($)",
            yaxis_title="Count",
            paper_bgcolor=self.COLORS["card"],
            plot_bgcolor=self.COLORS["card"],
            font_color=self.COLORS["text"],
            barmode="overlay",
            height=300,
        )
        
        return fig
    
    def create_summary_dashboard(self) -> go.Figure:
        """
        종합 대시보드 생성
        
        여러 차트를 서브플롯으로 구성합니다.
        """
        fig = make_subplots(
            rows=3, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.08,
            subplot_titles=("Equity Curve", "Drawdown", "Trade PnL Distribution"),
            row_heights=[0.5, 0.25, 0.25],
        )
        
        # Equity Curve
        equity_fig = self.create_equity_curve()
        for trace in equity_fig.data:
            fig.add_trace(trace, row=1, col=1)
        
        # Drawdown
        dd_fig = self.create_drawdown_chart()
        for trace in dd_fig.data:
            fig.add_trace(trace, row=2, col=1)
        
        # Trade Distribution
        dist_fig = self.create_trade_distribution()
        for trace in dist_fig.data:
            fig.add_trace(trace, row=3, col=1)
        
        # 레이아웃 업데이트
        fig.update_layout(
            title=f"Backtest Results: {self.report.strategy_name} | {self.report.symbol}",
            paper_bgcolor=self.COLORS["background"],
            plot_bgcolor=self.COLORS["card"],
            font_color=self.COLORS["text"],
            height=800,
            showlegend=True,
        )
        
        # X축 업데이트
        fig.update_xaxes(
            showgrid=True,
            gridcolor=self.COLORS["border"],
            row=1, col=1
        )
        fig.update_xaxes(
            showgrid=True,
            gridcolor=self.COLORS["border"],
            row=2, col=1
        )
        fig.update_xaxes(
            showgrid=True,
            gridcolor=self.COLORS["border"],
            row=3, col=1
        )
        
        # Y축 업데이트
        fig.update_yaxes(
            showgrid=True,
            gridcolor=self.COLORS["border"],
        )
        
        return fig
    
    def save_html(self, filepath: str) -> None:
        """
        HTML 파일로 저장
        
        Args:
            filepath: 저장할 파일 경로
        """
        fig = self.create_summary_dashboard()
        fig.write_html(filepath)
        print(f"[Visualizer] Saved to {filepath}")
    
    def show(self) -> None:
        """
        브라우저에서 열기
        """
        fig = self.create_summary_dashboard()
        fig.show()
    
    def _empty_figure(self, message: str) -> go.Figure:
        """빈 차트 생성"""
        fig = go.Figure()
        fig.add_annotation(
            text=message,
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(size=16, color=self.COLORS["text_muted"])
        )
        fig.update_layout(
            paper_bgcolor=self.COLORS["card"],
            plot_bgcolor=self.COLORS["card"],
            font_color=self.COLORS["text"],
        )
        return fig




