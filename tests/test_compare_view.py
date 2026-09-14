"""Compare view data layer: window slicing, costs, bundle, table rows."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_HERE = Path(__file__).resolve().parents[1] / "scripts" / "tools"
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
import alpha_dashboard_lib as L  # noqa: E402


@pytest.fixture
def archive(tmp_path: Path) -> Path:
    run = tmp_path / "run_x"
    (run / "alphas" / "a1").mkdir(parents=True)
    (run / "alphas" / "a1" / "forward").mkdir()
    (run / "composites" / "c1").mkdir(parents=True)
    (run / "splits.json").write_text(json.dumps({
        "is": {"start": "2024-01-01 00:00:00", "end": "2024-01-20 23:59:00"},
        "os": {"start": "2024-01-21 00:00:00", "end": "2024-02-09 23:59:00"},
    }))
    days = pd.date_range("2024-01-01", periods=40, freq="D")
    rng = np.random.default_rng(0)
    for d in (run / "alphas" / "a1", run / "composites" / "c1"):
        eq = 10000 + np.cumsum(rng.normal(3, 30, 40))
        pd.DataFrame({"timestamp": days, "equity": eq}).to_parquet(d / "equity_curve.parquet", index=False)
        pd.DataFrame({"timestamp": days, "symbol": "X", "action": "CLOSE_LONG", "price": 1.0, "quantity": 1.0,
                      "pnl": rng.normal(0, 1, 40), "fee": 0.5, "slippage": 0.25}).to_parquet(d / "trades.parquet", index=False)
        pd.DataFrame({"timestamp": days, "symbol": "X", "side": "LONG", "rate": 1e-4, "settlements": 3,
                      "notional": 100.0, "payment": -0.1}).to_parquet(d / "funding.parquet", index=False)
        (d / "metrics.json").write_text(json.dumps({"initial_capital": 10000.0, "sharpe": 1.0}))
    fwd = run / "alphas" / "a1" / "forward"
    fdays = pd.date_range("2024-02-10", periods=10, freq="D")
    pd.DataFrame({"timestamp": fdays, "equity": 10000 + np.arange(10) * 5.0}).to_parquet(fwd / "equity_curve.parquet", index=False)
    (fwd / "metrics.json").write_text(json.dumps({"initial_capital": 10000.0}))
    (run / "composites" / "c1" / "manifest.json").write_text(json.dumps({"composite_id": "c1", "target_gross": 5.0}))
    return tmp_path


def test_window_bounds_and_daily_equity(archive: Path):
    splits = json.loads((archive / "run_x" / "splits.json").read_text())
    d = L.compare_item_dir(archive, "run_x", "alpha", "a1")
    assert L.compare_daily_equity(d, "is", splits).index.max().date().isoformat() == "2024-01-20"
    os_eq = L.compare_daily_equity(d, "os", splits)
    assert os_eq.index.min().date().isoformat() == "2024-01-21" and len(os_eq) == 20
    assert len(L.compare_daily_equity(d, "full", splits)) == 40
    assert len(L.compare_daily_equity(d, "forward", splits)) == 10
    assert L.compare_daily_equity(L.compare_item_dir(archive, "run_x", "composite", "c1"), "forward", splits).empty


def test_window_costs_are_sliced(archive: Path):
    splits = json.loads((archive / "run_x" / "splits.json").read_text())
    d = L.compare_item_dir(archive, "run_x", "alpha", "a1")
    c_is = L.compare_window_costs(d, "is", splits)
    c_full = L.compare_window_costs(d, "full", splits)
    assert c_is["trades"] == 20 and c_full["trades"] == 40
    assert c_is["fees"] == pytest.approx(10.0) and c_full["fees"] == pytest.approx(20.0)
    assert c_is["slippage"] == pytest.approx(5.0)
    assert c_is["funding"] == pytest.approx(-2.0) and c_full["funding"] == pytest.approx(-4.0)


def test_returns_metrics_and_alignment():
    idx = pd.date_range("2024-01-01", periods=30, freq="D")
    eq = pd.Series(10000.0 + np.arange(30) * 10.0, index=idx)
    r = L.compare_daily_returns(eq, 10000.0, "simple")
    assert r.iloc[0] == pytest.approx(0.001) and len(r) == 29
    m = L.compare_metrics(r, "simple")
    assert m["cum"] == pytest.approx(0.029) and m["mdd"] == pytest.approx(0.0) and m["cagr"] == pytest.approx(0.365)
    rc = L.compare_daily_returns(eq, 10000.0, "compound")
    assert L.compare_metrics(rc, "compound")["cum"] == pytest.approx(0.029)
    aligned = L.compare_align({"a": r, "b": r.iloc[10:], "c": pd.Series(dtype=float)})
    assert list(aligned.columns) == ["a", "b"] and len(aligned) == 19


def test_bundle_rows_and_corr(archive: Path):
    keys = ["run_x/alpha/a1", "run_x/composite/c1", "run_x/alpha/missing", "bad-key"]
    b = L.compare_series_bundle(archive, keys, "os", "simple")
    assert set(b) == {"run_x/alpha/a1", "run_x/composite/c1", "run_x/alpha/missing"}
    assert b["run_x/alpha/missing"]["reason"] == "no OS data" and b["run_x/alpha/missing"]["returns"].empty
    aligned = L.compare_align({k: v["returns"] for k, v in b.items()})
    assert aligned.shape == (19, 2)
    rows = L.compare_table_rows(b, aligned, "simple", "os")
    assert [r["name"] for r in rows] == ["a1", "c1", "1/N blend of selection"]
    # costs narrowed to the common window: 19 aligned days of the 20-day OS
    assert rows[0]["fees"] == "-0.10%" and rows[0]["slippage"] == "-0.05%" and rows[0]["funding"] == "-0.02%"
    assert L.compare_table_rows(b, aligned, "simple", "os", include_blend=False)[-1]["name"] == "c1"
    corr = L.compare_corr(aligned)
    assert corr.shape == (2, 2) and corr.iloc[0, 0] == pytest.approx(1.0)


def test_options_and_keys():
    df = pd.DataFrame({"run_id": ["r", "r"], "alpha_id": ["a", "b"]})
    opts = L.compare_options(df, [{"run_id": "r", "dir_name": "c", "composite_id": "c"}])
    assert set(opts) == {"r/alpha/a", "r/alpha/b", "r/composite/c"}
    assert L.parse_compare_key("r/composite/c") == ("r", "composite", "c") and L.parse_compare_key("nope") is None
    assert L.compare_url(["r/alpha/a"], "os", "simple", True) == "/compare?ids=r/alpha/a&window=os&basis=simple&btc=1"
    assert L.compare_url(["r/alpha/a"], "all", blend=False).endswith("&blend=0")


def test_all_window_stitches_on_returns_and_marks_boundaries(archive: Path):
    splits = json.loads((archive / "run_x" / "splits.json").read_text())
    d = L.compare_item_dir(archive, "run_x", "alpha", "a1")
    r_all = L.compare_returns_for_window(d, "all", splits, 10000.0, "simple")
    r_full = L.compare_returns_for_window(d, "full", splits, 10000.0, "simple")
    r_fwd = L.compare_returns_for_window(d, "forward", splits, 10000.0, "simple")
    # 39 full-period returns + 9 forward returns; the level jump between the two replays is not a return
    assert len(r_all) == len(r_full) + len(r_fwd) == 48
    assert r_all.index.is_monotonic_increasing and not r_all.index.duplicated().any()
    assert r_all.loc["2024-02-11"] == pytest.approx(5.0 / 10000.0)
    b = L.compare_boundaries(splits)
    assert b["is_os"].date().isoformat() == "2024-01-21" and b["os_forward"].date().isoformat() == "2024-02-09"
    bundle = L.compare_series_bundle(archive, ["run_x/alpha/a1"], "all", "simple")
    aligned = L.compare_align({k: v["returns"] for k, v in bundle.items()})
    lines = L.compare_boundary_lines(bundle, aligned, "all")
    assert [lbl for _, lbl in lines] == ["IS | OS", "OS | Forward"]
    assert [lbl for _, lbl in L.compare_boundary_lines(bundle, aligned, "os")] == []
    costs = L.compare_window_costs(d, "all", splits)
    assert costs["trades"] == 40 and costs["fees"] == pytest.approx(20.0)


def test_daily_caches_key_on_mtime(archive: Path):
    d = L.compare_item_dir(archive, "run_x", "alpha", "a1")
    a = L._daily_equity(d); b = L._daily_equity(d)
    assert a is b  # same file, same mtime -> cached object
    assert L._daily_costs(d).shape[0] == 40


def test_window_note_names_the_limiting_strategy(archive: Path):
    keys = ["run_x/alpha/a1", "run_x/composite/c1"]   # c1 has no forward run
    b = L.compare_series_bundle(archive, keys, "all", "simple")
    aligned = L.compare_align({k: v["returns"] for k, v in b.items()})
    note = L.compare_window_note(b, aligned)
    assert "end 2024-02-09 set by c1" in note and "start" not in note
    assert L.compare_window_note(b, L.compare_align({"run_x/alpha/a1": b["run_x/alpha/a1"]["returns"]})) == ""


def test_windows_table_has_a_band_per_window_and_a_row_per_strategy(archive: Path):
    keys = ["run_x/alpha/a1", "run_x/composite/c1"]
    table = L.compare_windows_table(archive, keys, "simple", include_blend=True)
    assert [b["key"] for b in table["bands"]] == ["is", "os", "forward", "all"]
    is_band, os_band, fwd_band, all_band = table["bands"]
    # daily returns start on the second equity day, so a 20-day split has 19 return days
    assert (is_band["start"], is_band["end"], is_band["days"]) == ("2024-01-02", "2024-01-20", 19)
    assert os_band["days"] == 19 and fwd_band["days"] == 9
    assert all_band["days"] == 39  # 40 equity days -> 39 returns; the composite has no forward run, so All stops at OS
    assert [(r["name"], r["kind"]) for r in table["rows"]] == [("a1", "alpha"), ("c1", "composite"), ("1/N blend of selection", "blend")]
    a1, c1, blend = (r["windows"] for r in table["rows"])
    assert set(a1) == {"is", "os", "forward", "all"}
    assert set(c1) == {"is", "os", "all"}            # nothing to show under Forward
    assert set(blend) == {"is", "os", "all"}         # a blend needs two strategies in the band
    # a band's cells are the single-window rows for that band, so the two views agree
    b = L.compare_series_bundle(archive, keys, "os", "simple")
    single = L.compare_table_rows(b, L.compare_align({k: v["returns"] for k, v in b.items()}), "simple", "os")
    assert a1["os"] == single[0] and c1["os"]["fees"] == single[1]["fees"]
    without = L.compare_windows_table(archive, keys, "simple", include_blend=False)
    assert all(r["kind"] != "blend" for r in without["rows"])


def test_rows_say_what_capital_the_shares_refer_to(archive: Path):
    keys = ["run_x/alpha/a1", "run_x/composite/c1"]
    b = L.compare_series_bundle(archive, keys, "os", "simple")
    assert b["run_x/alpha/a1"]["gross"] is None and b["run_x/composite/c1"]["gross"] == 5.0
    rows = L.compare_table_rows(b, L.compare_align({k: v["returns"] for k, v in b.items()}), "simple", "os")
    assert [r["capital"] for r in rows] == ["10,000 USD", "10,000 USD · gross 5", "-"]
    table = L.compare_windows_table(archive, keys, "simple")
    assert [r["capital"] for r in table["rows"]] == ["10,000 USD", "10,000 USD · gross 5", "-"]
    assert L.format_capital(None) == "-" and L.format_capital(25000.0, 1.0) == "25,000 USD · gross 1"
