from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tools.alpha_dashboard_lib import (
    _fmt_bps,
    _fmt_duration_days,
    _fmt_int,
    _fmt_num,
    _fmt_pct,
    _fmt_turnover,
    _is_pass_eligible,
    _series_downsample,
    compute_drawdown_metrics,
    compute_net_pnl_bps,
    compute_turnover,
)


# ---------- formatters ----------


def test_fmt_pct():
    assert _fmt_pct(0.05) == "5.00%"
    assert _fmt_pct(-0.012) == "-1.20%"
    assert _fmt_pct(None) == "-"
    assert _fmt_pct(float("nan")) == "-"


def test_fmt_num():
    assert _fmt_num(1.234567) == "1.235"
    assert _fmt_num(None) == "-"


def test_fmt_int():
    assert _fmt_int(12345) == "12,345"
    assert _fmt_int(None) == "-"


def test_fmt_bps_sign_and_format():
    assert _fmt_bps(44.5) == "+44.50 bps"
    assert _fmt_bps(-3.0) == "-3.00 bps"
    assert _fmt_bps(0) == "+0.00 bps"
    assert _fmt_bps(None) == "-"


def test_fmt_duration_days():
    assert _fmt_duration_days(0.25) == "6.0h"
    assert _fmt_duration_days(2.5) == "2.5d"
    assert _fmt_duration_days(None) == "-"


def test_fmt_turnover():
    assert _fmt_turnover(12.34) == "12.34x"
    assert _fmt_turnover(None) == "-"


# ---------- IS_PASS gate ----------


def test_is_pass_all_gates_clear():
    assert _is_pass_eligible(
        0.7, 150, 50,
        sharpe_threshold=0.6, min_trades=100, min_turnover=10,
    )


def test_is_pass_fails_sharpe():
    assert not _is_pass_eligible(
        0.5, 150, 50,
        sharpe_threshold=0.6, min_trades=100, min_turnover=10,
    )


def test_is_pass_fails_trades():
    assert not _is_pass_eligible(
        0.7, 50, 50,
        sharpe_threshold=0.6, min_trades=100, min_turnover=10,
    )


def test_is_pass_fails_turnover():
    assert not _is_pass_eligible(
        0.7, 150, 5,
        sharpe_threshold=0.6, min_trades=100, min_turnover=10,
    )


def test_is_pass_none_inputs():
    assert not _is_pass_eligible(
        None, 150, 50,
        sharpe_threshold=0.6, min_trades=100, min_turnover=10,
    )
    assert not _is_pass_eligible(
        0.7, None, 50,
        sharpe_threshold=0.6, min_trades=100, min_turnover=10,
    )
    assert not _is_pass_eligible(
        0.7, 150, None,
        sharpe_threshold=0.6, min_trades=100, min_turnover=10,
    )


def test_is_pass_boundary_inclusive():
    # threshold met exactly should pass
    assert _is_pass_eligible(
        0.6, 100, 10.0,
        sharpe_threshold=0.6, min_trades=100, min_turnover=10,
    )


# ---------- compute_drawdown_metrics ----------


def test_drawdown_simple_recovery():
    # peak at 110 (day 1), trough at 95 (day 4), recovery at 110 (day 6)
    idx = pd.date_range("2026-01-01", periods=8, freq="D")
    eq = pd.Series([100, 110, 105, 100, 95, 100, 110, 120], index=idx, dtype=float)
    max_dd, dur, peak_ts, recov_ts = compute_drawdown_metrics(eq)
    assert max_dd == pytest.approx((95 - 110) / 110)  # ~ -0.1364
    assert dur == pytest.approx(5.0)  # day 1 -> day 6
    assert "2026-01-02" in peak_ts
    assert "2026-01-07" in recov_ts


def test_drawdown_no_recovery_uses_end():
    idx = pd.date_range("2026-01-01", periods=4, freq="D")
    eq = pd.Series([100, 110, 80, 90], index=idx, dtype=float)
    max_dd, dur, peak_ts, recov_ts = compute_drawdown_metrics(eq)
    assert max_dd == pytest.approx((80 - 110) / 110)
    # peak = day 1 (110), recovery never happens, so end-of-series day 3 is used
    assert dur == pytest.approx(2.0)


def test_drawdown_monotonic_up_zero_dd():
    idx = pd.date_range("2026-01-01", periods=5, freq="D")
    eq = pd.Series([100, 101, 102, 103, 104], index=idx, dtype=float)
    max_dd, dur, _, _ = compute_drawdown_metrics(eq)
    assert max_dd == pytest.approx(0.0)
    assert dur == pytest.approx(0.0)  # peak == bottom == recovery


