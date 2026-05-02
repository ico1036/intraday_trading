"""
포트폴리오 모멘텀 전략

Cross-Asset Momentum:
    - 여러 코인의 수익률(모멘텀)을 비교
    - 상대적으로 강한 코인 롱, 약한 코인 숏
    - 마켓 뉴트럴 또는 방향성 전략 가능

사용 예시:
    # Helper class 사용
    helper = PortfolioMomentum(
        symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        lookback_minutes=60,
        top_n=1,
        bottom_n=1,
    )
    rankings = helper.calculate_rankings(price_data)
    signals = helper.generate_signals(rankings, current_positions)

    # Strategy class 사용 (backtest runner용)
    strategy = PortfolioMomentumStrategy(
        symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"],
        lookback_bars=72,        # 6 hours lookback (reduces noise)
        momentum_threshold=0.005, # 0.5% minimum momentum (reduces trades)
        top_n=1,
        bottom_n=1,
        rebalance_bars=24,       # 2 hours between rebalances
        stop_loss_pct=0.03,      # 3% stop loss
        take_profit_pct=0.06,    # 6% take profit (2:1 R:R)
    )
    order = strategy.generate_order(state)
"""

from collections import deque
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from intraday.strategy import MarketState, Order, Side, OrderType, PortfolioOrder


@dataclass
class CoinReturn:
    """
    개별 코인 수익률 데이터
    
    Attributes:
        symbol: 거래쌍 (예: "BTCUSDT")
        total_return: 기간 수익률 (0.1 = 10%)
    """
    symbol: str
    total_return: float = 0.0
    
    @classmethod
    def from_prices(cls, symbol: str, prices: pd.Series) -> "CoinReturn":
        """
        가격 시리즈에서 수익률 계산
        
        Args:
            symbol: 거래쌍
            prices: 가격 시리즈 (시간순)
            
        Returns:
            CoinReturn 객체
        """
        if prices.empty or len(prices) < 2:
            return cls(symbol=symbol, total_return=0.0)
        
        first_price = prices.iloc[0]
        last_price = prices.iloc[-1]
        
        if first_price == 0:
            return cls(symbol=symbol, total_return=0.0)
        
        total_return = (last_price - first_price) / first_price
        
        return cls(symbol=symbol, total_return=total_return)


