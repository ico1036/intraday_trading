"""
Dash 실시간 대시보드

Binance Orderbook 데이터를 실시간으로 시각화하는 대시보드입니다.
"""

import asyncio
import threading
from collections import deque
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dash import Dash, html, dcc, callback, Output, Input

from .client import BinanceWebSocketClient, OrderbookSnapshot
from .orderbook import OrderbookProcessor, OrderbookState
from .metrics import MetricsCalculator, MetricsSnapshot


# ============================================================================
# 글로벌 상태 (스레드 간 공유)
# ============================================================================

class DashboardState:
    """대시보드 상태 관리"""
    
    def __init__(self, max_history: int = 500):
        self.processor = OrderbookProcessor(max_history=max_history)
        self.metrics_calc = MetricsCalculator(max_history=max_history)
        self.current_state: Optional[OrderbookState] = None
        self.current_metrics: Optional[MetricsSnapshot] = None
        self._lock = threading.Lock()
    
    def update(self, snapshot: OrderbookSnapshot):
        """새 스냅샷으로 상태 업데이트 (스레드 안전)"""
        with self._lock:
            self.current_state = self.processor.update(snapshot)
            self.current_metrics = self.metrics_calc.calculate(self.current_state)
    
    def get_state(self) -> tuple[Optional[OrderbookState], Optional[MetricsSnapshot]]:
        """현재 상태 조회 (스레드 안전)"""
        with self._lock:
            return self.current_state, self.current_metrics
    
    def get_metrics_df(self) -> pd.DataFrame:
        """지표 DataFrame 조회 (스레드 안전)"""
        with self._lock:
            return self.metrics_calc.to_dataframe()


# 글로벌 상태 인스턴스
state = DashboardState()


# ============================================================================
# WebSocket 데이터 수신 (백그라운드 스레드)
# ============================================================================

def run_websocket():
    """WebSocket 연결을 별도 스레드에서 실행"""
    async def _connect():
        client = BinanceWebSocketClient("btcusdt", depth_levels=20, update_speed="100ms")
        
        def on_data(snapshot: OrderbookSnapshot):
            state.update(snapshot)
        
        print("[Dashboard] WebSocket 연결 중...")
        await client.connect(on_data)
    
    # 새 이벤트 루프 생성
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(_connect())


# ============================================================================
# Dash 앱 설정
# ============================================================================

# 다크 테마 색상
COLORS = {
    "background": "#0d1117",
    "card": "#161b22",
    "text": "#c9d1d9",
    "text_muted": "#8b949e",
    "bid": "#00D4AA",
    "ask": "#FF6B6B",
    "accent": "#58a6ff",
    "border": "#30363d",
}

# CSS 스타일
external_stylesheets = []

app = Dash(__name__, external_stylesheets=external_stylesheets)
app.title = "Intraday Trading Dashboard"

# ============================================================================
# 레이아웃
# ============================================================================

