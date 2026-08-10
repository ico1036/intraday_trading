"""Pure planning and validation for target-weight live execution."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from pathlib import Path

import pandas as pd

from .binance_futures import SymbolRules


@dataclass(frozen=True)
class ExecutionConfig:
    deployment_usdt: Decimal
    max_gross: Decimal = Decimal("1.01")
    max_abs_net: Decimal = Decimal("0.02")
    max_symbol_weight: Decimal = Decimal("0.01")
    max_orders: int = 400
    max_order_notional: Decimal = Decimal("1000")
    max_signal_age_hours: int = 36
    position_tolerance_usdt: Decimal = Decimal("2")

    @classmethod
    def from_json(cls, path: Path) -> "ExecutionConfig":
        raw = json.loads(path.read_text())
        return cls(
            deployment_usdt=Decimal(str(raw["deployment_usdt"])),
            max_gross=Decimal(str(raw.get("max_gross", "1.01"))),
            max_abs_net=Decimal(str(raw.get("max_abs_net", "0.02"))),
            max_symbol_weight=Decimal(str(raw.get("max_symbol_weight", "0.01"))),
            max_orders=int(raw.get("max_orders", 400)),
            max_order_notional=Decimal(str(raw.get("max_order_notional", "1000"))),
            max_signal_age_hours=int(raw.get("max_signal_age_hours", 36)),
            position_tolerance_usdt=Decimal(
                str(raw.get("position_tolerance_usdt", "2"))
            ),
        )


@dataclass(frozen=True)
class OrderIntent:
    symbol: str
    side: str
    quantity: Decimal
    reduce_only: bool
    target_qty: Decimal
    current_qty: Decimal


def signal_fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def load_target_weights(
    path: Path,
    *,
    now: pd.Timestamp | None = None,
    max_age_hours: int = 36,
) -> tuple[pd.Timestamp, dict[str, Decimal]]:
    if not path.exists():
        raise FileNotFoundError(path)
    frame = pd.read_parquet(path, columns=["timestamp", "symbol", "target_weight"])
    if frame.empty:
        raise ValueError("weights artifact is empty")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    latest = frame["timestamp"].max()
    clock = now or pd.Timestamp.now(tz="UTC")
    if clock.tzinfo is None:
        clock = clock.tz_localize("UTC")
    if latest > clock + pd.Timedelta(minutes=5):
        raise ValueError(f"signal timestamp is in the future: {latest}")
    age = clock - latest
    if age > pd.Timedelta(hours=max_age_hours):
        raise ValueError(f"stale signal: {latest} ({age} old)")
    rows = frame[frame["timestamp"] == latest].copy()
    rows["symbol"] = rows["symbol"].astype(str).str.upper()
    if rows["symbol"].duplicated().any():
        raise ValueError("latest weights contain duplicate symbols")
    weights = {
        row.symbol: Decimal(str(row.target_weight))
        for row in rows.itertuples(index=False)
    }
    return latest, weights


def _floor_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def validate_weights(weights: dict[str, Decimal], config: ExecutionConfig) -> None:
    gross = sum((abs(v) for v in weights.values()), Decimal("0"))
    net = sum(weights.values(), Decimal("0"))
    if gross > config.max_gross:
        raise ValueError(f"gross weight {gross} exceeds {config.max_gross}")
    if abs(net) > config.max_abs_net:
        raise ValueError(f"net weight {net} exceeds ±{config.max_abs_net}")
    oversized = {s: w for s, w in weights.items() if abs(w) > config.max_symbol_weight}
    if oversized:
        raise ValueError(f"symbol weight limit exceeded: {oversized}")


def build_order_plan(
    *,
    weights: dict[str, Decimal],
    current_positions: dict[str, Decimal],
    mark_prices: dict[str, Decimal],
    rules: dict[str, SymbolRules],
    config: ExecutionConfig,
) -> list[OrderIntent]:
    validate_weights(weights, config)
    managed = set(weights)
    foreign = {s: q for s, q in current_positions.items() if s not in managed and q != 0}
    if foreign:
        raise ValueError(f"unmanaged open positions present: {sorted(foreign)}")

    target_qty: dict[str, Decimal] = {}
    for symbol, weight in weights.items():
        rule = rules.get(symbol)
        price = mark_prices.get(symbol)
        if rule is None or not rule.tradable:
            raise ValueError(f"symbol is not a tradable perpetual: {symbol}")
        if price is None or price <= 0:
            raise ValueError(f"missing mark price: {symbol}")
        raw = config.deployment_usdt * weight / price
        qty = _floor_step(abs(raw), rule.step_size)
        if qty < rule.min_qty or qty * price < rule.min_notional:
            qty = Decimal("0")
        signed = qty if raw > 0 else -qty
        if abs(signed * price) > config.max_order_notional:
            raise ValueError(f"target notional exceeds per-symbol cap: {symbol}")
        target_qty[symbol] = signed

    intents: list[OrderIntent] = []
    for symbol in sorted(set(target_qty) | set(current_positions)):
        current = current_positions.get(symbol, Decimal("0"))
        target = target_qty.get(symbol, Decimal("0"))
        rule = rules[symbol]
        if current != 0 and target != 0 and (current > 0) != (target > 0):
            intents.append(
                OrderIntent(
                    symbol, "SELL" if current > 0 else "BUY",
                    _floor_step(abs(current), rule.step_size), True, target, current,
                )
            )
            intents.append(
                OrderIntent(
                    symbol, "BUY" if target > 0 else "SELL",
                    abs(target), False, target, Decimal("0"),
                )
            )
            continue
        delta = target - current
        qty = _floor_step(abs(delta), rule.step_size)
        price = mark_prices[symbol]
        if qty < rule.min_qty or qty * price < rule.min_notional:
            continue
        intents.append(
            OrderIntent(
                symbol=symbol,
                side="BUY" if delta > 0 else "SELL",
                quantity=qty,
                reduce_only=(target == 0 or abs(target) < abs(current)),
                target_qty=target,
                current_qty=current,
            )
        )
    if len(intents) > config.max_orders:
        raise ValueError(f"order count {len(intents)} exceeds cap {config.max_orders}")
    return intents