class PortfolioMomentum:
    """
    포트폴리오 모멘텀 전략
    
    여러 코인의 수익률을 비교하여:
    - 가장 강한 N개 코인: 롱
    - 가장 약한 M개 코인: 숏 (옵션)
    
    Attributes:
        symbols: 분석 대상 심볼 목록
        lookback_minutes: 모멘텀 계산 기간 (분)
        top_n: 롱 포지션 코인 수
        bottom_n: 숏 포지션 코인 수 (0이면 롱 온리)
    """
    
    def __init__(
        self,
        symbols: list[str],
        lookback_minutes: int = 60,
        top_n: int = 1,
        bottom_n: int = 1,
    ):
        """
        Args:
            symbols: 분석 대상 심볼 목록
            lookback_minutes: 모멘텀 계산 기간 (분)
            top_n: 롱 포지션 코인 수
            bottom_n: 숏 포지션 코인 수 (0이면 롱 온리)
        """
        if len(symbols) < top_n + bottom_n:
            raise ValueError(
                f"Not enough symbols ({len(symbols)}) for top_n={top_n}, bottom_n={bottom_n}"
            )
        
        self.symbols = symbols
        self.lookback_minutes = lookback_minutes
        self.top_n = top_n
        self.bottom_n = bottom_n
    
    def calculate_rankings(
        self,
        price_data: dict[str, pd.Series],
    ) -> dict[str, list[str]]:
        """
        코인 순위 계산
        
        Args:
            price_data: {symbol: price_series} 형태의 가격 데이터
            
        Returns:
            {"long": [top_symbols], "short": [bottom_symbols]}
        """
        # 각 코인의 수익률 계산
        returns = []
        for symbol in self.symbols:
            if symbol in price_data:
                coin_return = CoinReturn.from_prices(symbol, price_data[symbol])
                returns.append(coin_return)
        
        # 수익률 기준 정렬 (내림차순)
        returns.sort(key=lambda x: x.total_return, reverse=True)
        
        # 상위 N개 (롱), 하위 M개 (숏)
        long_symbols = [r.symbol for r in returns[:self.top_n]]
        short_symbols = [r.symbol for r in returns[-self.bottom_n:]] if self.bottom_n > 0 else []
        
        # 롱과 숏이 겹치지 않도록 (코인 수가 적을 때)
        short_symbols = [s for s in short_symbols if s not in long_symbols]
        
        return {"long": long_symbols, "short": short_symbols}
    
    def generate_signals(
        self,
        rankings: dict[str, list[str]],
        current_positions: dict[str, str],
    ) -> dict[str, str]:
        """
        트레이딩 시그널 생성
        
        Args:
            rankings: calculate_rankings()의 결과
            current_positions: 현재 포지션 {symbol: "LONG" | "SHORT"}
            
        Returns:
            {symbol: "LONG" | "SHORT" | "CLOSE"} 시그널
        """
        signals = {}
        
        long_targets = set(rankings["long"])
        short_targets = set(rankings["short"])
        
        # 1. 새로운 롱 포지션
        for symbol in long_targets:
            current = current_positions.get(symbol)
            if current is None:
                signals[symbol] = "LONG"
            elif current == "SHORT":
                signals[symbol] = "CLOSE_AND_LONG"
        
        # 2. 새로운 숏 포지션
        for symbol in short_targets:
            current = current_positions.get(symbol)
            if current is None:
                signals[symbol] = "SHORT"
            elif current == "LONG":
                signals[symbol] = "CLOSE_AND_SHORT"
        
        # 3. 청산해야 할 포지션 (순위에서 벗어난 것)
        for symbol, position in current_positions.items():
            if symbol not in long_targets and symbol not in short_targets:
                signals[symbol] = "CLOSE"

        return signals


