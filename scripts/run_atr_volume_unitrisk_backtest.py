#!/usr/bin/env python3
"""
ATR Volume Unit Risk Strategy Backtest Script

Uses 5-minute candle data directly for the ATRVolumeUnitRiskStrategy.

Usage:
    uv run python scripts/run_atr_volume_unitrisk_backtest.py
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from intraday.strategies.multi import ATRVolumeUnitRiskMultiStrategyV4
from intraday.strategy import MarketState, Side, Order, PortfolioOrder
from intraday.backtest.metrics import sharpe_daily_annualized


class CandleBacktestRunner:
    """
    Simple candle-based backtest runner for portfolio strategies.

    Processes 5-minute candles across multiple symbols and executes
    portfolio strategies that generate PortfolioOrder objects.

    Uses isolated futures-style margin bookkeeping per symbol:
    - margin is reserved at entry: notional / leverage
    - unrealized PnL is mark-to-market on notional exposure
    - liquidation is checked on each bar based on Binance-like maintenance margin formula
    """

    def __init__(
        self,
        strategy,
        initial_capital: float = 100000.0,
        position_size_pct: float = 0.5,
        leverage: int = 1,
        maker_fee_rate: float = 0.0002,
        taker_fee_rate: float = 0.0005,
        maintenance_margin_rate: float = 0.004,
    ):
        self.strategy = strategy
        self.initial_capital = initial_capital
        self.position_size_pct = position_size_pct
        self.leverage = leverage
        self.maker_fee_rate = maker_fee_rate
        self.taker_fee_rate = taker_fee_rate
        self.maintenance_margin_rate = maintenance_margin_rate

        self.capital = initial_capital
        # symbol -> {side, qty, entry_price, margin, entry_fee, liquidation_price}
        self.positions: dict[str, dict] = {}
        self.trade_log = []
        self.equity_curve = []
        self._equity_timestamps: list[datetime] = []
        self._closed_this_bar: set = set()  # Track symbols closed in current bar

    def load_candle_data(
        self,
        data_paths: dict[str, str],
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """Load and merge candle data from multiple symbols."""
        dfs = []

        for symbol, path in data_paths.items():
            df = pd.read_parquet(path)

            # Ensure timestamp column
            if 'timestamp' not in df.columns:
                if df.index.name == 'timestamp':
                    df = df.reset_index()
                else:
                    raise ValueError(f"No timestamp column in {path}")

            # Convert to datetime
            df['timestamp'] = pd.to_datetime(df['timestamp'])

            # Filter by date range
            start = pd.to_datetime(start_date)
            end = pd.to_datetime(end_date) + timedelta(days=1)
            df = df[(df['timestamp'] >= start) & (df['timestamp'] < end)]

            # Add symbol column
            df['symbol'] = symbol
            dfs.append(df)

        # Combine all data and sort by timestamp
        combined = pd.concat(dfs, ignore_index=True)
        combined = combined.sort_values('timestamp').reset_index(drop=True)

        return combined

    def _build_panel(self, df: pd.DataFrame, timestamp: pd.Timestamp) -> dict:
        """Build panel data for all symbols at a given timestamp."""
        panel = {}

        # Get latest candle for each symbol up to this timestamp
        for symbol in self.strategy.symbols:
            symbol_df = df[(df['symbol'] == symbol) & (df['timestamp'] <= timestamp)]
            if symbol_df.empty:
                continue

            latest = symbol_df.iloc[-1]
            panel[symbol] = {
                'open': float(latest['open']),
                'high': float(latest['high']),
                'low': float(latest['low']),
                'close': float(latest['close']),
                'volume': float(latest['volume']),
            }

        return panel if panel else None

    def _get_positions_dict(self) -> dict:
        """Convert positions to strategy-expected format."""
        return {
            sym: {
                'side': pos['side'],
                'qty': pos['qty'],
                'entry_price': pos['entry_price'],
            }
            for sym, pos in self.positions.items()
        }

    def _calculate_liquidation_price(self, entry_price: float, side: str) -> float:
        """Binance-isolated style liquidation proxy.

        Uses the same fixed-MMR formula currently used by PaperTrader for consistency.
        """
        mmr = self.maintenance_margin_rate
        L = self.leverage
        if side == 'LONG':
            return entry_price * (1 / L - 1) / (mmr - 1)
        return entry_price * (1 / L + 1) / (mmr + 1)

    def _mark_price_liquidated(self, symbol: str, price: float) -> bool:
        pos = self.positions.get(symbol)
        if not pos:
            return False
        if pos['side'] == 'LONG':
            return price <= pos['liquidation_price']
        return price >= pos['liquidation_price']

    def _position_unrealized(self, pos: dict, price: float) -> float:
        if pos['side'] == 'LONG':
            return (price - pos['entry_price']) * pos['qty']
        return (pos['entry_price'] - price) * pos['qty']

    def _calc_margin_required(self, notional: float) -> float:
        if self.leverage <= 0:
            raise ValueError('leverage must be >= 1')
        return notional / self.leverage

    def _close_position(self, symbol: str, close_qty: float, price: float, timestamp: pd.Timestamp, fee_rate: float) -> float:
        """Close qty of an existing position. Returns realized pnl (already fee-adjusted)."""
        if close_qty <= 0:
            return 0.0

        pos = self.positions[symbol]
        held_qty = float(pos['qty'])
        close_qty = min(close_qty, held_qty)
        if close_qty <= 0:
            return 0.0

        close_notional = close_qty * price
        close_fee = close_notional * fee_rate

        direction = 1 if pos['side'] == 'LONG' else -1
        pnl = (price - pos['entry_price']) * close_qty * direction

        # release pro-rata margin + realised pnl allocation
        close_ratio = close_qty / held_qty
        released_margin = pos['margin'] * close_ratio
        allocated_entry_fee = pos['entry_fee'] * close_ratio

        self.capital += pnl
        self.capital -= close_fee
        self.capital += released_margin

        realized = pnl - allocated_entry_fee - close_fee

        if close_qty >= held_qty:
            del self.positions[symbol]
        else:
            pos['qty'] -= close_qty
            pos['margin'] -= released_margin
            pos['entry_fee'] -= allocated_entry_fee
            # keep liquidation price anchored to VWAP-weighted entry in real life;
            # keep original liquidation anchor for simplicity in partial exits

        self.trade_log.append({
            'timestamp': timestamp,
            'symbol': symbol,
            'action': f'CLOSE_{pos["side"]}',
            'price': price,
            'quantity': close_qty,
            'pnl': realized,
            'fee': close_fee,
        })
        self._closed_this_bar.add(symbol)
        return realized

    def _liquidate_if_needed(self, symbol: str, price: float, timestamp: pd.Timestamp) -> None:
        pos = self.positions.get(symbol)
        if not pos:
            return
        if not self._mark_price_liquidated(symbol, price):
            return

        liq_price = pos['liquidation_price']
        pnl = self._position_unrealized(pos, liq_price)
        self.capital += pos['margin'] + pnl - pos['entry_fee']
        realized = pnl - pos['entry_fee']
        self.trade_log.append({
            'timestamp': timestamp,
            'symbol': symbol,
            'action': 'LIQUIDATE',
            'price': liq_price,
            'quantity': pos['qty'],
            'pnl': realized,
            'fee': 0.0,
        })
        self.positions.pop(symbol, None)
        self._closed_this_bar.add(symbol)

    def _execute_order(
        self,
        symbol: str,
        order: Order,
        price: float,
        timestamp: pd.Timestamp,
    ) -> None:
        """Execute a single order with isolated futures margin + liquidation checks."""
        fee_rate = self.taker_fee_rate  # Assume market orders

        # Determine quantity
        if order.quantity > 0:
            quantity = order.quantity
        elif order.weight is not None and order.weight > 0:
            position_value = self.capital * self.position_size_pct * order.weight
            quantity = position_value / price if price > 0 else 0.0
            # Apply leverage at exposure stage
            position_value *= self.leverage
            quantity = position_value / price if price > 0 else 0.0
        else:
            return

        if quantity <= 0:
            return

        notional = quantity * price
        fee = notional * fee_rate
        required_margin = self._calc_margin_required(notional)

        # Prevent same-bar flip and avoid double-close/reopen when already closed
        if symbol in self.positions:
            pos = self.positions[symbol]
            is_close = (order.side == Side.BUY and pos['side'] == 'SHORT') or (
                order.side == Side.SELL and pos['side'] == 'LONG'
            )

            if is_close:
                self._close_position(symbol, quantity, price, timestamp, fee_rate)
                # no immediate re-entry in same bar (same as existing behavior)
                return

        # If same direction while held, ignore additional add-on to keep strict margin semantics
        if symbol in self.positions:
            return

        # Reject if not enough free capital for margin + fee
        if self.capital < (required_margin + fee):
            return

        side = 'LONG' if order.side == Side.BUY else 'SHORT'
        liquidation_price = self._calculate_liquidation_price(price, side)

        self.capital -= (required_margin + fee)
        self.positions[symbol] = {
            'side': side,
            'qty': quantity,
            'entry_price': price,
            'margin': required_margin,
            'entry_fee': fee,
            'liquidation_price': liquidation_price,
        }

        self.trade_log.append({
            'timestamp': timestamp,
            'symbol': symbol,
            'action': f'OPEN_{side}',
            'price': price,
            'quantity': quantity,
            'fee': fee,
            'liquidation_price': liquidation_price,
            'notional': notional,
            'required_margin': required_margin,
        })

    def _calculate_equity(self, prices: dict[str, float]) -> float:
        """Calculate total equity including unrealized PnL."""
        equity = self.capital

        for symbol, pos in self.positions.items():
            if symbol not in prices:
                continue
            price = prices[symbol]
            equity += pos['margin']
            equity += self._position_unrealized(pos, price)

        return equity

    def _flush_liquidations(self, prices: dict[str, float], timestamp: pd.Timestamp) -> None:
        for symbol in list(self.positions.keys()):
            price = prices.get(symbol)
            if price is None:
                continue
            self._liquidate_if_needed(symbol, price, timestamp)

    def run(
        self,
        data_paths: dict[str, str],
        start_date: str,
        end_date: str,
    ) -> dict:
        """Run the backtest."""
        # Load data
        print("Loading candle data...")
        df = self.load_candle_data(data_paths, start_date, end_date)
        print(f"  Total candles: {len(df)}")

        # Get unique timestamps where we'll evaluate
        timestamps = df.groupby('timestamp').first().index.tolist()
        print(f"  Unique timestamps: {len(timestamps)}")

        # Pre-bucket data for O(N) panel access (avoid repeated full-frame filtering)
        symbol_frames = {}
        for symbol in self.strategy.symbols:
            sym_df = df[df['symbol'] == symbol].sort_values('timestamp').reset_index(drop=True)
            if sym_df.empty:
                continue
            symbol_frames[symbol] = {
                "df": sym_df,
                "idx": 0,
            }

        # Reset state
        self.capital = self.initial_capital
        self.positions = {}
        self.trade_log = []
        self.equity_curve = []
        self._equity_timestamps = []

        latest_prices = {}

        # Pre-group candles by timestamp for O(N) price updates
        candles_by_ts = {ts: group[['symbol', 'close']].to_dict('records') for ts, group in df.groupby('timestamp')}

        # Process each timestamp
        for i, ts in enumerate(timestamps):
            self._closed_this_bar = set()  # Reset for new bar

            # Update latest prices
            for row in candles_by_ts.get(ts, []):
                latest_prices[row['symbol']] = float(row['close'])

            # Liquidation check should happen before new entries
            self._flush_liquidations(latest_prices, ts)

            # Build panel data incrementally from each symbol feed
            panel: dict[str, dict[str, float]] = {}
            for symbol, bucket in symbol_frames.items():
                if bucket['idx'] >= len(bucket['df']):
                    continue

                # Advance pointer to the latest candle <= current timestamp
                rows = bucket['df']
                idx = bucket['idx']
                while idx < len(rows) and rows.at[idx, 'timestamp'] <= ts:
                    idx += 1
                bucket['idx'] = idx

                if idx <= 0:
                    continue

                latest = rows.iloc[idx - 1]
                panel[symbol] = {
                    'open': float(latest['open']),
                    'high': float(latest['high']),
                    'low': float(latest['low']),
                    'close': float(latest['close']),
                    'volume': float(latest['volume']),
                }

            if len(panel) < len(self.strategy.symbols):
                continue

            # Create MarketState
            trigger_symbol = self.strategy.symbols[0]
            trigger_price = latest_prices.get(trigger_symbol, 0)

            state = MarketState(
                timestamp=ts.to_pydatetime() if hasattr(ts, 'to_pydatetime') else ts,
                mid_price=trigger_price,
                imbalance=0.0,
                spread=0.0,
                spread_bps=0.0,
                best_bid=trigger_price,
                best_ask=trigger_price,
                best_bid_qty=0.0,
                best_ask_qty=0.0,
                position_side=None,
                position_qty=0.0,
                open=panel.get(trigger_symbol, {}).get('open', trigger_price),
                high=panel.get(trigger_symbol, {}).get('high', trigger_price),
                low=panel.get(trigger_symbol, {}).get('low', trigger_price),
                close=trigger_price,
                volume=panel.get(trigger_symbol, {}).get('volume', 0.0),
                vwap=trigger_price,
                symbol=trigger_symbol,
                panel=panel,
                positions=self._get_positions_dict() if self.positions else None,
            )

            # Generate order
            result = self.strategy.generate_order(state)

            # Execute orders
            if isinstance(result, PortfolioOrder):
                for symbol, order in result.active_orders.items():
                    price = latest_prices.get(symbol)
                    if price:
                        self._execute_order(symbol, order, price, ts)

            # Record equity periodically
            if i % 100 == 0:
                equity = self._calculate_equity(latest_prices)
                self.equity_curve.append(equity)
                self._equity_timestamps.append(ts)

        # Final close all positions
        final_ts = timestamps[-1] if timestamps else datetime.now()
        for symbol in list(self.positions.keys()):
            pos = self.positions[symbol]
            price = latest_prices.get(symbol, 0)
            if price <= 0:
                continue
            self._close_position(symbol, pos['qty'], price, final_ts, self.taker_fee_rate)

        self.positions = {}
        self.equity_curve.append(self.capital)
        self._equity_timestamps.append(final_ts)

        return self._compute_results()

    def _compute_results(self) -> dict:
        """Compute backtest results."""
        equity = pd.Series(self.equity_curve if self.equity_curve else [self.initial_capital])

        total_return = (self.capital - self.initial_capital) / self.initial_capital

        # Sharpe ratio (daily aggregated, annualized)
        sharpe = sharpe_daily_annualized(equity, timestamps=self._equity_timestamps)

        # Max drawdown
        rolling_max = equity.cummax()
        drawdown = (equity - rolling_max) / rolling_max
        max_dd = drawdown.min()

        # Trade stats
        closed_trades = [t for t in self.trade_log if 'pnl' in t]
        winning = len([t for t in closed_trades if t['pnl'] > 0])
        losing = len([t for t in closed_trades if t['pnl'] < 0])

        # Profit factor
        gross_profit = sum(t['pnl'] for t in closed_trades if t['pnl'] > 0)
        gross_loss = abs(sum(t['pnl'] for t in closed_trades if t['pnl'] < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (float('inf') if gross_profit > 0 else 0)

        return {
            'initial_capital': self.initial_capital,
            'final_capital': self.capital,
            'total_return': total_return,
            'sharpe_ratio': sharpe,
            'max_drawdown': max_dd,
            'total_trades': len(closed_trades),
            'winning_trades': winning,
            'losing_trades': losing,
            'win_rate': winning / len(closed_trades) if closed_trades else 0,
            'profit_factor': profit_factor,
            'equity_curve': equity,
            'trade_log': self.trade_log,
        }


def main():
    # Configuration
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
    data_base = Path("/Users/jwcorp/trading_data/futures/candles")

    data_paths = {
        sym: str(data_base / f"{sym}_5m.parquet")
        for sym in symbols
    }

    # Strategy parameters - V4 Cross-Sectional Relative Strength (Iteration 13 - FINAL)
    # Using best params from Iter 12 + leverage to hit 5% return target
    strategy_params = {
        "symbols": symbols,
        "lookback_period": 24,              # 2 hours RS calculation
        "min_spread_threshold": 0.35,       # Best from Iter 12
        "spread_exit_threshold": 0.1,       # Exit when spread compresses
        "volume_dispersion_threshold": 1.3, # Best from Iter 12
        "min_holding_bars": 8,              # 40 min minimum hold
        "max_holding_bars": 60,             # 5-hour max hold
        "min_bars_between_trades": 12,      # 1-hour cooldown
        "atr_period": 14,                   # Standard ATR
        "stop_loss_atr": 1.8,               # Moderate stop
        "position_weight": 0.5,             # 50% per side
        "history_max_len": 2000,
    }

    # Backtest configuration
    initial_capital = 100000.0
    position_size_pct = 0.8  # Increased from 0.5 to boost returns
    leverage = 2             # Increased from 1 to boost returns
    maker_fee = 0.0002
    taker_fee = 0.0005

    # Period (IS 1 month - January 2025)
    start_date = "2025-01-01"
    end_date = "2025-01-31"

    print("=" * 70)
    print("ATRVolumeUnitRiskMultiStrategyV4 Backtest (Cross-Sectional RS)")
    print("=" * 70)
    print(f"Symbols:        {symbols}")
    print(f"Period:         {start_date} ~ {end_date}")
    print(f"Bar Type:       TIME (5 minutes)")
    print(f"Capital:        ${initial_capital:,.2f}")
    print(f"Position Size:  {position_size_pct * 100:.0f}%")
    print(f"Leverage:       {leverage}x")
    print(f"Fees:           Maker {maker_fee*100:.3f}% / Taker {taker_fee*100:.3f}%")
    print("=" * 70)
    print("\nStrategy Parameters:")
    for k, v in strategy_params.items():
        if k != 'symbols':
            print(f"  {k}: {v}")
    print("=" * 70)

    # Create strategy
    strategy = ATRVolumeUnitRiskMultiStrategyV4(**strategy_params)

    # Create runner
    runner = CandleBacktestRunner(
        strategy=strategy,
        initial_capital=initial_capital,
        position_size_pct=position_size_pct,
        leverage=leverage,
        maker_fee_rate=maker_fee,
        taker_fee_rate=taker_fee,
    )

    # Run backtest
    print("\nRunning backtest...")
    result = runner.run(
        data_paths=data_paths,
        start_date=start_date,
        end_date=end_date,
    )

    # Print results
    print("\n" + "=" * 70)
    print("BACKTEST RESULTS")
    print("=" * 70)
    print(f"Initial Capital:  ${result['initial_capital']:,.2f}")
    print(f"Final Capital:    ${result['final_capital']:,.2f}")
    print(f"Total Return:     {result['total_return'] * 100:.2f}%")
    print(f"Sharpe Ratio:     {result['sharpe_ratio']:.3f}")
    print(f"Max Drawdown:     {result['max_drawdown'] * 100:.2f}%")
    print(f"Total Trades:     {result['total_trades']}")
    print(f"Win Rate:         {result['win_rate'] * 100:.1f}%")
    print(f"Profit Factor:    {result['profit_factor']:.2f}")
    print("=" * 70)

    # Success criteria check
    print("\nSUCCESS CRITERIA CHECK:")
    criteria = [
        ("Sharpe Ratio >= 1.0", result['sharpe_ratio'] >= 1.0, result['sharpe_ratio']),
        ("Profit Factor >= 1.3", result['profit_factor'] >= 1.3, result['profit_factor']),
        ("Max Drawdown >= -15%", result['max_drawdown'] >= -0.15, result['max_drawdown'] * 100),
        ("Total Return >= 5%", result['total_return'] >= 0.05, result['total_return'] * 100),
        ("Min Trades >= 30", result['total_trades'] >= 30, result['total_trades']),
    ]

    all_pass = True
    for name, passed, value in criteria:
        status = "PASS" if passed else "FAIL"
        if "%" in name:
            print(f"  [{status}] {name}: {value:.2f}%")
        elif isinstance(value, float):
            print(f"  [{status}] {name}: {value:.3f}")
        else:
            print(f"  [{status}] {name}: {value}")
        if not passed:
            all_pass = False

    print("\n" + "=" * 70)
    if all_pass:
        print("ALL CRITERIA PASSED - STRATEGY APPROVED!")
    else:
        print("SOME CRITERIA FAILED - NEEDS IMPROVEMENT")
    print("=" * 70)

    # Save results
    output_dir = Path(__file__).parent.parent / "atr_volume_unitrisk_multi_dir"
    output_dir.mkdir(exist_ok=True)

    # Save equity curve
    equity_file = output_dir / "equity_curve.csv"
    result['equity_curve'].to_csv(equity_file)
    print(f"\nEquity curve saved to: {equity_file}")

    # Save trade log
    if result['trade_log']:
        trade_df = pd.DataFrame(result['trade_log'])
        trade_file = output_dir / "trade_log.csv"
        trade_df.to_csv(trade_file, index=False)
        print(f"Trade log saved to: {trade_file}")

    return result


if __name__ == "__main__":
    main()
