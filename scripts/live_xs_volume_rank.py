#!/usr/bin/env python3
"""Preflight, plan, and execute xs_volume_rank on Binance USDⓈ-M Futures.

Safe defaults:
  * no flag places an order;
  * ``--execute`` additionally requires ``--confirm LIVE``;
  * a kill-switch file, stale signal, open orders, hedge mode, foreign
    positions, risk-limit violation, or repeated signal fingerprint aborts.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from intraday.live import (
    BinanceFuturesClient,
    ExecutionConfig,
    build_order_plan,
    load_target_weights,
)
from intraday.live.execution import signal_fingerprint


REPO = Path(__file__).resolve().parents[1]
DEFAULT_WEIGHTS = (
    REPO
    / "archive/run_2026_05_xs500/alphas/xs_volume_rank/forward/weights.parquet"
)
DEFAULT_CONFIG = REPO / "config/live_xs_volume_rank.json"
DEFAULT_STATE_DIR = REPO / "live/state/xs_volume_rank"
KILL_SWITCH = REPO / "live/KILL_SWITCH"


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _usdt_available(balances: list[dict[str, Any]]) -> Decimal:
    for row in balances:
        if str(row.get("asset", "")).upper() == "USDT":
            return Decimal(str(row.get("availableBalance", "0")))
    raise RuntimeError("USDT futures balance not found")


def _client_order_id(run_id: str, index: int, symbol: str) -> str:
    return f"xsvr-{run_id[:12]}-{index:03d}-{symbol[:8]}"[:36]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    parser.add_argument("--testnet", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv(REPO / ".env")
    if KILL_SWITCH.exists():
        raise RuntimeError(f"kill switch is active: {KILL_SWITCH}")
    if args.execute and args.confirm != "LIVE":
        raise RuntimeError("live execution requires --execute --confirm LIVE")

    config = ExecutionConfig.from_json(args.config)
    signal_ts, weights = load_target_weights(
        args.weights, max_age_hours=config.max_signal_age_hours
    )
    fingerprint = signal_fingerprint(args.weights)
    run_id = f"{signal_ts.strftime('%Y%m%d')}-{fingerprint}"
    completed_path = args.state_dir / f"{run_id}.completed.json"
    started_path = args.state_dir / f"{run_id}.started.json"
    if completed_path.exists():
        raise RuntimeError(f"signal was already executed: {completed_path}")
    if started_path.exists():
        raise RuntimeError(
            f"an earlier execution may be incomplete; reconcile manually: {started_path}"
        )

    api_key = os.environ.get("BINANCE_FUTURES_API_KEY", "")
    api_secret = os.environ.get("BINANCE_FUTURES_API_SECRET", "")
    base_url = (
        BinanceFuturesClient.TESTNET_URL
        if args.testnet
        else BinanceFuturesClient.MAINNET_URL
    )
    client = BinanceFuturesClient(api_key, api_secret, base_url=base_url)

    if client.is_hedge_mode():
        raise RuntimeError("account must use one-way position mode")
    open_orders = client.open_orders()
    if open_orders:
        raise RuntimeError(f"cancel existing open orders first: {len(open_orders)}")
    balances = client.balances()
    available = _usdt_available(balances)
    if available < config.deployment_usdt:
        raise RuntimeError(
            f"available USDT {available} is below deployment_usdt "
            f"{config.deployment_usdt}"
        )

    rules = client.symbol_rules()
    prices = client.mark_prices()
    positions = client.positions()
    plan = build_order_plan(
        weights=weights,
        current_positions=positions,
        mark_prices=prices,
        rules=rules,
        config=config,
    )
    report = {
        "ok": True,
        "mode": "testnet" if args.testnet else "mainnet",
        "execute": bool(args.execute),
        "signal_timestamp": signal_ts,
        "signal_fingerprint": fingerprint,
        "deployment_usdt": config.deployment_usdt,
        "available_usdt": available,
        "n_targets": len(weights),
        "n_orders": len(plan),
        "gross_weight": sum(abs(v) for v in weights.values()),
        "net_weight": sum(weights.values()),
        "orders": [asdict(intent) for intent in plan],
    }

    if not args.execute:
        print(json.dumps(_jsonable(report), indent=2))
        return 0

    args.state_dir.mkdir(parents=True, exist_ok=True)
    started_path.write_text(
        json.dumps(
            _jsonable({**report, "started_at": datetime.now(timezone.utc)}),
            indent=2,
        )
    )

    # Enforce isolated 1x leverage before any exposure-changing order.
    for symbol in sorted(weights):
        client.set_leverage(symbol, 1)

    # Reduce exposure before increasing or opening exposure. This also makes
    # direction flips safe: the reduce-only leg necessarily runs first.
    execution_plan = sorted(plan, key=lambda intent: (not intent.reduce_only, intent.symbol))
    responses = []
    for index, intent in enumerate(execution_plan):
        response = client.market_order(
            symbol=intent.symbol,
            side=intent.side,
            quantity=intent.quantity,
            reduce_only=intent.reduce_only,
            client_order_id=_client_order_id(run_id, index, intent.symbol),
        )
        status = str(response.get("status", ""))
        if status not in {"FILLED", "NEW"}:
            raise RuntimeError(
                f"order did not reach an accepted state: {intent.symbol} {status}"
            )
        responses.append(response)
        # Stay below Binance's short-window order-rate limit with headroom.
        time.sleep(0.05)

    remaining = client.positions()
    residuals: dict[str, str] = {}
    for intent in plan:
        actual = remaining.get(intent.symbol, Decimal("0"))
        target = intent.target_qty
        price = prices[intent.symbol]
        if abs(actual - target) * price > config.position_tolerance_usdt:
            residuals[intent.symbol] = str(actual - target)
    if residuals:
        raise RuntimeError(f"post-trade reconciliation failed: {residuals}")

    completed = {
        **report,
        "completed_at": datetime.now(timezone.utc),
        "responses": responses,
        "final_positions": remaining,
    }
    completed_path.write_text(json.dumps(_jsonable(completed), indent=2))
    print(json.dumps(_jsonable(completed), indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        raise SystemExit(2)
