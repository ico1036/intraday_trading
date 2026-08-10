from __future__ import annotations

from decimal import Decimal

import pandas as pd
import pytest

from intraday.live.binance_futures import SymbolRules
from intraday.live.execution import (
    ExecutionConfig,
    build_order_plan,
    load_target_weights,
)


def _rule(symbol: str) -> SymbolRules:
    return SymbolRules(
        symbol=symbol,
        status="TRADING",
        contract_type="PERPETUAL",
        step_size=Decimal("0.001"),
        min_qty=Decimal("0.001"),
        max_qty=Decimal("1000000"),
        min_notional=Decimal("5"),
    )


def _config(**overrides) -> ExecutionConfig:
    values = {
        "deployment_usdt": Decimal("2000"),
        "max_gross": Decimal("1.01"),
        "max_abs_net": Decimal("0.02"),
        "max_symbol_weight": Decimal("0.6"),
        "max_orders": 10,
        "max_order_notional": Decimal("1100"),
    }
    values.update(overrides)
    return ExecutionConfig(**values)


def test_load_target_weights_selects_latest_and_rejects_stale(tmp_path):
    path = tmp_path / "weights.parquet"
    pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2026-07-30 00:00:00", "2026-07-31 00:00:00", "2026-07-31 00:00:00"]
            ),
            "symbol": ["OLDUSDT", "BTCUSDT", "ETHUSDT"],
            "target_weight": [1.0, 0.5, -0.5],
        }
    ).to_parquet(path)

    ts, weights = load_target_weights(
        path, now=pd.Timestamp("2026-07-31 12:00:00", tz="UTC")
    )
    assert ts == pd.Timestamp("2026-07-31 00:00:00", tz="UTC")
    assert weights == {"BTCUSDT": Decimal("0.5"), "ETHUSDT": Decimal("-0.5")}

    with pytest.raises(ValueError, match="stale signal"):
        load_target_weights(
            path,
            now=pd.Timestamp("2026-08-03 00:00:00", tz="UTC"),
            max_age_hours=36,
        )


def test_build_order_plan_quantizes_and_reconciles_deltas():
    weights = {"BTCUSDT": Decimal("0.5"), "ETHUSDT": Decimal("-0.5")}
    prices = {"BTCUSDT": Decimal("100"), "ETHUSDT": Decimal("50")}
    rules = {symbol: _rule(symbol) for symbol in weights}
    current = {"BTCUSDT": Decimal("4"), "ETHUSDT": Decimal("-25")}

    plan = build_order_plan(
        weights=weights,
        current_positions=current,
        mark_prices=prices,
        rules=rules,
        config=_config(),
    )

    assert [(p.symbol, p.side, p.quantity, p.reduce_only) for p in plan] == [
        ("BTCUSDT", "BUY", Decimal("6"), False),
        ("ETHUSDT", "BUY", Decimal("5"), True),
    ]


def test_build_order_plan_splits_direction_flip_into_reduce_then_open():
    plan = build_order_plan(
        weights={"BTCUSDT": Decimal("-0.5"), "ETHUSDT": Decimal("0.5")},
        current_positions={"BTCUSDT": Decimal("2")},
        mark_prices={"BTCUSDT": Decimal("100"), "ETHUSDT": Decimal("50")},
        rules={"BTCUSDT": _rule("BTCUSDT"), "ETHUSDT": _rule("ETHUSDT")},
        config=_config(),
    )

    btc = [p for p in plan if p.symbol == "BTCUSDT"]
    assert [(p.side, p.quantity, p.reduce_only) for p in btc] == [
        ("SELL", Decimal("2"), True),
        ("SELL", Decimal("10"), False),
    ]


def test_build_order_plan_refuses_unmanaged_positions():
    with pytest.raises(ValueError, match="unmanaged open positions"):
        build_order_plan(
            weights={"BTCUSDT": Decimal("0.5"), "ETHUSDT": Decimal("-0.5")},
            current_positions={"DOGEUSDT": Decimal("1")},
            mark_prices={"BTCUSDT": Decimal("100"), "ETHUSDT": Decimal("50")},
            rules={"BTCUSDT": _rule("BTCUSDT"), "ETHUSDT": _rule("ETHUSDT")},
            config=_config(),
        )


def test_build_order_plan_enforces_gross_and_symbol_caps():
    with pytest.raises(ValueError, match="gross weight"):
        build_order_plan(
            weights={"BTCUSDT": Decimal("0.7"), "ETHUSDT": Decimal("-0.7")},
            current_positions={},
            mark_prices={"BTCUSDT": Decimal("100"), "ETHUSDT": Decimal("50")},
            rules={"BTCUSDT": _rule("BTCUSDT"), "ETHUSDT": _rule("ETHUSDT")},
            config=_config(max_symbol_weight=Decimal("1")),
        )
