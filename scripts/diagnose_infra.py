#!/usr/bin/env python3
"""
Infrastructure Diagnostic Tool

Automatically diagnoses common infrastructure issues in the trading system.
Run this when:
- Orders are generated but not executing
- Strategy produces no signals
- PnL calculations seem wrong
- System runs but produces no meaningful output

Usage:
    python scripts/diagnose_infra.py
    python scripts/diagnose_infra.py --verbose
    python scripts/diagnose_infra.py --test-strategy VolumeImbalanceStrategy
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def check_enum_identity():
    """
    CRITICAL CHECK: Verify enum classes are not duplicated.

    Python enums with same values but different classes will NOT compare equal.
    This causes silent failures where order.order_type == OrderType.MARKET returns False.
    """
    print("\n" + "=" * 60)
    print("CHECK 1: Enum Identity (CRITICAL)")
    print("=" * 60)

    issues = []

    try:
        from intraday.strategy import OrderType as OT1, Side as S1
        from intraday.strategies.base import OrderType as OT2, Side as S2

        # Check if they're the same class (not just same values)
        if OT1 is not OT2:
            issues.append({
                "severity": "CRITICAL",
                "component": "OrderType enum",
                "issue": "OrderType is defined in multiple places",
                "impact": "Orders will NEVER execute (comparison always fails)",
                "fix": "In strategies/base.py, use: from ..strategy import OrderType",
                "evidence": f"id(strategy.OrderType)={id(OT1)} != id(base.OrderType)={id(OT2)}"
            })
        else:
            print("✅ OrderType: Same class (OK)")

        if S1 is not S2:
            issues.append({
                "severity": "CRITICAL",
                "component": "Side enum",
                "issue": "Side is defined in multiple places",
                "impact": "Position tracking will fail",
                "fix": "In strategies/base.py, use: from ..strategy import Side",
                "evidence": f"id(strategy.Side)={id(S1)} != id(base.Side)={id(S2)}"
            })
        else:
            print("✅ Side: Same class (OK)")

        # Test actual comparison
        if OT1 is OT2:
            test_result = OT1.MARKET == OT2.MARKET
            print(f"✅ OrderType.MARKET == OrderType.MARKET: {test_result}")

    except ImportError as e:
        issues.append({
            "severity": "ERROR",
            "component": "Import",
            "issue": f"Failed to import: {e}",
            "impact": "Cannot verify enum identity",
            "fix": "Check import paths"
        })

    return issues


def check_order_pipeline(verbose=False):
    """
    Trace an order through the entire pipeline to find where it fails.
    """
    print("\n" + "=" * 60)
    print("CHECK 2: Order Execution Pipeline")
    print("=" * 60)

    issues = []

    try:
        from intraday import PaperTrader, Side, OrderType, Order

        trader = PaperTrader(initial_capital=10000.0, fee_rate=0.001)

        # Create test order
        order = Order(
            side=Side.BUY,
            quantity=0.01,
            order_type=OrderType.MARKET,
            limit_price=None
        )

        print(f"\n1. Order created: {order}")
        print(f"   order.order_type = {order.order_type}")
        print(f"   type(order.order_type) = {type(order.order_type)}")

        # Submit order
        order_id = trader.submit_order(order, timestamp=datetime.now())
        print(f"\n2. Order submitted: ID={order_id}")
        print(f"   Pending orders: {len(trader.pending_orders)}")

        # Check balance
        print(f"\n3. Balance check:")
        print(f"   USD balance: ${trader.usd_balance:,.2f}")
        print(f"   Required: ${50000 * 0.01 * 1.001:,.2f} (for 0.01 BTC @ $50k)")

        # Try to execute
        print(f"\n4. Attempting execution...")

        # Simulate price update
        trade = trader.on_price_update(
            price=50000.0,
            best_bid=49990.0,
            best_ask=50000.0,
            timestamp=datetime.now() + timedelta(milliseconds=100),
            latency_ms=50.0
        )

        if trade:
            print(f"   ✅ Trade executed: {trade.side.value} @ ${trade.price:,.2f}")
        else:
            print(f"   ❌ Trade NOT executed")

            # Diagnose why
            if trader.pending_orders:
                pending = trader.pending_orders[0]
                print(f"\n   Diagnosing failure...")
                print(f"   - Order still pending: {pending.order_id}")
                print(f"   - Order type: {pending.order.order_type}")
                print(f"   - Expected type: {OrderType.MARKET}")
                print(f"   - Type match: {pending.order.order_type == OrderType.MARKET}")
                print(f"   - Is same class: {type(pending.order.order_type) is type(OrderType.MARKET)}")

                if type(pending.order.order_type) is not type(OrderType.MARKET):
                    issues.append({
                        "severity": "CRITICAL",
                        "component": "Order Pipeline",
                        "issue": "OrderType class mismatch in pipeline",
                        "impact": "Market orders never execute",
                        "fix": "Ensure single OrderType definition",
                        "evidence": f"Order uses {type(pending.order.order_type).__module__}.OrderType"
                    })
            else:
                print(f"   - Order was removed from queue (unknown reason)")

    except Exception as e:
        issues.append({
            "severity": "ERROR",
            "component": "Order Pipeline",
            "issue": f"Exception during test: {e}",
            "impact": "Cannot verify order pipeline",
            "fix": "Check stack trace"
        })
        if verbose:
            import traceback
            traceback.print_exc()

    return issues


def check_backtest_pipeline(verbose=False):
    """
    Run a minimal backtest and verify each stage produces output.
    """
    print("\n" + "=" * 60)
    print("CHECK 3: Backtest Pipeline")
    print("=" * 60)

    issues = []

    try:
        from intraday import (
            TickBacktestRunner, TickDataLoader,
            VolumeImbalanceStrategy, BarType
        )

        data_dir = Path("./data/ticks")
        if not data_dir.exists():
            print("⚠️  No tick data found. Skipping backtest pipeline check.")
            print(f"   Expected: {data_dir}")
            return issues

        loader = TickDataLoader(data_dir, symbol="BTCUSDT")
        print(f"✅ Data loaded: {loader.file_count} file(s)")

        strategy = VolumeImbalanceStrategy(quantity=0.01)
        print(f"✅ Strategy created: {strategy.__class__.__name__}")

        runner = TickBacktestRunner(
            strategy=strategy,
            data_loader=loader,
            bar_type=BarType.VOLUME,
            bar_size=10.0,
            initial_capital=10000.0,
            latency_ms=50.0,
        )

        # Run for 1 hour
        start = datetime(2024, 1, 1, 0, 0, 0)
        end = start + timedelta(hours=1)

        print(f"\nRunning backtest: {start} to {end}")
        report = runner.run(start_time=start, end_time=end, progress_interval=100000)

        # Analyze results
        print(f"\n--- Pipeline Statistics ---")
        print(f"Ticks processed: {runner._tick_count:,}")
        print(f"Bars generated:  {runner._bar_count:,}")
        print(f"Orders submitted: {runner._order_count}")
        print(f"Trades executed: {runner._trade_count}")

        # Check for issues
        if runner._tick_count == 0:
            issues.append({
                "severity": "ERROR",
                "component": "Data Loader",
                "issue": "No ticks processed",
                "impact": "No data flowing through pipeline",
                "fix": "Check data files and time range"
            })

        if runner._bar_count == 0 and runner._tick_count > 0:
            issues.append({
                "severity": "WARNING",
                "component": "CandleBuilder",
                "issue": "Ticks processed but no bars generated",
                "impact": "Strategy never receives signals",
                "fix": "Check bar_size (might be too large)"
            })

        if runner._order_count == 0 and runner._bar_count > 0:
            issues.append({
                "severity": "WARNING",
                "component": "Strategy",
                "issue": "Bars generated but no orders",
                "impact": "Strategy conditions never met",
                "fix": "Check strategy thresholds vs actual data distribution"
            })

        if runner._trade_count == 0 and runner._order_count > 0:
            issues.append({
                "severity": "CRITICAL",
                "component": "PaperTrader",
                "issue": "Orders submitted but no trades",
                "impact": "Orders failing to execute",
                "fix": "Check enum identity, balance, latency"
            })

        # Calculate execution rate
        if runner._order_count > 0:
            exec_rate = runner._trade_count / runner._order_count * 100
            print(f"\nExecution rate: {exec_rate:.1f}%")
            if exec_rate < 50:
                print(f"⚠️  Low execution rate - investigate order failures")

        print(f"\n--- Performance ---")
        print(f"Total Return: {report.total_return:+.2f}%")
        print(f"Win Rate: {report.win_rate:.1f}%")
        print(f"Max Drawdown: {report.max_drawdown:.2f}%")

    except FileNotFoundError as e:
        print(f"⚠️  Data not found: {e}")
    except Exception as e:
        issues.append({
            "severity": "ERROR",
            "component": "Backtest Pipeline",
            "issue": f"Exception: {e}",
            "impact": "Cannot verify backtest pipeline",
            "fix": "Check stack trace"
        })
        if verbose:
            import traceback
            traceback.print_exc()

    return issues


def check_data_characteristics(verbose=False):
    """
    Analyze data to help tune strategy parameters.
    """
    print("\n" + "=" * 60)
    print("CHECK 4: Data Characteristics")
    print("=" * 60)

    issues = []

    try:
        from intraday import TickDataLoader, CandleBuilder, CandleType

        data_dir = Path("./data/ticks")
        if not data_dir.exists():
            print("⚠️  No tick data found. Skipping.")
            return issues

        loader = TickDataLoader(data_dir, symbol="BTCUSDT")
        builder = CandleBuilder(CandleType.VOLUME, bar_size=10.0)

        # Collect sample candles
        candles = []
        start = datetime(2024, 1, 1, 0, 0, 0)
        end = start + timedelta(hours=1)

        for trade in loader.iter_trades(start_time=start, end_time=end):
            candle = builder.update(trade)
            if candle:
                candles.append(candle)

        if not candles:
            print("⚠️  No candles generated in sample period")
            return issues

        # Analyze
        price_changes = []
        ranges_bps = []
        imbalances = []

        prev_close = None
        for c in candles:
            if prev_close:
                change_pct = (c.close - prev_close) / prev_close * 100
                price_changes.append(change_pct)
            prev_close = c.close

            range_bps = (c.high - c.low) / c.close * 10000
            ranges_bps.append(range_bps)
            imbalances.append(c.volume_imbalance)

        print(f"\nSample: {len(candles)} candles from {start} to {end}")

        if price_changes:
            print(f"\n--- Price Change (%) ---")
            print(f"  Min: {min(price_changes):.4f}%")
            print(f"  Max: {max(price_changes):.4f}%")
            print(f"  Avg: {sum(price_changes)/len(price_changes):.4f}%")

            # Check if normalization thresholds are appropriate
            max_change = max(abs(c) for c in price_changes)
            print(f"\n  Suggested trend normalization: {max_change * 2:.4f}% (2x max)")
            if max_change < 0.1:
                print(f"  ⚠️  Very small price changes - may need 10bps (0.1%) normalization")

        if ranges_bps:
            print(f"\n--- Range (bps) ---")
            print(f"  Min: {min(ranges_bps):.2f} bps")
            print(f"  Max: {max(ranges_bps):.2f} bps")
            print(f"  Avg: {sum(ranges_bps)/len(ranges_bps):.2f} bps")

            avg_range = sum(ranges_bps) / len(ranges_bps)
            print(f"\n  Suggested volatility normalization: {avg_range * 2:.2f} bps")

        if imbalances:
            print(f"\n--- Volume Imbalance ---")
            print(f"  Min: {min(imbalances):.3f}")
            print(f"  Max: {max(imbalances):.3f}")
            print(f"  Avg: {sum(imbalances)/len(imbalances):.3f}")

            # Distribution
            above_03 = sum(1 for i in imbalances if i > 0.3) / len(imbalances) * 100
            below_m03 = sum(1 for i in imbalances if i < -0.3) / len(imbalances) * 100
            print(f"\n  > 0.3: {above_03:.1f}% of bars")
            print(f"  < -0.3: {below_m03:.1f}% of bars")

            if above_03 < 5 and below_m03 < 5:
                print(f"  ⚠️  Very few bars exceed ±0.3 threshold - consider lowering")

    except Exception as e:
        if verbose:
            import traceback
            traceback.print_exc()

    return issues


def print_report(all_issues):
    """Print final diagnostic report."""
    print("\n")
    print("=" * 60)
    print("DIAGNOSTIC REPORT")
    print("=" * 60)

    if not all_issues:
        print("\n✅ No issues found!")
        return

    # Group by severity
    critical = [i for i in all_issues if i["severity"] == "CRITICAL"]
    errors = [i for i in all_issues if i["severity"] == "ERROR"]
    warnings = [i for i in all_issues if i["severity"] == "WARNING"]

    if critical:
        print(f"\n🔴 CRITICAL ({len(critical)}):")
        for i in critical:
            print(f"\n   Component: {i['component']}")
            print(f"   Issue: {i['issue']}")
            print(f"   Impact: {i['impact']}")
            print(f"   Fix: {i['fix']}")
            if "evidence" in i:
                print(f"   Evidence: {i['evidence']}")

    if errors:
        print(f"\n🟠 ERRORS ({len(errors)}):")
        for i in errors:
            print(f"\n   Component: {i['component']}")
            print(f"   Issue: {i['issue']}")
            print(f"   Fix: {i['fix']}")

    if warnings:
        print(f"\n🟡 WARNINGS ({len(warnings)}):")
        for i in warnings:
            print(f"\n   Component: {i['component']}")
            print(f"   Issue: {i['issue']}")
            print(f"   Fix: {i['fix']}")


def main():
    parser = argparse.ArgumentParser(description="Infrastructure Diagnostic Tool")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()

    print("=" * 60)
    print("INFRASTRUCTURE DIAGNOSTIC TOOL")
    print("=" * 60)
    print(f"Time: {datetime.now()}")

    all_issues = []

    # Run all checks
    all_issues.extend(check_enum_identity())
    all_issues.extend(check_order_pipeline(args.verbose))
    all_issues.extend(check_backtest_pipeline(args.verbose))
    all_issues.extend(check_data_characteristics(args.verbose))

    # Print report
    print_report(all_issues)

    # Exit code
    critical_count = sum(1 for i in all_issues if i["severity"] == "CRITICAL")
    sys.exit(1 if critical_count > 0 else 0)


if __name__ == "__main__":
    main()