class PortfolioMomentumStrategy:
    """
    Cross-sectional momentum strategy with stop loss and take profit.

    Compares momentum across multiple coins and goes:
    - LONG on strongest momentum coin(s)
    - SHORT on weakest momentum coin(s)

    Features:
    - Stop loss: Exit if position loses more than stop_loss_pct from entry
    - Take profit: Exit if position gains more than take_profit_pct from entry
    - Rebalancing: Reassess rankings every rebalance_bars
    - Momentum threshold: Only trade if momentum exceeds threshold

    Returns PortfolioOrder for multi-symbol execution.
    """

    def __init__(
        self,
        symbols: list[str],
        lookback_bars: int = 72,
        momentum_threshold: float = 0.005,
        top_n: int = 1,
        bottom_n: int = 1,
        rebalance_bars: int = 24,
        stop_loss_pct: float = 0.03,
        take_profit_pct: float = 0.06,
        quantity: float = 0.01,
    ):
        """
        Args:
            symbols: List of symbols to trade
            lookback_bars: Number of bars for momentum calculation (default 72 = 6 hours)
            momentum_threshold: Minimum absolute momentum to trade (e.g., 0.005 = 0.5%)
            top_n: Number of coins to go LONG
            bottom_n: Number of coins to go SHORT
            rebalance_bars: How often to reassess rankings (default 24 = 2 hours)
            stop_loss_pct: Stop loss percentage (e.g., 0.03 = 3%)
            take_profit_pct: Take profit percentage (e.g., 0.06 = 6%)
            quantity: Position size per coin
        """
        if len(symbols) < top_n + bottom_n:
            raise ValueError(
                f"Not enough symbols ({len(symbols)}) for top_n={top_n}, bottom_n={bottom_n}"
            )

        self.symbols = symbols
        self.lookback_bars = lookback_bars
        self.momentum_threshold = momentum_threshold
        self.top_n = top_n
        self.bottom_n = bottom_n
        self.rebalance_bars = rebalance_bars
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.quantity = quantity

        # Price history per symbol
        self._price_history: dict[str, deque] = {
            sym: deque(maxlen=lookback_bars + 1) for sym in symbols
        }

        # Bar counter for rebalancing
        self._bar_count: int = 0

        # Entry prices for stop loss / take profit tracking
        # {symbol: {"entry_price": float, "side": "LONG" | "SHORT"}}
        self._entries: dict[str, dict] = {}

        # Current target positions
        self._target_long: list[str] = []
        self._target_short: list[str] = []

    def _calculate_momentum(self, symbol: str) -> Optional[float]:
        """
        Calculate momentum (return) over lookback period.

        Returns:
            Momentum as decimal (e.g., 0.01 = 1%) or None if insufficient data
        """
        prices = list(self._price_history[symbol])
        if len(prices) < self.lookback_bars + 1:
            return None

        old_price = prices[0]
        new_price = prices[-1]

        if old_price <= 0:
            return None

        return (new_price - old_price) / old_price

    def _rank_coins(self) -> dict[str, list[str]]:
        """
        Rank coins by momentum and return long/short targets.

        Returns:
            {"long": [symbols], "short": [symbols]}
        """
        momentums = {}
        for sym in self.symbols:
            mom = self._calculate_momentum(sym)
            if mom is not None:
                momentums[sym] = mom

        if len(momentums) < self.top_n + self.bottom_n:
            return {"long": [], "short": []}

        # Sort by momentum (ascending)
        ranked = sorted(momentums.keys(), key=lambda s: momentums[s])

        # Bottom n for SHORT (weakest momentum)
        short_candidates = ranked[: self.bottom_n]
        # Top n for LONG (strongest momentum)
        long_candidates = ranked[-self.top_n :]

        # Apply momentum threshold filter
        long_targets = [
            s for s in long_candidates if momentums[s] > self.momentum_threshold
        ]
        short_targets = [
            s for s in short_candidates if momentums[s] < -self.momentum_threshold
        ]

        return {"long": long_targets, "short": short_targets}

    def _check_stop_loss_take_profit(
        self, state: MarketState
    ) -> dict[str, Optional[Order]]:
        """
        Check all positions for stop loss or take profit conditions.

        Returns:
            {symbol: Order} for positions that need to be closed
        """
        orders: dict[str, Optional[Order]] = {}

        if state.panel is None:
            return orders

        for symbol, entry_info in list(self._entries.items()):
            if symbol not in state.panel:
                continue

            current_price = state.panel[symbol].get("close")
            if current_price is None:
                continue

            entry_price = entry_info["entry_price"]
            side = entry_info["side"]

            # Calculate PnL percentage
            if side == "LONG":
                pnl_pct = (current_price - entry_price) / entry_price
                # Stop loss: price dropped below threshold
                if pnl_pct <= -self.stop_loss_pct:
                    orders[symbol] = Order(
                        side=Side.SELL,
                        quantity=self.quantity,
                        order_type=OrderType.MARKET,
                    )
                    del self._entries[symbol]
                # Take profit: price rose above threshold
                elif pnl_pct >= self.take_profit_pct:
                    orders[symbol] = Order(
                        side=Side.SELL,
                        quantity=self.quantity,
                        order_type=OrderType.MARKET,
                    )
                    del self._entries[symbol]

            elif side == "SHORT":
                # For short, profit when price drops
                pnl_pct = (entry_price - current_price) / entry_price
                # Stop loss: price rose above threshold
                if pnl_pct <= -self.stop_loss_pct:
                    orders[symbol] = Order(
                        side=Side.BUY,
                        quantity=self.quantity,
                        order_type=OrderType.MARKET,
                    )
                    del self._entries[symbol]
                # Take profit: price dropped below threshold
                elif pnl_pct >= self.take_profit_pct:
                    orders[symbol] = Order(
                        side=Side.BUY,
                        quantity=self.quantity,
                        order_type=OrderType.MARKET,
                    )
                    del self._entries[symbol]

        return orders

    def _get_current_positions(self, state: MarketState) -> dict[str, str]:
        """
        Extract current position sides from state.

        Returns:
            {symbol: "LONG" | "SHORT"}
        """
        positions = {}
        if state.positions:
            for sym, pos_info in state.positions.items():
                if pos_info.get("side") in ("LONG", "SHORT"):
                    positions[sym] = pos_info["side"]
        return positions

    def generate_order(self, state: MarketState) -> PortfolioOrder | None:
        """
        Main entry point - generates portfolio orders based on momentum ranking.

        Called on each bar completion. Updates price history, checks stop loss/take profit,
        and rebalances positions at specified intervals.
        """
        if state.panel is None or state.symbol is None:
            return None

        # Update price history for all symbols
        for sym in self.symbols:
            if sym in state.panel and state.panel[sym].get("close") is not None:
                self._price_history[sym].append(state.panel[sym]["close"])

        self._bar_count += 1

        # First priority: Check stop loss / take profit
        sl_tp_orders = self._check_stop_loss_take_profit(state)

        # Check if it's rebalancing time
        is_rebalance_bar = self._bar_count % self.rebalance_bars == 0

        if not is_rebalance_bar:
            # Not rebalancing - only return SL/TP orders if any
            if sl_tp_orders:
                return PortfolioOrder(orders=sl_tp_orders)
            return None

        # Rebalancing time: Calculate new rankings
        rankings = self._rank_coins()
        new_long_targets = set(rankings["long"])
        new_short_targets = set(rankings["short"])

        # Get current positions
        current_positions = self._get_current_positions(state)

        # Build orders
        orders: dict[str, Optional[Order]] = dict(sl_tp_orders)  # Start with SL/TP

        for sym in self.symbols:
            # Skip if already handled by SL/TP
            if sym in sl_tp_orders:
                continue

            current_side = current_positions.get(sym)
            current_price = state.panel.get(sym, {}).get("close")

            if sym in new_long_targets:
                # Should be LONG
                if current_side != "LONG":
                    # Close existing SHORT if any, then go LONG
                    orders[sym] = Order(
                        side=Side.BUY,
                        quantity=self.quantity,
                        order_type=OrderType.MARKET,
                    )
                    # Track entry
                    if current_price:
                        self._entries[sym] = {
                            "entry_price": current_price,
                            "side": "LONG",
                        }

            elif sym in new_short_targets:
                # Should be SHORT
                if current_side != "SHORT":
                    # Close existing LONG if any, then go SHORT
                    orders[sym] = Order(
                        side=Side.SELL,
                        quantity=self.quantity,
                        order_type=OrderType.MARKET,
                    )
                    # Track entry
                    if current_price:
                        self._entries[sym] = {
                            "entry_price": current_price,
                            "side": "SHORT",
                        }

            else:
                # Not in target list - close position if any
                if current_side == "LONG":
                    orders[sym] = Order(
                        side=Side.SELL,
                        quantity=self.quantity,
                        order_type=OrderType.MARKET,
                    )
                    if sym in self._entries:
                        del self._entries[sym]
                elif current_side == "SHORT":
                    orders[sym] = Order(
                        side=Side.BUY,
                        quantity=self.quantity,
                        order_type=OrderType.MARKET,
                    )
                    if sym in self._entries:
                        del self._entries[sym]

        # Update target tracking
        self._target_long = list(new_long_targets)
        self._target_short = list(new_short_targets)

        if not orders:
            return None

        return PortfolioOrder(orders=orders)

    def __repr__(self) -> str:
        """Return string representation of the strategy."""
        symbols_str = ", ".join(self.symbols[:3])
        if len(self.symbols) > 3:
            symbols_str += f", ... ({len(self.symbols)} total)"
        return (
            f"{self.__class__.__name__}("
            f"symbols=[{symbols_str}], "
            f"lookback_bars={self.lookback_bars}, "
            f"top_n={self.top_n}, "
            f"bottom_n={self.bottom_n})"
        )

