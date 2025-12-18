"""
Forward Tester Dashboard

NiceGUI 기반 단일 페이지 앱으로 포워드 테스트를 관리합니다.
"""

import asyncio
from datetime import datetime
from collections import deque
from typing import Optional

from nicegui import ui, app

from ..strategy import OBIStrategy, MarketState
from ..runner import ForwardRunner
from ..performance import PerformanceReport


class ForwardTesterApp:
    """
    단일 전략 포워드 테스터 UI
    
    전략 선택, 파라미터 설정, 시작/중지, 성과 모니터링을 제공합니다.
    """
    
    def __init__(self):
        self.runner: Optional[ForwardRunner] = None
        self.is_running: bool = False
        
        # UI 상태
        self.selected_strategy: str = "OBI"
        self.selected_symbol: str = "btcusdt"
        self.initial_capital: float = 10000.0
        
        # OBI 파라미터
        self.buy_threshold: float = 0.3
        self.sell_threshold: float = -0.3
        self.quantity: float = 0.01
        
        # 실시간 데이터
        self.pnl: float = 0.0
        self.trades_count: int = 0
        self.win_rate: float = 0.0
        self.current_price: float = 0.0
        
        # 차트 데이터 (최근 60개 포인트 = 30초)
        self.imbalance_history = deque(maxlen=60)
        self.price_history = deque(maxlen=60)  # 가격 히스토리
        self.time_labels = deque(maxlen=60)
        self.order_markers: list[dict] = []  # 주문 마커 [{time, price, side, status}]
        self._last_trade_count = 0  # 새 거래 감지용
        
        # UI 요소 참조
        self._status_label: Optional[ui.label] = None
        self._pnl_label: Optional[ui.label] = None
        self._trades_label: Optional[ui.label] = None
        self._orders_label: Optional[ui.label] = None  # New
        self._winrate_label: Optional[ui.label] = None
        self._price_label: Optional[ui.label] = None
        self._bid_ask_label: Optional[ui.label] = None  # Bid/Ask 표시
        self._position_label: Optional[ui.label] = None
        self._trades_table: Optional[ui.table] = None
        self._update_timer: Optional[ui.timer] = None
        
        # 시각화 요소
        self._imbalance_chart: Optional[ui.echart] = None
        self._price_chart: Optional[ui.echart] = None  # 가격 차트
        self._pressure_bar_buy: Optional[ui.linear_progress] = None
        self._pressure_bar_sell: Optional[ui.linear_progress] = None
        self._pressure_label: Optional[ui.label] = None
        self._heartbeat_label: Optional[ui.label] = None
    
    def _create_strategy(self):
        """선택된 전략 생성"""
        if self.selected_strategy == "OBI":
            return OBIStrategy(
                buy_threshold=self.buy_threshold,
                sell_threshold=self.sell_threshold,
                quantity=self.quantity,
            )
        raise ValueError(f"Unknown strategy: {self.selected_strategy}")
    
    async def start(self):
        """전략 실행 시작"""
        if self.is_running:
            return
        
        try:
            print(f"[UI] Starting forward test... Symbol: {self.selected_symbol}")
            strategy = self._create_strategy()
            self.runner = ForwardRunner(
                strategy=strategy,
                symbol=self.selected_symbol,
                initial_capital=self.initial_capital,
            )
            self.is_running = True
            self._update_ui()
            
            # 차트 초기화
            self.imbalance_history.clear()
            self.time_labels.clear()
            if self._imbalance_chart:
                self._imbalance_chart.options["xAxis"]["data"] = []
                self._imbalance_chart.options["series"][0]["data"] = []
                self._imbalance_chart.update()
            
            # 백그라운드에서 실행
            asyncio.create_task(self._run_forward_test())
            ui.notify(f"Started {self.selected_symbol} OBI Strategy", color="positive")
            
        except Exception as e:
            print(f"[UI] Error starting: {e}")
            ui.notify(f"Error starting: {e}", color="negative")
    
    async def _run_forward_test(self):
        """포워드 테스트 실행 (백그라운드)"""
        try:
            print("[UI] Runner started")
            await self.runner.run()
        except Exception as e:
            print(f"[UI] Runner error: {e}")
            ui.notify(f"Runner error: {e}", color="negative")
        finally:
            print("[UI] Runner finished")
            self.is_running = False
            self._update_ui()
    
    async def stop(self):
        """전략 실행 중지"""
        if not self.is_running or not self.runner:
            return
        
        print("[UI] Stopping forward test...")
        
        # UI 먼저 업데이트하여 반응성 향상
        self.is_running = False
        self._update_ui()
        
        # 실제 중지 작업
        await self.runner.stop()
        
        ui.notify("Forward test stopped", color="info")
        print("[UI] Forward test stopped")
        
        # 성과 리포트 팝업
        report = self.get_report()
        if report:
            with ui.dialog() as dialog, ui.card().classes("w-96 bg-gray-900 border border-gray-700"):
                ui.label("📊 Performance Summary").classes("text-xl font-bold mb-4 w-full text-center text-cyan-400")
                
                with ui.grid(columns=2).classes("w-full gap-y-2"):
                    ui.label("Total Return:").classes("text-gray-400")
                    color = "text-green-500" if report.total_return >= 0 else "text-red-500"
                    ui.label(f"{report.total_return:+.2f}%").classes(f"font-bold {color} text-right")
                    
                    # realized_pnl = final_capital - initial_capital
                    realized_pnl = report.final_capital - report.initial_capital
                    ui.label("Realized PnL:").classes("text-gray-400")
                    ui.label(f"${realized_pnl:+,.2f}").classes(f"font-bold {color} text-right")
                    
                    ui.label("Win Rate:").classes("text-gray-400")
                    ui.label(f"{report.win_rate:.1f}%").classes("font-bold text-white text-right")
                    
                    ui.label("Trades (W/L):").classes("text-gray-400")
                    ui.label(f"{report.winning_trades}W / {report.losing_trades}L").classes("font-bold text-white text-right")
                    
                    ui.label("Total Trades:").classes("text-gray-400")
                    ui.label(f"{report.total_trades}").classes("font-bold text-white text-right")
                
                ui.button("Close", on_click=dialog.close).classes("mt-6 w-full bg-gray-700 hover:bg-gray-600")
            
            dialog.open()
    
    def _update_ui(self):
        """UI 상태 업데이트"""
        if self._status_label:
            status = "🟢 Running" if self.is_running else "⚫ Stopped"
            self._status_label.text = status
    
    def _update_metrics(self):
        """성과 지표 및 차트 업데이트 (타이머 콜백)"""
        if not self.runner or not self.is_running:
            return
        
        trader = self.runner.trader
        market_state = self.runner.market_state
        
        # === 기본 지표 업데이트 ===
        # PnL
        total_pnl = trader.total_pnl
        if self._pnl_label:
            color = "text-green-500" if total_pnl >= 0 else "text-red-500"
            self._pnl_label.text = f"${total_pnl:+,.2f}"
            self._pnl_label.classes(replace=f"text-2xl font-bold {color}")
        
        # 거래 수
        self.trades_count = len(trader.trades)
        if self._trades_label:
            self._trades_label.text = str(self.trades_count)
            
        # 대기 주문
        active_orders = len(trader.pending_orders)
        if self._orders_label:
            self._orders_label.text = str(active_orders)
        
        # 승률
        pnl_trades = [t for t in trader.trades if t.pnl != 0]
        total = len(pnl_trades)
        
        if total > 0:
            winning = len([t for t in pnl_trades if t.pnl > 0])
            self.win_rate = (winning / total * 100)
            text = f"{self.win_rate:.1f}%"
        else:
            self.win_rate = 0.0
            text = "N/A"  # 청산된 거래가 없음
            
        if self._winrate_label:
            self._winrate_label.text = text
        
        # 마지막 체결가 (Last Trade)
        if self._price_label:
            last_price = self.runner.last_trade_price
            if last_price > 0:
                self._price_label.text = f"${last_price:,.2f}"
            elif market_state:
                self._price_label.text = f"${market_state.mid_price:,.2f}"
        
        # Bid/Ask 표시
        if market_state and self._bid_ask_label:
            spread = market_state.best_ask - market_state.best_bid
            self._bid_ask_label.text = f"Bid: ${market_state.best_bid:,.0f} | Ask: ${market_state.best_ask:,.0f} (Spread: ${spread:,.0f})"
        
        # 포지션
        if self._position_label:
            pos = trader.position
            if pos.side:
                self._position_label.text = f"{pos.side.value} {pos.quantity:.4f} @ ${pos.entry_price:,.2f}"
            else:
                self._position_label.text = "No Position"
        
        # 거래 내역 테이블
        if self._trades_table:
            recent_trades = trader.trades[-10:][::-1]
            rows = []
            for t in recent_trades:
                rows.append({
                    "time": t.timestamp.strftime("%H:%M:%S"),
                    "side": t.side.value,
                    "price": f"${t.price:,.2f}",
                    "qty": f"{t.quantity:.4f}",
                    "pnl": f"${t.pnl:+.2f}" if t.pnl != 0 else "--",
                })
            self._trades_table.rows = rows
            
        # === 시각화 업데이트 ===
        if market_state:
            now_str = datetime.now().strftime("%H:%M:%S")
            
            # 1. Imbalance 차트 업데이트
            self.imbalance_history.append(market_state.imbalance)
            self.time_labels.append(now_str)
            
            if self._imbalance_chart:
                self._imbalance_chart.options["xAxis"]["data"] = list(self.time_labels)
                self._imbalance_chart.options["series"][0]["data"] = list(self.imbalance_history)
                # 임계값 라인 업데이트 (설정 변경 반영)
                self._imbalance_chart.options["series"][0]["markLine"]["data"] = [
                    {"yAxis": self.buy_threshold, "label": {"formatter": "Buy"}},
                    {"yAxis": self.sell_threshold, "label": {"formatter": "Sell"}}
                ]
                self._imbalance_chart.update()
            
            # 2. Pressure Bar 업데이트
            # Imbalance = (Bid - Ask) / (Bid + Ask)
            # Imbalance > 0 : Bid 우세 (Buy Pressure)
            # Imbalance < 0 : Ask 우세 (Sell Pressure)
            
            # 시각화를 위해 0~1 사이 값으로 정규화
            # Imbalance range: -1 ~ 1
            # 0.5 기준으로 오른쪽은 Buy, 왼쪽은 Sell
            
            if self._pressure_label:
                status = "Neutral"
                color = "text-gray-400"
                if market_state.imbalance > 0.1:
                    status = "Buying Pressure 🔼"
                    color = "text-green-500"
                elif market_state.imbalance < -0.1:
                    status = "Selling Pressure 🔽"
                    color = "text-red-500"
                
                self._pressure_label.text = f"{status} ({market_state.imbalance:+.2f})"
                self._pressure_label.classes(replace=f"text-center font-bold {color}")
            
            if self._pressure_bar_buy and self._pressure_bar_sell:
                # Buy Pressure (0 ~ 1)
                buy_strength = max(0, market_state.imbalance)
                self._pressure_bar_buy.value = buy_strength
                
                # Sell Pressure (0 ~ 1) - 절대값 사용
                sell_strength = max(0, -market_state.imbalance)
                self._pressure_bar_sell.value = sell_strength
            
            # 3. 가격 차트 업데이트
            last_price = self.runner.last_trade_price
            if last_price > 0:
                self.price_history.append(last_price)
                
                # 새 거래 감지 → 마커 추가
                current_trade_count = len(trader.trades)
                if current_trade_count > self._last_trade_count:
                    new_trades = trader.trades[self._last_trade_count:]
                    for t in new_trades:
                        self.order_markers.append({
                            "xAxis": now_str,
                            "yAxis": t.price,
                            "symbol": "pin",
                            "symbolSize": 30,
                            "itemStyle": {
                                "color": "#22c55e" if t.side.value == "BUY" else "#ef4444"
                            },
                            "label": {
                                "show": True,
                                "formatter": t.side.value,
                                "position": "top"
                            }
                        })
                    self._last_trade_count = current_trade_count
                    # 마커 최대 20개 유지
                    if len(self.order_markers) > 20:
                        self.order_markers = self.order_markers[-20:]
                
                if self._price_chart:
                    self._price_chart.options["xAxis"]["data"] = list(self.time_labels)
                    self._price_chart.options["series"][0]["data"] = list(self.price_history)
                    self._price_chart.options["series"][0]["markPoint"]["data"] = self.order_markers
                    
                    # 포지션 진입가 표시 (수평선)
                    pos = trader.position
                    if pos.side:
                        self._price_chart.options["series"][0]["markLine"]["data"] = [
                            {
                                "yAxis": pos.entry_price,
                                "label": {"formatter": f"Entry: ${pos.entry_price:,.0f}"},
                                "lineStyle": {"color": "#fbbf24", "type": "dashed"}
                            }
                        ]
                    else:
                        self._price_chart.options["series"][0]["markLine"]["data"] = []
                    
                    self._price_chart.update()

            # 3. Heartbeat 업데이트
            if self._heartbeat_label:
                self._heartbeat_label.text = f"Last Update: {now_str} | Ob: {market_state.timestamp.strftime('%H:%M:%S.%f')[:-3]}"
    
    def get_report(self) -> Optional[PerformanceReport]:
        """현재 성과 리포트"""
        if self.runner:
            return self.runner.get_performance_report()
        return None
    
    def export_csv(self):
        """거래 내역 CSV 내보내기"""
        if not self.runner or not self.runner.trader.trades:
            ui.notify("No trades to export", color="warning")
            return
        
        import csv
        import io
        
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Timestamp", "Side", "Price", "Quantity", "Fee", "PnL"])
        
        for t in self.runner.trader.trades:
            writer.writerow([
                t.timestamp.isoformat(),
                t.side.value,
                t.price,
                t.quantity,
                t.fee,
                t.pnl,
            ])
        
        csv_content = output.getvalue()
        filename = f"trades_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        ui.download(csv_content.encode(), filename)
        ui.notify(f"Exported {len(self.runner.trader.trades)} trades", color="positive")


