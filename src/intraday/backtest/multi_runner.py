"""
포트폴리오 백테스트 러너

여러 코인을 동시에 백테스트하는 러너입니다.
시간 동기화, 포트폴리오 포지션 관리, 리밸런싱을 처리합니다.

사용 예시:
    strategy = PortfolioMomentum(symbols=["BTCUSDT", "ETHUSDT"], ...)
    runner = PortfolioBacktestRunner(strategy=strategy, initial_capital=10000)
    runner.load_data(data_dict)
    result = runner.run()
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from ..strategies.multi import PortfolioMomentum
from ..backtest.metrics import sharpe_daily_annualized


@dataclass
class PositionInfo:
    """개별 포지션 정보"""
    symbol: str
    side: str  # "LONG" or "SHORT"
    entry_price: float
    quantity: float
    entry_time: datetime


class PortfolioPosition:
    """
    포트폴리오 포지션 관리자
    
    여러 코인의 포지션을 동시에 관리합니다.
    """
    
    def __init__(self):
        self._positions: dict[str, PositionInfo] = {}
    
    def open(
        self,
        symbol: str,
        side: str,
        price: float,
        quantity: float,
        timestamp: datetime,
    ) -> None:
        """
        포지션 오픈
        
        Args:
            symbol: 거래쌍
            side: "LONG" or "SHORT"
            price: 진입 가격
            quantity: 수량
            timestamp: 진입 시간
        """
        self._positions[symbol] = PositionInfo(
            symbol=symbol,
            side=side,
            entry_price=price,
            quantity=quantity,
            entry_time=timestamp,
        )
    
    def close(self, symbol: str, price: float, timestamp: datetime) -> float:
        """
        포지션 청산
        
        Args:
            symbol: 거래쌍
            price: 청산 가격
            timestamp: 청산 시간
            
        Returns:
            실현 PnL
        """
        if symbol not in self._positions:
            return 0.0
        
        pos = self._positions[symbol]
        
        if pos.side == "LONG":
            pnl = (price - pos.entry_price) * pos.quantity
        else:  # SHORT
            pnl = (pos.entry_price - price) * pos.quantity
        
        del self._positions[symbol]
        return pnl
    
    def has_position(self, symbol: str) -> bool:
        """포지션 존재 여부"""
        return symbol in self._positions
    
    def get_side(self, symbol: str) -> Optional[str]:
        """포지션 방향"""
        if symbol in self._positions:
            return self._positions[symbol].side
        return None
    
    def get_entry_price(self, symbol: str) -> Optional[float]:
        """진입 가격"""
        if symbol in self._positions:
            return self._positions[symbol].entry_price
        return None
    
    def get_all_positions(self) -> list[PositionInfo]:
        """모든 포지션 목록"""
        return list(self._positions.values())
    
    def to_dict(self) -> dict[str, str]:
        """현재 포지션을 {symbol: side} 형태로"""
        return {symbol: pos.side for symbol, pos in self._positions.items()}
    
    def get_unrealized_pnl(self, current_prices: dict[str, float]) -> float:
        """미실현 PnL 계산"""
        total_pnl = 0.0
        for symbol, pos in self._positions.items():
            if symbol in current_prices:
                price = current_prices[symbol]
                if pos.side == "LONG":
                    total_pnl += (price - pos.entry_price) * pos.quantity
                else:
                    total_pnl += (pos.entry_price - price) * pos.quantity
        return total_pnl


@dataclass
class PortfolioBacktestResult:
    """
    포트폴리오 백테스트 결과
    
    전체 성과와 심볼별 분석을 제공합니다.
    """
    initial_capital: float
    final_capital: float
    total_return: float
    sharpe_ratio: float
    max_drawdown: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    equity_curve: pd.Series
    trade_log: list[dict]
    
    @property
    def win_rate(self) -> float:
        """승률"""
        if self.total_trades == 0:
            return 0.0
        return self.winning_trades / self.total_trades
    
    @property
    def profit_factor(self) -> float:
        """Profit Factor"""
        gross_profit = sum(t["pnl"] for t in self.trade_log if t.get("pnl", 0) > 0)
        gross_loss = abs(sum(t["pnl"] for t in self.trade_log if t.get("pnl", 0) < 0))
        
        if gross_loss == 0:
            return float("inf") if gross_profit > 0 else 0.0
        return gross_profit / gross_loss
    
    def get_symbol_breakdown(self) -> dict[str, dict]:
        """심볼별 성과 분석"""
        breakdown = {}
        
        for trade in self.trade_log:
            symbol = trade.get("symbol")
            if symbol is None:
                continue
            
            if symbol not in breakdown:
                breakdown[symbol] = {
                    "total_pnl": 0.0,
                    "trades": 0,
                    "wins": 0,
                    "losses": 0,
                }
            
            pnl = trade.get("pnl", 0)
            breakdown[symbol]["total_pnl"] += pnl
            breakdown[symbol]["trades"] += 1
            if pnl > 0:
                breakdown[symbol]["wins"] += 1
            elif pnl < 0:
                breakdown[symbol]["losses"] += 1
        
        return breakdown
    
    def summary(self) -> str:
        """결과 요약 문자열"""
        return f"""