app.layout = html.Div(
    style={
        "backgroundColor": COLORS["background"],
        "minHeight": "100vh",
        "padding": "20px",
        "fontFamily": "'Segoe UI', 'Roboto', sans-serif",
    },
    children=[
        # 헤더
        html.Div(
            style={
                "display": "flex",
                "justifyContent": "space-between",
                "alignItems": "center",
                "marginBottom": "20px",
                "paddingBottom": "15px",
                "borderBottom": f"1px solid {COLORS['border']}",
            },
            children=[
                html.H1(
                    "BTC/USDT Orderbook Dashboard",
                    style={
                        "color": COLORS["text"],
                        "margin": "0",
                        "fontSize": "24px",
                        "fontWeight": "600",
                    }
                ),
                html.Div(
                    id="last-update",
                    style={"color": COLORS["text_muted"], "fontSize": "14px"}
                ),
            ]
        ),
        
        # 상단 지표 카드들
        html.Div(
            id="metrics-cards",
            style={
                "display": "grid",
                "gridTemplateColumns": "repeat(auto-fit, minmax(200px, 1fr))",
                "gap": "15px",
                "marginBottom": "20px",
            }
        ),
        
        # 차트 그리드
        html.Div(
            style={
                "display": "grid",
                "gridTemplateColumns": "1fr 1fr",
                "gap": "20px",
            },
            children=[
                # 왼쪽: Orderbook 히트맵
                html.Div(
                    style={
                        "backgroundColor": COLORS["card"],
                        "borderRadius": "8px",
                        "padding": "15px",
                        "border": f"1px solid {COLORS['border']}",
                    },
                    children=[
                        html.H3(
                            "Orderbook",
                            style={
                                "color": COLORS["text"],
                                "margin": "0 0 10px 0",
                                "fontSize": "16px",
                            }
                        ),
                        dcc.Graph(
                            id="orderbook-chart",
                            config={"displayModeBar": False},
                            style={"height": "400px"}
                        ),
                    ]
                ),
                
                # 오른쪽: Depth Chart
                html.Div(
                    style={
                        "backgroundColor": COLORS["card"],
                        "borderRadius": "8px",
                        "padding": "15px",
                        "border": f"1px solid {COLORS['border']}",
                    },
                    children=[
                        html.H3(
                            "Depth Chart",
                            style={
                                "color": COLORS["text"],
                                "margin": "0 0 10px 0",
                                "fontSize": "16px",
                            }
                        ),
                        dcc.Graph(
                            id="depth-chart",
                            config={"displayModeBar": False},
                            style={"height": "400px"}
                        ),
                    ]
                ),
            ]
        ),
        
        # 하단: 시계열 차트
        html.Div(
            style={
                "marginTop": "20px",
                "backgroundColor": COLORS["card"],
                "borderRadius": "8px",
                "padding": "15px",
                "border": f"1px solid {COLORS['border']}",
            },
            children=[
                html.H3(
                    "Price & Spread Time Series",
                    style={
                        "color": COLORS["text"],
                        "margin": "0 0 10px 0",
                        "fontSize": "16px",
                    }
                ),
                dcc.Graph(
                    id="timeseries-chart",
                    config={"displayModeBar": False},
                    style={"height": "350px"}
                ),
            ]
        ),
        
        # 자동 업데이트 인터벌
        dcc.Interval(
            id="interval-component",
            interval=200,  # 200ms마다 업데이트
            n_intervals=0
        ),
    ]
)


# ============================================================================
# 콜백 함수들
# ============================================================================

def create_metric_card(title: str, value: str, subtitle: str = "", color: str = COLORS["text"]):
    """지표 카드 컴포넌트 생성"""
    return html.Div(
        style={
            "backgroundColor": COLORS["card"],
            "borderRadius": "8px",
            "padding": "15px",
            "border": f"1px solid {COLORS['border']}",
        },
        children=[
            html.Div(
                title,
                style={
                    "color": COLORS["text_muted"],
                    "fontSize": "12px",
                    "textTransform": "uppercase",
                    "marginBottom": "5px",
                }
            ),
            html.Div(
                value,
                style={
                    "color": color,
                    "fontSize": "24px",
                    "fontWeight": "600",
                }
            ),
            html.Div(
                subtitle,
                style={
                    "color": COLORS["text_muted"],
                    "fontSize": "12px",
                    "marginTop": "5px",
                }
            ) if subtitle else None,
        ]
    )


