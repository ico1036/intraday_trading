"""Phase 3-1 — IntegrityTest (tick, overlapping windows).

Core algorithm: given N trade sets from N overlapping backtest runs + the
windows they covered, check that on pairwise shared time ranges the trades
are identical. Divergence = look-ahead bias or path dependency bug.

The tick runner adapter is a thin shim tested in integration; here we pin
the pure comparison algorithm.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from scripts.agent.v2.deterministic import integrity


UTC = timezone.utc


def _ts(day: int, hour: int = 12) -> datetime:
    return datetime(2025, 3, day, hour, 0, tzinfo=UTC)


def _trade(day: int, side: str, price: float, qty: float = 0.01, hour: int = 12):
    return integrity.TradeEvent(ts=_ts(day, hour), side=side, qty=qty, price=price)


# ---------------------------------------------------------------------------
# Base: identical trades in overlap → clean.
# ---------------------------------------------------------------------------


def test_identical_trades_in_overlap_is_clean():
    # Window A covers days 1-5, window B covers days 3-7. Overlap: 3-5.
    trades_a = [_trade(2, "BUY", 100.0), _trade(4, "SELL", 102.0)]
    trades_b = [_trade(4, "SELL", 102.0), _trade(6, "BUY", 105.0)]
    report = integrity.check(
        trade_sets=[trades_a, trades_b],
        windows=[(_ts(1).date(), _ts(5).date()), (_ts(3).date(), _ts(7).date())],
    )
    assert report.clean
    assert report.divergences == []
    assert (_ts(3).date(), _ts(5).date()) in report.shared_windows


def test_different_trades_in_overlap_is_divergent():
    # Same windows as above, but different trade in day 4.
    trades_a = [_trade(2, "BUY", 100.0), _trade(4, "SELL", 102.0)]
    trades_b = [_trade(4, "SELL", 103.0), _trade(6, "BUY", 105.0)]
    report = integrity.check(
        trade_sets=[trades_a, trades_b],
        windows=[(_ts(1).date(), _ts(5).date()), (_ts(3).date(), _ts(7).date())],
    )
    assert not report.clean
    assert len(report.divergences) == 1
    d = report.divergences[0]
    assert d.run_a == 0 and d.run_b == 1
    assert d.missing_in_b or d.extra_in_b  # trades differed


def test_missing_trade_in_overlap_is_divergent():
    trades_a = [_trade(4, "SELL", 102.0)]
    trades_b = []  # B somehow skipped the day-4 trade
    report = integrity.check(
        trade_sets=[trades_a, trades_b],
        windows=[(_ts(1).date(), _ts(5).date()), (_ts(3).date(), _ts(7).date())],
    )
    assert not report.clean
    assert report.divergences[0].missing_in_b


# ---------------------------------------------------------------------------
# Trades outside overlap are ignored.
# ---------------------------------------------------------------------------


def test_trades_outside_overlap_do_not_matter():
    # A has trade on day 2 (before overlap), B on day 6 (after). Overlap is 3-5.
    trades_a = [_trade(2, "BUY", 100.0)]
    trades_b = [_trade(6, "SELL", 105.0)]
    report = integrity.check(
        trade_sets=[trades_a, trades_b],
        windows=[(_ts(1).date(), _ts(5).date()), (_ts(3).date(), _ts(7).date())],
    )
    assert report.clean


# ---------------------------------------------------------------------------
# Three runs, pairwise.
# ---------------------------------------------------------------------------


def test_three_run_clean():
    t = _trade(5, "BUY", 100.0)
    report = integrity.check(
        trade_sets=[[t], [t], [t]],
        windows=[
            (_ts(1).date(), _ts(7).date()),
            (_ts(3).date(), _ts(9).date()),
            (_ts(4).date(), _ts(10).date()),
        ],
    )
    assert report.clean


def test_three_run_catches_one_pair():
    t_common = _trade(5, "BUY", 100.0)
    t_diff = _trade(5, "BUY", 100.5)  # same timestamp, different price
    report = integrity.check(
        trade_sets=[[t_common], [t_common], [t_diff]],
        windows=[
            (_ts(1).date(), _ts(7).date()),
            (_ts(3).date(), _ts(9).date()),
            (_ts(4).date(), _ts(10).date()),
        ],
    )
    assert not report.clean
    # run 0 vs run 2 AND run 1 vs run 2 should both diverge on day 5
    diverging_pairs = {(d.run_a, d.run_b) for d in report.divergences}
    assert (0, 2) in diverging_pairs
    assert (1, 2) in diverging_pairs


# ---------------------------------------------------------------------------
# Warmup ignores early divergences inside each window.
# ---------------------------------------------------------------------------


def test_warmup_ignores_early_trades_in_overlap():
    # Window A: days 1-10, Window B: days 5-15. Overlap: days 5-10.
    # Warmup 2 days → effective comparison window is day 7-10 for both.
    trades_a = [
        _trade(5, "BUY", 100.0),   # within warmup zone of B (day 5 = B.start + 0d)
        _trade(8, "SELL", 102.0),
    ]
    trades_b = [
        _trade(5, "SELL", 101.0),  # different but inside B's warmup → ignored
        _trade(8, "SELL", 102.0),
    ]
    report = integrity.check(
        trade_sets=[trades_a, trades_b],
        windows=[(_ts(1).date(), _ts(10).date()), (_ts(5).date(), _ts(15).date())],
        warmup=timedelta(days=2),
    )
    assert report.clean


# ---------------------------------------------------------------------------
# Non-overlapping windows.
# ---------------------------------------------------------------------------


def test_non_overlapping_windows_are_clean_but_flagged():
    trades_a = [_trade(2, "BUY", 100.0)]
    trades_b = [_trade(10, "SELL", 105.0)]
    report = integrity.check(
        trade_sets=[trades_a, trades_b],
        windows=[(_ts(1).date(), _ts(5).date()), (_ts(8).date(), _ts(12).date())],
    )
    assert report.clean
    assert report.shared_windows == []
    assert "no_overlap" in report.notes


# ---------------------------------------------------------------------------
# Report rendering.
# ---------------------------------------------------------------------------


def test_report_markdown_renders():
    trades_a = [_trade(4, "SELL", 102.0)]
    trades_b = [_trade(4, "SELL", 103.0)]
    report = integrity.check(
        trade_sets=[trades_a, trades_b],
        windows=[(_ts(1).date(), _ts(5).date()), (_ts(3).date(), _ts(7).date())],
    )
    md = integrity.render_markdown(report)
    assert "# Integrity Report" in md
    assert "DIVERGENT" in md or "divergence" in md.lower()


def test_clean_report_markdown_renders_as_pass():
    trades = [_trade(4, "SELL", 102.0)]
    report = integrity.check(
        trade_sets=[trades, trades],
        windows=[(_ts(1).date(), _ts(5).date()), (_ts(3).date(), _ts(7).date())],
    )
    md = integrity.render_markdown(report)
    assert "CLEAN" in md or "pass" in md.lower()


# ---------------------------------------------------------------------------
# Validation: mismatched input sizes.
# ---------------------------------------------------------------------------


def test_check_requires_equal_len_trade_sets_and_windows():
    with pytest.raises(integrity.IntegrityError):
        integrity.check(
            trade_sets=[[], []],
            windows=[(_ts(1).date(), _ts(5).date())],  # only 1 window
        )


def test_check_requires_at_least_two_runs():
    with pytest.raises(integrity.IntegrityError):
        integrity.check(
            trade_sets=[[]],
            windows=[(_ts(1).date(), _ts(5).date())],
        )


# ---------------------------------------------------------------------------
# TradeEvent canonical form used for equality.
# ---------------------------------------------------------------------------


def test_trade_event_canonical_rounds_price_and_qty():
    a = integrity.TradeEvent(ts=_ts(1), side="BUY", qty=0.0100000001, price=100.00004)
    b = integrity.TradeEvent(ts=_ts(1), side="BUY", qty=0.0100000000, price=100.00000)
    # Rounding tolerance: canonical strings match
    assert a.canonical() == b.canonical()


def test_trade_event_canonical_differs_on_side():
    a = integrity.TradeEvent(ts=_ts(1), side="BUY", qty=0.01, price=100.0)
    b = integrity.TradeEvent(ts=_ts(1), side="SELL", qty=0.01, price=100.0)
    assert a.canonical() != b.canonical()