=== Portfolio Backtest Result ===
Initial Capital: ${self.initial_capital:,.2f}
Final Capital:   ${self.final_capital:,.2f}
Total Return:    {self.total_return * 100:.2f}%
Sharpe Ratio:    {self.sharpe_ratio:.2f}
Max Drawdown:    {self.max_drawdown * 100:.2f}%
Total Trades:    {self.total_trades}
Win Rate:        {self.win_rate * 100:.1f}%
Profit Factor:   {self.profit_factor:.2f}
"""


class PortfolioBacktestRunner:
    """
    포트폴리오 백테스트 러너
    
    여러 코인의 데이터를 로드하고, 전략을 실행하며,
    리밸런싱을 처리합니다.
    """
    
    def __init__(
        self,
        strategy: PortfolioMomentum,
        initial_capital: float = 10000,
        position_size_pct: float = 0.1,
        rebalance_minutes: int = 60,
        fee_rate: float = 0.001,  # 0.1% (maker + taker 평균)
    ):
        """
        Args:
            strategy: PortfolioMomentum 전략 인스턴스
            initial_capital: 초기 자본
            position_size_pct: 포지션당 자본 비율 (0.1 = 10%)
            rebalance_minutes: 리밸런싱 주기 (분)
            fee_rate: 거래 수수료율 (편도)
        """
        self.strategy = strategy
        self.initial_capital = initial_capital
        self.position_size_pct = position_size_pct
        self.rebalance_minutes = rebalance_minutes
        self.fee_rate = fee_rate
        
        self.data: dict[str, pd.DataFrame] = {}
        self.position = PortfolioPosition()
        self.capital = initial_capital
        self.equity_curve: list[float] = []
        self.equity_timestamps: list[pd.Timestamp] = []
        self.trade_log: list[dict] = []
    
    def load_data(self, data: dict[str, pd.DataFrame]) -> None:
        """
        데이터 로드
        
        Args:
            data: {symbol: DataFrame} 형태, DataFrame은 timestamp, price 컬럼 필요
        """
        self.data = {}
        for symbol, df in data.items():
            # timestamp 인덱스로 설정
            df = df.copy()
            if "timestamp" in df.columns:
                df = df.set_index("timestamp")
            self.data[symbol] = df
    
    def get_synced_timestamps(self) -> pd.DatetimeIndex:
        """
        모든 코인에서 공통인 타임스탬프 반환
        
        시간 동기화를 위해 가장 가까운 분 단위로 반올림
        """
        if not self.data:
            return pd.DatetimeIndex([])
        
        # 각 데이터의 인덱스를 분 단위로 반올림
        rounded_indices = []
        for symbol, df in self.data.items():
            rounded = df.index.round("1min")
            rounded_indices.append(set(rounded))
        
        # 교집합
        common = rounded_indices[0]
        for idx_set in rounded_indices[1:]:
            common = common.intersection(idx_set)
        
        return pd.DatetimeIndex(sorted(common))
    
    def _get_price_at(self, symbol: str, timestamp: pd.Timestamp) -> Optional[float]:
        """특정 시간의 가격"""
        if symbol not in self.data:
            return None
        
        df = self.data[symbol]
        rounded = timestamp.round("1min")
        
        # 정확한 매치 시도
        if rounded in df.index:
            return float(df.loc[rounded, "price"])
        
        # 가장 가까운 이전 가격
        mask = df.index <= rounded
        if mask.any():
            return float(df.loc[mask].iloc[-1]["price"])
        
        return None
    
    def _get_lookback_prices(
        self,
        timestamp: pd.Timestamp,
    ) -> dict[str, pd.Series]:
        """lookback 기간의 가격 데이터"""
        lookback_start = timestamp - timedelta(minutes=self.strategy.lookback_minutes)
        
        result = {}
        for symbol, df in self.data.items():
            mask = (df.index >= lookback_start) & (df.index <= timestamp)
            if mask.any():
                result[symbol] = df.loc[mask, "price"]
        
        return result
    
    def _execute_signal(
        self,
        symbol: str,
        signal: str,
        price: float,
        timestamp: pd.Timestamp,
    ) -> None:
        """시그널 실행"""
        position_value = self.capital * self.position_size_pct
        quantity = position_value / price
        
        if signal == "LONG":
            fee = position_value * self.fee_rate
            self.capital -= fee
            self.position.open(symbol, "LONG", price, quantity, timestamp)
            self.trade_log.append({
                "timestamp": timestamp,
                "symbol": symbol,
                "action": "OPEN_LONG",
                "price": price,
                "quantity": quantity,
                "fee": fee,
            })
        
        elif signal == "SHORT":
            fee = position_value * self.fee_rate
            self.capital -= fee
            self.position.open(symbol, "SHORT", price, quantity, timestamp)
            self.trade_log.append({
                "timestamp": timestamp,
                "symbol": symbol,
                "action": "OPEN_SHORT",
                "price": price,
                "quantity": quantity,
                "fee": fee,
            })

        elif signal == "CLOSE":
            if self.position.has_position(symbol):
                pnl = self.position.close(symbol, price, timestamp)
                fee = abs(pnl) * self.fee_rate if pnl != 0 else position_value * self.fee_rate
                self.capital += pnl - fee
                self.trade_log.append({
                    "timestamp": timestamp,
                    "symbol": symbol,
                    "action": "CLOSE",
                    "price": price,
                    "pnl": pnl,
                    "fee": fee,
                })
        
        elif signal == "CLOSE_AND_LONG":
            # 청산 후 롱
            if self.position.has_position(symbol):
                pnl = self.position.close(symbol, price, timestamp)
                fee = abs(pnl) * self.fee_rate if pnl != 0 else position_value * self.fee_rate
                self.capital += pnl - fee
                self.trade_log.append({
                    "timestamp": timestamp,
                    "symbol": symbol,
                    "action": "CLOSE",
                    "price": price,
                    "pnl": pnl,
                    "fee": fee,
                })
            # 롱 진입
            fee = position_value * self.fee_rate
            self.capital -= fee
            self.position.open(symbol, "LONG", price, quantity, timestamp)
            self.trade_log.append({
                "timestamp": timestamp,
                "symbol": symbol,
                "action": "OPEN_LONG",
                "price": price,
                "quantity": quantity,
                "fee": fee,
            })
        
        elif signal == "CLOSE_AND_SHORT":
            # 청산 후 숏
            if self.position.has_position(symbol):
                pnl = self.position.close(symbol, price, timestamp)
                fee = abs(pnl) * self.fee_rate if pnl != 0 else position_value * self.fee_rate
                self.capital += pnl - fee
                self.trade_log.append({
                    "timestamp": timestamp,
                    "symbol": symbol,
                    "action": "CLOSE",
                    "price": price,
                    "pnl": pnl,
                    "fee": fee,
                })
            # 숏 진입
            fee = position_value * self.fee_rate
            self.capital -= fee
            self.position.open(symbol, "SHORT", price, quantity, timestamp)
            self.trade_log.append({
                "timestamp": timestamp,
                "symbol": symbol,
                "action": "OPEN_SHORT",
                "price": price,
                "quantity": quantity,
                "fee": fee,
            })

    def _result_from_current_state(self) -> PortfolioBacktestResult:
        """Build a result snapshot without mutating or rerunning the backtest."""
        equity_series = pd.Series(self.equity_curve)
        total_return = (self.capital - self.initial_capital) / self.initial_capital
        sharpe_ratio = sharpe_daily_annualized(equity_series, timestamps=self.equity_timestamps)

        rolling_max = equity_series.cummax()
        drawdown = (equity_series - rolling_max) / rolling_max
        max_drawdown = drawdown.min()

        closed_trades = [t for t in self.trade_log if "pnl" in t]
        winning_trades = len([t for t in closed_trades if t["pnl"] > 0])
        losing_trades = len([t for t in closed_trades if t["pnl"] < 0])

        return PortfolioBacktestResult(
            initial_capital=self.initial_capital,
            final_capital=self.capital,
            total_return=total_return,
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_drawdown,
            total_trades=len(closed_trades),
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            equity_curve=equity_series,
            trade_log=self.trade_log,
        )
    
    def save_report(self, output_dir: str | Path) -> str:
        """Save backtest artifacts and summary for parity with other runners."""
        from pathlib import Path as _P

        out_dir = _P(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        # if caller invokes save_report directly before run, call run once
        if not self.equity_curve:
            self.run()

        closed_trades = [t for t in self.trade_log if "pnl" in t]

        equity_df = pd.DataFrame({
            "timestamp": self.equity_timestamps,
            "equity": [float(v) for v in self.equity_curve],
        })
        trades_df = pd.DataFrame(self.trade_log)
        summary = {
            "strategy_name": self.strategy.__class__.__name__,
            "initial_capital": self.initial_capital,
            "final_capital": self.capital,
        }
        result = self._result_from_current_state()
        summary.update({
            "total_return": result.total_return,
            "sharpe_ratio": result.sharpe_ratio,
            "max_drawdown": result.max_drawdown,
            "total_trades": result.total_trades,
            "winning_trades": result.winning_trades,
            "losing_trades": result.losing_trades,
            "win_rate": result.win_rate,
            "profit_factor": result.profit_factor,
        })

        summary_df = pd.DataFrame([summary])
        metrics = {
            "profit_factor": result.profit_factor,
            "total_return": result.total_return,
            "max_drawdown": result.max_drawdown,
            "total_trades": result.total_trades,
            "win_rate": result.win_rate,
            "sharpe": result.sharpe_ratio,
            "sharpe_ratio": result.sharpe_ratio,
            "per_symbol": result.get_symbol_breakdown(),
        }
        summary_json = {
            "artifact_version": 1,
            "run_type": "backtest",
            "strategy_name": self.strategy.__class__.__name__,
            "symbols": list(getattr(self.strategy, "symbols", [])),
            **summary,
            "metrics": metrics,
        }

        equity_by_ts = {
            ts: float(eq)
            for ts, eq in zip(self.equity_timestamps, self.equity_curve)
        }
        weight_rows = []
        for trade in self.trade_log:
            timestamp = trade.get("timestamp")
            price = trade.get("price")
            quantity = trade.get("quantity")
            equity = equity_by_ts.get(timestamp, self.capital)
            notional = abs(float(price) * float(quantity)) if price and quantity else 0.0
            weight_rows.append({
                "timestamp": timestamp,
                "symbol": trade.get("symbol"),
                "side": str(trade.get("action", "")).replace("OPEN_", ""),
                "quantity": quantity,
                "price": price,
                "notional": notional,
                "weight": notional / equity if equity else 0.0,
            })

        weights_df = pd.DataFrame(
            weight_rows,
            columns=[
                "timestamp",
                "symbol",
                "side",
                "quantity",
                "price",
                "notional",
                "weight",
            ],
        )
        events_df = trades_df.copy()
        if events_df.empty:
            events_df = pd.DataFrame(columns=["timestamp", "event_type", "symbol", "details"])
        else:
            events_df.insert(1, "event_type", "trade")

        paths = [
            (equity_df, out_dir / "equity_curve.parquet", out_dir / "equity_curve.csv"),
            (trades_df, out_dir / "trades.parquet", out_dir / "trades.csv"),
            (summary_df, out_dir / "summary.parquet", out_dir / "summary.csv"),
            (weights_df, out_dir / "weights.parquet", out_dir / "weights.csv"),
            (events_df, out_dir / "events.parquet", out_dir / "events.csv"),
        ]

        for df, pqt, csv in paths:
            try:
                df.to_parquet(pqt, index=False)
            except Exception:
                pass
            df.to_csv(csv, index=False)

        (out_dir / "summary.json").write_text(
            json.dumps(summary_json, ensure_ascii=False, default=str, indent=2),
            encoding="utf-8",
        )
        (out_dir / "metrics.json").write_text(
            json.dumps(metrics, ensure_ascii=False, default=str, indent=2),
            encoding="utf-8",
        )
        (out_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "artifact_version": 1,
                    "run_type": "backtest",
                    "strategy_name": self.strategy.__class__.__name__,
                    "symbols": list(getattr(self.strategy, "symbols", [])),
                    "files": {
                        "summary": "summary.json",
                        "metrics": "metrics.json",
                        "summary_table": "summary.parquet",
                        "summary_csv": "summary.csv",
                        "equity_curve": "equity_curve.parquet",
                        "trades": "trades.parquet",
                        "weights": "weights.parquet",
                        "events": "events.parquet",
                        "report": "report.png",
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        try:
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(10, 4))
            if not equity_df.empty:
                ax.plot(equity_df["timestamp"], equity_df["equity"], linewidth=1)
            ax.set_title("Equity Curve")
            ax.set_xlabel("time")
            ax.set_ylabel("equity")
            ax.grid(alpha=0.2)
            fig.tight_layout()
            fig.savefig(out_dir / "report.png", dpi=120)
            plt.close(fig)
        except Exception:
            pass

        return str(out_dir)


    def run(self) -> PortfolioBacktestResult:
        """백테스트 실행"""
        timestamps = self.get_synced_timestamps()
        
        if len(timestamps) == 0:
            raise ValueError("No synchronized timestamps found")
        
        last_rebalance = timestamps[0]
        
        self.equity_timestamps = []
        for ts in timestamps:
            # 리밸런싱 주기 체크
            minutes_since_rebalance = (ts - last_rebalance).total_seconds() / 60
            
            if minutes_since_rebalance >= self.rebalance_minutes:
                # 모멘텀 계산
                price_data = self._get_lookback_prices(ts)
                
                if len(price_data) >= len(self.strategy.symbols):
                    rankings = self.strategy.calculate_rankings(price_data)
                    current_positions = self.position.to_dict()
                    signals = self.strategy.generate_signals(rankings, current_positions)
                    
                    # 시그널 실행
                    for symbol, signal in signals.items():
                        price = self._get_price_at(symbol, ts)
                        if price:
                            self._execute_signal(symbol, signal, price, ts)
                    
                    last_rebalance = ts
            
            # 에쿼티 계산
            current_prices = {
                symbol: self._get_price_at(symbol, ts)
                for symbol in self.strategy.symbols
            }
            current_prices = {k: v for k, v in current_prices.items() if v is not None}
            
            unrealized_pnl = self.position.get_unrealized_pnl(current_prices)
            equity = self.capital + unrealized_pnl
            self.equity_curve.append(equity)
            self.equity_timestamps.append(ts)
        
        # 최종 청산
        final_ts = timestamps[-1]
        for symbol in list(self.position._positions.keys()):
            price = self._get_price_at(symbol, final_ts)
            if price:
                self._execute_signal(symbol, "CLOSE", price, final_ts)

        # 마지막 에쿼티 포인트
        self.equity_timestamps.append(final_ts)
        self.equity_curve.append(self.capital)

        return self._result_from_current_state()