@callback(
    [
        Output("metrics-cards", "children"),
        Output("last-update", "children"),
        Output("orderbook-chart", "figure"),
        Output("depth-chart", "figure"),
        Output("timeseries-chart", "figure"),
    ],
    Input("interval-component", "n_intervals")
)
def update_dashboard(n):
    """대시보드 전체 업데이트"""
    current_state, current_metrics = state.get_state()
    
    # 데이터가 없는 경우 빈 차트 반환
    if not current_state or not current_metrics:
        empty_fig = go.Figure()
        empty_fig.update_layout(
            paper_bgcolor=COLORS["card"],
            plot_bgcolor=COLORS["card"],
            font_color=COLORS["text"],
            annotations=[{
                "text": "Waiting for data...",
                "xref": "paper",
                "yref": "paper",
                "x": 0.5,
                "y": 0.5,
                "showarrow": False,
                "font": {"size": 16, "color": COLORS["text_muted"]}
            }]
        )
        return (
            [create_metric_card("Status", "Connecting...", color=COLORS["accent"])],
            "Connecting to Binance...",
            empty_fig,
            empty_fig,
            empty_fig,
        )
    
    # 지표 카드들
    diff = current_metrics.micro_price - current_metrics.mid_price
    diff_color = COLORS["bid"] if diff >= 0 else COLORS["ask"]
    imb_color = COLORS["bid"] if current_metrics.imbalance >= 0 else COLORS["ask"]
    
    metrics_cards = [
        create_metric_card(
            "Best Bid",
            f"${current_metrics.best_bid:,.2f}",
            f"{current_state.best_bid[1]:.4f} BTC",
            COLORS["bid"]
        ),
        create_metric_card(
            "Best Ask",
            f"${current_metrics.best_ask:,.2f}",
            f"{current_state.best_ask[1]:.4f} BTC",
            COLORS["ask"]
        ),
        create_metric_card(
            "Spread",
            f"${current_metrics.spread:.2f}",
            f"{current_metrics.spread_bps:.2f} bps",
            COLORS["accent"]
        ),
        create_metric_card(
            "Mid Price",
            f"${current_metrics.mid_price:,.2f}",
            color=COLORS["text"]
        ),
        create_metric_card(
            "Micro Price",
            f"${current_metrics.micro_price:,.2f}",
            f"Diff: ${diff:+.2f}",
            diff_color
        ),
        create_metric_card(
            "Imbalance",
            f"{current_metrics.imbalance:+.3f}",
            "Bid heavy" if current_metrics.imbalance > 0 else "Ask heavy",
            imb_color
        ),
    ]
    
    # 마지막 업데이트 시간
    last_update = f"Last update: {current_metrics.timestamp.strftime('%H:%M:%S.%f')[:-3]}"
    
    # Orderbook 차트
    orderbook_fig = create_orderbook_chart(current_state)
    
    # Depth 차트
    depth_fig = create_depth_chart(current_state)
    
    # 시계열 차트
    timeseries_fig = create_timeseries_chart()
    
    return metrics_cards, last_update, orderbook_fig, depth_fig, timeseries_fig


def create_orderbook_chart(state: OrderbookState) -> go.Figure:
    """Orderbook 히트맵 차트 생성"""
    fig = make_subplots(
        rows=1, cols=2,
        subplot_titles=("Bids (Buy)", "Asks (Sell)"),
        horizontal_spacing=0.05
    )
    
    # 상위 15개 호가
    bid_prices = state.bid_prices[:15]
    bid_qtys = state.bid_quantities[:15]
    ask_prices = state.ask_prices[:15]
    ask_qtys = state.ask_quantities[:15]
    
    # 매수 호가
    fig.add_trace(
        go.Bar(
            y=[f"${p:,.0f}" for p in bid_prices],
            x=bid_qtys,
            orientation="h",
            marker_color=COLORS["bid"],
            opacity=0.8,
            text=[f"{q:.3f}" for q in bid_qtys],
            textposition="outside",
            textfont=dict(size=10, color=COLORS["text"]),
            hovertemplate="Price: %{y}<br>Qty: %{x:.4f} BTC<extra></extra>"
        ),
        row=1, col=1
    )
    
    # 매도 호가
    fig.add_trace(
        go.Bar(
            y=[f"${p:,.0f}" for p in ask_prices],
            x=ask_qtys,
            orientation="h",
            marker_color=COLORS["ask"],
            opacity=0.8,
            text=[f"{q:.3f}" for q in ask_qtys],
            textposition="outside",
            textfont=dict(size=10, color=COLORS["text"]),
            hovertemplate="Price: %{y}<br>Qty: %{x:.4f} BTC<extra></extra>"
        ),
        row=1, col=2
    )
    
    fig.update_layout(
        paper_bgcolor=COLORS["card"],
        plot_bgcolor=COLORS["card"],
        font_color=COLORS["text"],
        showlegend=False,
        margin=dict(l=10, r=10, t=30, b=10),
    )
    
    fig.update_xaxes(
        showgrid=True,
        gridcolor=COLORS["border"],
        zeroline=False,
    )
    
    fig.update_yaxes(
        showgrid=False,
    )
    
    return fig