def create_app():
    """NiceGUI 앱 생성"""
    tester = ForwardTesterApp()
    
    @ui.page("/")
    def main_page():
        # 다크 모드 설정
        ui.dark_mode().enable()
        
        # 스타일
        ui.add_head_html("""
        <style>
            .stat-card {
                background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                border-radius: 12px;
                padding: 16px;
                text-align: center;
            }
            .stat-label {
                color: #8892b0;
                font-size: 12px;
                text-transform: uppercase;
            }
            .stat-value {
                font-size: 24px;
                font-weight: bold;
                margin-top: 4px;
            }
            .pressure-bar .q-linear-progress__track {
                opacity: 0.1;
            }
        </style>
        """)
        
        with ui.column().classes("w-full max-w-6xl mx-auto p-4 gap-4"):
            # 헤더
            with ui.row().classes("w-full items-center justify-between"):
                ui.label("⚡ Intraday Forward Tester").classes("text-3xl font-bold text-cyan-400")
                tester._status_label = ui.label("⚫ Stopped").classes("text-lg")
            
            ui.separator()
            
            # 설정 섹션
            with ui.card().classes("w-full"):
                ui.label("Settings").classes("text-lg font-semibold mb-2")
                
                with ui.row().classes("gap-4 flex-wrap"):
                    ui.select(
                        ["OBI"],
                        label="Strategy",
                        value="OBI",
                    ).bind_value(tester, "selected_strategy").classes("w-32")
                    
                    ui.select(
                        ["btcusdt", "ethusdt", "solusdt"],
                        label="Symbol",
                        value="btcusdt",
                    ).bind_value(tester, "selected_symbol").classes("w-32")
                    
                    ui.number(
                        label="Initial Capital ($)",
                        value=10000,
                        min=100,
                        step=1000,
                    ).bind_value(tester, "initial_capital").classes("w-40")
                
                ui.label("OBI Parameters").classes("text-md font-semibold mt-4 mb-2")
                
                with ui.row().classes("gap-4 flex-wrap"):
                    ui.number(
                        label="Buy Threshold",
                        value=0.3,
                        min=-1,
                        max=1,
                        step=0.05,
                    ).bind_value(tester, "buy_threshold").classes("w-36")
                    
                    ui.number(
                        label="Sell Threshold",
                        value=-0.3,
                        min=-1,
                        max=1,
                        step=0.05,
                    ).bind_value(tester, "sell_threshold").classes("w-36")
                    
                    ui.number(
                        label="Quantity",
                        value=0.01,
                        min=0.001,
                        step=0.01,
                    ).bind_value(tester, "quantity").classes("w-36")
                
                # 버튼
                with ui.row().classes("gap-4 mt-4"):
                    start_btn = ui.button("▶ Start", on_click=tester.start).classes("bg-green-600")
                    stop_btn = ui.button("⏹ Stop", on_click=tester.stop).classes("bg-red-600")
            
            # 실시간 지표
            with ui.row().classes("w-full gap-4"):
                # 마지막 체결가 (실제 시장가)
                with ui.card().classes("flex-1 stat-card"):
                    ui.label("Last Trade").classes("stat-label")
                    tester._price_label = ui.label("--").classes("stat-value text-white")
                
                # PnL
                with ui.card().classes("flex-1 stat-card"):
                    ui.label("Total PnL").classes("stat-label")
                    tester._pnl_label = ui.label("$0.00").classes("stat-value text-green-500")
                
                # 거래 수
                with ui.card().classes("flex-1 stat-card"):
                    ui.label("Trades").classes("stat-label")
                    tester._trades_label = ui.label("0").classes("stat-value text-white")
                
                # 대기 주문
                with ui.card().classes("flex-1 stat-card"):
                    ui.label("Active Orders").classes("stat-label")
                    tester._orders_label = ui.label("0").classes("stat-value text-yellow-500")
                
                # 승률
                with ui.card().classes("flex-1 stat-card"):
                    ui.label("Win Rate").classes("stat-label")
                    tester._winrate_label = ui.label("0%").classes("stat-value text-white")
            
            # Bid/Ask 정보 (호가창 최상위)
            with ui.card().classes("w-full").style("background: rgba(0,0,0,0.3); padding: 8px;"):
                tester._bid_ask_label = ui.label("Bid: -- | Ask: -- (Spread: --)").classes("text-center text-gray-400 font-mono")
            
            # === 시각화 섹션 (New) ===
            with ui.row().classes("w-full gap-4"):
                # Imbalance Chart
                with ui.card().classes("w-2/3").style("height: 400px"):
                    ui.label("Real-time OBI Imbalance").classes("text-lg font-semibold mb-2")
                    tester._imbalance_chart = ui.echart({
                        "tooltip": {"trigger": "axis"},
                        "xAxis": {
                            "type": "category",
                            "data": [],
                            "boundaryGap": False,
                        },
                        "yAxis": {
                            "type": "value",
                            "min": -1,
                            "max": 1,
                            "splitLine": {"show": True, "lineStyle": {"type": "dashed", "opacity": 0.2}}
                        },
                        "series": [{
                            "data": [],
                            "type": "line",
                            "smooth": True,
                            "symbol": "none",
                            "lineStyle": {"color": "#00d2ff", "width": 2},
                            "areaStyle": {
                                "color": {
                                    "type": "linear",
                                    "x": 0, "y": 0, "x2": 0, "y2": 1,
                                    "colorStops": [
                                        {"offset": 0, "color": "rgba(0, 210, 255, 0.3)"},
                                        {"offset": 1, "color": "rgba(0, 210, 255, 0)"}
                                    ]
                                }
                            },
                            "markLine": {
                                "symbol": "none",
                                "label": {"position": "end"},
                                "data": [
                                    {"yAxis": 0.3, "lineStyle": {"color": "green", "type": "solid"}, "label": {"formatter": "Buy"}},
                                    {"yAxis": -0.3, "lineStyle": {"color": "red", "type": "solid"}, "label": {"formatter": "Sell"}}
                                ]
                            }
                        }],
                        "grid": {"top": 30, "bottom": 30, "left": 40, "right": 20}
                    }).classes("w-full h-full")

                # Market Pressure & Heartbeat
                with ui.column().classes("w-1/3 gap-4"):
                    # Pressure Gauge
                    with ui.card().classes("w-full"):
                        ui.label("Market Pressure").classes("text-lg font-semibold mb-4")
                        tester._pressure_label = ui.label("Neutral (0.00)").classes("text-center font-bold text-gray-400 mb-2")
                        
                        with ui.row().classes("w-full items-center"):
                            ui.label("Sell").classes("text-xs text-red-500 w-8")
                            tester._pressure_bar_sell = ui.linear_progress(value=0.0).classes("flex-1 h-4 rounded pressure-bar").props("color=red-14 track-color=transparent reverse")
                        
                        with ui.row().classes("w-full items-center mt-1"):
                            ui.label("Buy").classes("text-xs text-green-500 w-8")
                            tester._pressure_bar_buy = ui.linear_progress(value=0.0).classes("flex-1 h-4 rounded pressure-bar").props("color=green-14 track-color=transparent")
                            
                        ui.label("Strength").classes("text-xs text-center text-gray-500 mt-2")

                    # Heartbeat
                    with ui.card().classes("w-full mt-auto"):
                        ui.label("System Status").classes("text-lg font-semibold mb-2")
                        tester._heartbeat_label = ui.label("Ready").classes("text-sm text-gray-400 font-mono")
                        ui.label("Updates every 0.5s").classes("text-xs text-gray-600 mt-1")
            
            # === 가격 차트 (New) ===
            with ui.card().classes("w-full").style("height: 350px"):
                ui.label("📈 Price Chart with Orders").classes("text-lg font-semibold mb-2")
                tester._price_chart = ui.echart({
                    "tooltip": {
                        "trigger": "axis",
                        "axisPointer": {"type": "cross"}
                    },
                    "xAxis": {
                        "type": "category",
                        "data": [],
                        "boundaryGap": False,
                    },
                    "yAxis": {
                        "type": "value",
                        "scale": True,  # 자동 스케일
                        "splitLine": {"show": True, "lineStyle": {"type": "dashed", "opacity": 0.2}}
                    },
                    "series": [{
                        "name": "Price",
                        "data": [],
                        "type": "line",
                        "smooth": False,
                        "symbol": "none",
                        "lineStyle": {"color": "#fbbf24", "width": 2},
                        "areaStyle": {
                            "color": {
                                "type": "linear",
                                "x": 0, "y": 0, "x2": 0, "y2": 1,
                                "colorStops": [
                                    {"offset": 0, "color": "rgba(251, 191, 36, 0.3)"},
                                    {"offset": 1, "color": "rgba(251, 191, 36, 0)"}
                                ]
                            }
                        },
                        "markPoint": {
                            "data": [],  # 주문 마커
                        },
                        "markLine": {
                            "symbol": "none",
                            "data": [],  # 진입가 라인
                        }
                    }],
                    "grid": {"top": 30, "bottom": 30, "left": 60, "right": 20}
                }).classes("w-full h-full")
            
            # 포지션
            with ui.card().classes("w-full"):
                ui.label("Current Position").classes("text-lg font-semibold")
                tester._position_label = ui.label("No Position").classes("text-xl mt-2")
            
            # 거래 내역
            with ui.card().classes("w-full"):
                with ui.row().classes("w-full items-center justify-between"):
                    ui.label("Recent Trades").classes("text-lg font-semibold")
                    ui.button("📥 Export CSV", on_click=tester.export_csv).classes("bg-blue-600")
                
                columns = [
                    {"name": "time", "label": "Time", "field": "time", "align": "left"},
                    {"name": "side", "label": "Side", "field": "side", "align": "center"},
                    {"name": "price", "label": "Price", "field": "price", "align": "right"},
                    {"name": "qty", "label": "Qty", "field": "qty", "align": "right"},
                    {"name": "pnl", "label": "PnL", "field": "pnl", "align": "right"},
                ]
                
                tester._trades_table = ui.table(
                    columns=columns,
                    rows=[],
                    row_key="time",
                ).classes("w-full")
            
            # 실시간 업데이트 타이머 (0.5초마다)
            tester._update_timer = ui.timer(0.5, tester._update_metrics)
    
    return tester


def run_dashboard(port: int = 8080):
    """대시보드 실행"""
    create_app()
    ui.run(
        title="Intraday Forward Tester",
        port=port,
        reload=False,
        show=True,
    )


if __name__ == "__main__":
    run_dashboard()