def test_drawdown_empty_returns_nones():
    assert compute_drawdown_metrics(pd.Series(dtype=float)) == (None, None, None, None)
    assert compute_drawdown_metrics(pd.Series([1.0])) == (None, None, None, None)


# ---------- compute_net_pnl_bps ----------


def _make_trades(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_net_bps_simple_case():
    # 2 round trips on BTCUSDT
    # T1: open @ 100 qty=1 (notional 100), close @ 102, gross=2, open_fee=0.05, close_fee=0.051
    #     net = 2 - 0.05 - 0.051 = 1.899; bps = 189.9
    # T2: open @ 200 qty=1 (notional 200), close @ 198, gross=-2, open_fee=0.1, close_fee=0.099
    #     net = -2 - 0.1 - 0.099 = -2.199; bps = -109.95
    rows = [
        {"timestamp": pd.Timestamp("2026-01-01 00:00"), "symbol": "BTCUSDT",
         "action": "OPEN_LONG",  "price": 100.0, "quantity": 1.0, "fee": 0.05, "pnl": None},
        {"timestamp": pd.Timestamp("2026-01-01 00:30"), "symbol": "BTCUSDT",
         "action": "CLOSE_LONG", "price": 102.0, "quantity": None, "fee": 0.051, "pnl": 2.0},
        {"timestamp": pd.Timestamp("2026-01-02 00:00"), "symbol": "BTCUSDT",
         "action": "OPEN_SHORT", "price": 200.0, "quantity": 1.0, "fee": 0.1, "pnl": None},
        {"timestamp": pd.Timestamp("2026-01-02 00:30"), "symbol": "BTCUSDT",
         "action": "CLOSE_SHORT", "price": 198.0, "quantity": None, "fee": 0.099, "pnl": -2.0},
    ]
    simple, weighted, n = compute_net_pnl_bps(_make_trades(rows))
    assert n == 2
    # simple = (189.9 + (-109.95)) / 2 = 39.975
    assert simple == pytest.approx(39.975)
    # weighted = (1.899 + (-2.199)) / (100 + 200) * 10000 = -10.0
    assert weighted == pytest.approx(-10.0)


def test_net_bps_empty_returns_nones():
    out = compute_net_pnl_bps(pd.DataFrame(columns=["action"]))
    assert out == (None, None, 0)
    assert compute_net_pnl_bps(pd.DataFrame()) == (None, None, 0)


def test_net_bps_uses_open_leg_notional_not_close():
    # Notional must come from OPEN leg (price * qty), independent of close fields.
    rows = [
        {"timestamp": pd.Timestamp("2026-01-01 00:00"), "symbol": "ETHUSDT",
         "action": "OPEN_LONG",  "price": 1000.0, "quantity": 1.0, "fee": 0.5, "pnl": None},
        {"timestamp": pd.Timestamp("2026-01-01 01:00"), "symbol": "ETHUSDT",
         "action": "CLOSE_LONG", "price": 1010.0, "quantity": None, "fee": 0.505, "pnl": 10.0},
    ]
    simple, weighted, n = compute_net_pnl_bps(_make_trades(rows))
    assert n == 1
    # net = 10 - 0.5 - 0.505 = 8.995; bps = 8.995/1000 * 10000 = 89.95
    assert simple == pytest.approx(89.95)
    assert weighted == pytest.approx(89.95)  # only one trade, simple==weighted


# ---------- compute_turnover ----------


def test_turnover_basic():
    # row 0 vs implicit zero start: |0.5| + |0.0| = 0.5
    # row 0 -> row 1: |0.3-0.5| + |-0.2-0| = 0.2 + 0.2 = 0.4
    # row 1 -> row 2: |0-0.3| + |-0.2-(-0.2)| = 0.3
    # total = 1.2
    pivot = pd.DataFrame({"BTC": [0.5, 0.3, 0.0], "ETH": [0.0, -0.2, -0.2]})
    assert compute_turnover(pivot) == pytest.approx(1.2)


def test_turnover_empty():
    assert compute_turnover(pd.DataFrame()) is None


# ---------- _series_downsample ----------


def test_series_downsample_no_op_when_short():
    s = pd.Series(range(50))
    assert len(_series_downsample(s, max_points=100)) == 50


def test_series_downsample_reduces():
    s = pd.Series(range(1000))
    out = _series_downsample(s, max_points=100)
    assert len(out) <= 110  # roughly 100 with possible step rounding
