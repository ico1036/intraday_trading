"""Tests for dashboard support of forward split + LIVE indicator.

The dashboard already understands ``is/`` and ``os/`` splits. To support
running a live (forward) extension of a strategy, we add:

  - a ``forward/`` split sibling to ``is/`` and ``os/``
  - a ``pid.txt`` file inside ``forward/`` written by the forward runner
  - a LIVE indicator on the dashboard when ``pid.txt`` references a
    running process

These tests cover the pure-logic dashboard helpers. The forward runner
itself and the dashboard UI rendering are exercised via a separate
smoke test.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


_LIB_DIR = Path(__file__).resolve().parents[1] / "scripts" / "tools"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from alpha_dashboard_lib import (  # noqa: E402  (path-injected import)
    cumret_segment_offsets,
    discover_splits,
    format_uptime,
    forward_status,
    is_forward_live,
)


# --- discover_splits --------------------------------------------------------


def test_discover_splits_returns_is_when_only_is_present(tmp_path):
    alpha = tmp_path / "alphas" / "demo"
    (alpha / "is").mkdir(parents=True)
    (alpha / "is" / "metrics.json").write_text("{}")
    assert discover_splits(alpha) == ["is"]


def test_discover_splits_returns_is_os(tmp_path):
    alpha = tmp_path / "alphas" / "demo"
    for sp in ("is", "os"):
        (alpha / sp).mkdir(parents=True)
        (alpha / sp / "metrics.json").write_text("{}")
    assert discover_splits(alpha) == ["is", "os"]


def test_discover_splits_includes_forward_when_present(tmp_path):
    alpha = tmp_path / "alphas" / "demo"
    for sp in ("is", "os", "forward"):
        (alpha / sp).mkdir(parents=True)
        # forward does not require metrics.json — equity_curve.parquet is enough
    (alpha / "is" / "metrics.json").write_text("{}")
    (alpha / "os" / "metrics.json").write_text("{}")
    (alpha / "forward" / "equity_curve.parquet").write_bytes(b"")
    splits = discover_splits(alpha)
    assert splits == ["is", "os", "forward"]


def test_discover_splits_ignores_empty_dirs(tmp_path):
    alpha = tmp_path / "alphas" / "demo"
    (alpha / "is").mkdir(parents=True)
    (alpha / "is" / "metrics.json").write_text("{}")
    (alpha / "forward").mkdir()  # empty — should be ignored
    assert discover_splits(alpha) == ["is"]


# --- is_forward_live --------------------------------------------------------


def test_live_false_when_no_pid_file(tmp_path):
    forward_dir = tmp_path / "forward"
    forward_dir.mkdir()
    assert is_forward_live(forward_dir) is False


def test_live_false_when_forward_dir_missing(tmp_path):
    assert is_forward_live(tmp_path / "missing") is False


def test_live_true_when_pid_points_at_current_process(tmp_path):
    forward_dir = tmp_path / "forward"
    forward_dir.mkdir()
    (forward_dir / "pid.txt").write_text(str(os.getpid()))
    assert is_forward_live(forward_dir) is True


def test_live_false_when_pid_is_stale(tmp_path):
    """A PID that no longer maps to a running process must be treated as dead."""
    forward_dir = tmp_path / "forward"
    forward_dir.mkdir()
    # Find an unused high PID. PID 999999 is essentially guaranteed not to exist.
    (forward_dir / "pid.txt").write_text("999999")
    assert is_forward_live(forward_dir) is False


def test_live_false_when_pid_file_is_garbage(tmp_path):
    forward_dir = tmp_path / "forward"
    forward_dir.mkdir()
    (forward_dir / "pid.txt").write_text("not-a-number\n")
    assert is_forward_live(forward_dir) is False


# --- cumret_segment_offsets -------------------------------------------------


def test_offsets_default_zero_when_no_priors():
    assert cumret_segment_offsets(None, None) == {"is": 0.0, "os": 0.0, "forward": 0.0}


def test_offsets_only_is_present():
    """OS and Forward both start where IS ended."""
    assert cumret_segment_offsets(0.32, None) == {
        "is": 0.0, "os": 0.32, "forward": 0.32,
    }


def test_offsets_is_and_os_both_present():
    """Forward continues from OS end which itself continues from IS end."""
    assert cumret_segment_offsets(0.32, 0.30) == pytest.approx(
        {"is": 0.0, "os": 0.32, "forward": 0.62}
    )


def test_offsets_handles_negative_returns():
    """Negative IS still shifts subsequent segments down."""
    assert cumret_segment_offsets(-0.20, 0.10) == pytest.approx(
        {"is": 0.0, "os": -0.20, "forward": -0.10}
    )


# --- format_uptime ---------------------------------------------------------


def test_format_uptime_seconds():
    assert format_uptime(45) == "45s"


def test_format_uptime_minutes():
    assert format_uptime(125) == "2m 5s"


def test_format_uptime_hours():
    assert format_uptime(3725) == "1h 2m"


def test_format_uptime_days():
    assert format_uptime(90061) == "1d 1h"


def test_format_uptime_none():
    assert format_uptime(None) == "-"


# --- forward_status --------------------------------------------------------


def test_forward_status_when_no_dir(tmp_path):
    s = forward_status(tmp_path / "missing")
    assert s["live"] is False
    assert s["pid"] is None
    assert s["nav_current"] is None


def test_forward_status_with_live_pid_no_equity(tmp_path):
    forward_dir = tmp_path / "forward"
    forward_dir.mkdir()
    (forward_dir / "pid.txt").write_text(str(os.getpid()))
    s = forward_status(forward_dir)
    assert s["live"] is True
    assert s["pid"] == os.getpid()
    assert s["uptime_seconds"] is not None and s["uptime_seconds"] >= 0
    assert s["nav_current"] is None  # no equity_curve yet


def test_forward_status_with_dead_pid(tmp_path):
    forward_dir = tmp_path / "forward"
    forward_dir.mkdir()
    (forward_dir / "pid.txt").write_text("999999")
    s = forward_status(forward_dir)
    assert s["live"] is False
    assert s["pid"] is None  # treated as no live pid


def test_forward_status_with_equity_data(tmp_path):
    import pandas as pd
    from datetime import datetime as _dt
    forward_dir = tmp_path / "forward"
    forward_dir.mkdir()
    df = pd.DataFrame({
        "timestamp": [_dt(2026, 5, 15), _dt(2026, 5, 16)],
        "equity":   [10000.0, 10100.0],
    })
    df.to_parquet(forward_dir / "equity_curve.parquet")
    s = forward_status(forward_dir)
    assert s["nav_start"] == pytest.approx(10000.0)
    assert s["nav_current"] == pytest.approx(10100.0)
    assert s["today_pnl"] == pytest.approx(100.0)
    assert s["last_decision"] is not None


# --- forward_status: live session (post-OS) fields -------------------------


def test_forward_status_session_fields_populated_when_live(tmp_path):
    """When the runner is live, session_* fields summarize the post-OS
    (= full forward) segment: start ts, start equity, PnL, return.
    """
    import pandas as pd
    from datetime import datetime as _dt
    forward_dir = tmp_path / "forward"
    forward_dir.mkdir()
    (forward_dir / "pid.txt").write_text(str(os.getpid()))
    df = pd.DataFrame({
        "timestamp": [_dt(2026, 5, 15), _dt(2026, 5, 16), _dt(2026, 5, 17)],
        "equity":   [10000.0, 10050.0, 10200.0],
    })
    df.to_parquet(forward_dir / "equity_curve.parquet")
    s = forward_status(forward_dir)
    assert s["live"] is True
    assert s["session_equity_start"] == pytest.approx(10000.0)
    assert s["session_pnl"] == pytest.approx(200.0)
    assert s["session_return"] == pytest.approx(0.02)
    assert s["session_start"] is not None


def test_forward_status_session_fields_none_when_not_live(tmp_path):
    """If pid is dead/missing, session_* must stay None even if equity exists."""
    import pandas as pd
    from datetime import datetime as _dt
    forward_dir = tmp_path / "forward"
    forward_dir.mkdir()
    (forward_dir / "pid.txt").write_text("999999")  # dead pid
    df = pd.DataFrame({
        "timestamp": [_dt(2026, 5, 15), _dt(2026, 5, 16)],
        "equity":   [10000.0, 10100.0],
    })
    df.to_parquet(forward_dir / "equity_curve.parquet")
    s = forward_status(forward_dir)
    assert s["live"] is False
    assert s["session_pnl"] is None
    assert s["session_return"] is None
    assert s["session_equity_start"] is None
    assert s["session_start"] is None


# --- Sharpe formatters: daily vs yearly ------------------------------------


def test_fmt_sharpe_daily_divides_by_sqrt252():
    """Stored value is annualized; daily formatter divides by sqrt(252)."""
    import math
    import sys as _sys
    from pathlib import Path as _Path
    _here = _Path(__file__).resolve().parents[1] / "scripts" / "tools"
    if str(_here) not in _sys.path:
        _sys.path.insert(0, str(_here))
    from alpha_dashboard import _fmt_sharpe_daily, _fmt_sharpe_annual, _fmt_sharpe_pair

    # 0.91 (annualized) → 0.91 / sqrt(252) ≈ 0.057
    daily = _fmt_sharpe_daily(0.91)
    assert daily == f"{0.91 / math.sqrt(252):.3f}"

    yearly = _fmt_sharpe_annual(0.91)
    assert yearly == "0.910"

    pair = _fmt_sharpe_pair(0.91)
    assert pair == f"{daily} / {yearly}"


def test_fmt_sharpe_handles_none_and_nan():
    import sys as _sys
    from pathlib import Path as _Path
    _here = _Path(__file__).resolve().parents[1] / "scripts" / "tools"
    if str(_here) not in _sys.path:
        _sys.path.insert(0, str(_here))
    from alpha_dashboard import _fmt_sharpe_daily, _fmt_sharpe_annual, _fmt_sharpe_pair

    assert _fmt_sharpe_daily(None) == "-"
    assert _fmt_sharpe_annual(None) == "-"
    assert _fmt_sharpe_pair(None) == "- / -"
    assert _fmt_sharpe_daily(float("nan")) == "-"
    assert _fmt_sharpe_annual(float("nan")) == "-"