def create_depth_chart(state: OrderbookState) -> go.Figure:
    """Depth 차트 생성"""
    fig = go.Figure()
    
    # 누적 수량 계산
    bid_prices = state.bid_prices[:20]
    bid_cumulative = np.cumsum(state.bid_quantities[:20]).tolist()
    ask_prices = state.ask_prices[:20]
    ask_cumulative = np.cumsum(state.ask_quantities[:20]).tolist()
    
    # 매수 누적
    fig.add_trace(go.Scatter(
        x=bid_prices[::-1],
        y=bid_cumulative[::-1],
        fill="tozeroy",
        name="Bids",
        line=dict(color=COLORS["bid"], width=2),
        fillcolor="rgba(0, 212, 170, 0.2)",
        hovertemplate="Price: $%{x:,.2f}<br>Cumulative: %{y:.4f} BTC<extra></extra>"
    ))
    
    # 매도 누적
    fig.add_trace(go.Scatter(
        x=ask_prices,
        y=ask_cumulative,
        fill="tozeroy",
        name="Asks",
        line=dict(color=COLORS["ask"], width=2),
        fillcolor="rgba(255, 107, 107, 0.2)",
        hovertemplate="Price: $%{x:,.2f}<br>Cumulative: %{y:.4f} BTC<extra></extra>"
    ))
    
    # Mid-price 라인
    fig.add_vline(
        x=state.mid_price,
        line_dash="dash",
        line_color=COLORS["accent"],
        annotation_text=f"Mid: ${state.mid_price:,.2f}",
        annotation_font_color=COLORS["text"],
    )
    
    fig.update_layout(
        paper_bgcolor=COLORS["card"],
        plot_bgcolor=COLORS["card"],
        font_color=COLORS["text"],
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        ),
        margin=dict(l=10, r=10, t=30, b=10),
        xaxis_title="Price ($)",
        yaxis_title="Cumulative Quantity (BTC)",
    )
    
    fig.update_xaxes(
        showgrid=True,
        gridcolor=COLORS["border"],
        zeroline=False,
    )
    
    fig.update_yaxes(
        showgrid=True,
        gridcolor=COLORS["border"],
        zeroline=False,
    )
    
    return fig


def create_timeseries_chart() -> go.Figure:
    """시계열 차트 생성"""
    df = state.get_metrics_df()
    
    if df.empty:
        fig = go.Figure()
        fig.update_layout(
            paper_bgcolor=COLORS["card"],
            plot_bgcolor=COLORS["card"],
            font_color=COLORS["text"],
        )
        return fig
    
    # 최근 200개 데이터만 표시
    df = df.tail(200)
    
    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        subplot_titles=("Mid vs Micro Price", "Spread", "Imbalance"),
        row_heights=[0.4, 0.3, 0.3]
    )
    
    # 가격 차트
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["mid_price"],
            mode="lines",
            name="Mid",
            line=dict(color="#4ECDC4", width=1.5)
        ),
        row=1, col=1
    )
    
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["micro_price"],
            mode="lines",
            name="Micro",
            line=dict(color=COLORS["ask"], width=1.5)
        ),
        row=1, col=1
    )
    
    # 스프레드 차트
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["spread"],
            mode="lines",
            name="Spread",
            line=dict(color=COLORS["accent"], width=1.5),
            fill="tozeroy",
            fillcolor="rgba(88, 166, 255, 0.1)"
        ),
        row=2, col=1
    )
    
    # Imbalance 차트
    colors = [COLORS["bid"] if i >= 0 else COLORS["ask"] for i in df["imbalance"]]
    fig.add_trace(
        go.Bar(
            x=df.index,
            y=df["imbalance"],
            name="Imbalance",
            marker_color=colors,
        ),
        row=3, col=1
    )
    
    # 기준선
    fig.add_hline(y=0, line_dash="solid", line_color=COLORS["border"], row=3, col=1)
    
    fig.update_layout(
        paper_bgcolor=COLORS["card"],
        plot_bgcolor=COLORS["card"],
        font_color=COLORS["text"],
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        ),
        margin=dict(l=10, r=10, t=40, b=10),
    )
    
    fig.update_xaxes(
        showgrid=True,
        gridcolor=COLORS["border"],
        zeroline=False,
    )
    
    fig.update_yaxes(
        showgrid=True,
        gridcolor=COLORS["border"],
        zeroline=False,
    )
    
    return fig


# ============================================================================
# 메인 실행
# ============================================================================

def main():
    """대시보드 실행"""
    print("=" * 60)
    print("  Intraday Trading Dashboard")
    print("  BTC/USDT Real-time Orderbook Visualization")
    print("=" * 60)
    print()
    
    # WebSocket 백그라운드 스레드 시작
    ws_thread = threading.Thread(target=run_websocket, daemon=True)
    ws_thread.start()
    print("[Dashboard] WebSocket thread started")
    
    # Dash 서버 실행
    print("[Dashboard] Starting web server...")
    print("[Dashboard] Open http://127.0.0.1:8050 in your browser")
    print()
    
    app.run(debug=False, host="127.0.0.1", port=8050)


if __name__ == "__main__":
    main()



