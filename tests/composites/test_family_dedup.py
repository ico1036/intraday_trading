"""Tests for family_key / family_dedup parameter-sweep collapse logic."""
from __future__ import annotations

from intraday.composites._optim_helpers import family_dedup, family_key


def test_family_key_signal_dir_collapses_window_and_concentration() -> None:
    base = family_key("xs_factor_atrproxy14d_rev_c40", level="signal_dir")
    assert base == ("xs_factor_atrproxy", "rev")
    # All windows and K values collapse to the same key
    for aid in (
        "xs_factor_atrproxy7d_rev_c20",
        "xs_factor_atrproxy14d_rev_c50",
        "xs_factor_atrproxy21d_rev_c40",
    ):
        assert family_key(aid, level="signal_dir") == base


def test_family_key_signal_window_dir_preserves_window() -> None:
    a = family_key("xs_factor_atrproxy7d_rev_c40", level="signal_window_dir")
    b = family_key("xs_factor_atrproxy14d_rev_c40", level="signal_window_dir")
    assert a == ("xs_factor_atrproxy7d", "rev")
    assert b == ("xs_factor_atrproxy14d", "rev")
    assert a != b
    # Different K values within same (signal, window, dir) collapse
    assert family_key("xs_factor_atrproxy14d_rev_c50",
                      level="signal_window_dir") == b


def test_family_key_fwd_vs_rev_are_distinct() -> None:
    fwd = family_key("xs_factor_atrproxy14d_fwd_c40")
    rev = family_key("xs_factor_atrproxy14d_rev_c40")
    assert fwd != rev


def test_family_key_non_zoo_alpha_is_singleton() -> None:
    a = family_key("xs_volume_rank")
    b = family_key("ts_donchian_trend_5d10d")
    assert a == ("__individual__", "xs_volume_rank")
    assert b == ("__individual__", "ts_donchian_trend_5d10d")
    assert a != b


def test_family_key_handles_compound_signal_names() -> None:
    # acceldiff520 = generator collapses "accel_diff_5_20"; trailing 520 strips
    assert family_key("xs_factor_acceldiff520_fwd_c10",
                      level="signal_dir") == ("xs_factor_acceldiff", "fwd")
    # closezscore252d → strip "252d" → closezscore
    assert family_key("xs_factor_closezscore252d_rev_c30",
                      level="signal_dir") == ("xs_factor_closezscore", "rev")


def test_family_dedup_keeps_highest_metric_per_family() -> None:
    alphas = [
        "xs_factor_atrproxy7d_rev_c20",   # IS 0.31
        "xs_factor_atrproxy14d_rev_c40",  # IS 0.59 — best
        "xs_factor_atrproxy21d_rev_c50",  # IS 0.37
        "xs_factor_amihud60d_fwd_c20",    # different family
        "xs_volume_rank",                  # singleton
    ]
    metric = {
        "xs_factor_atrproxy7d_rev_c20":   0.31,
        "xs_factor_atrproxy14d_rev_c40":  0.59,
        "xs_factor_atrproxy21d_rev_c50":  0.37,
        "xs_factor_amihud60d_fwd_c20":    1.98,
        "xs_volume_rank":                 0.91,
    }
    kept = family_dedup(alphas, metric, level="signal_dir")
    assert "xs_factor_atrproxy14d_rev_c40" in kept
    assert "xs_factor_atrproxy7d_rev_c20" not in kept
    assert "xs_factor_atrproxy21d_rev_c50" not in kept
    assert "xs_factor_amihud60d_fwd_c20" in kept
    assert "xs_volume_rank" in kept
    assert len(kept) == 3


def test_family_dedup_signal_window_dir_keeps_window_variants() -> None:
    alphas = [
        "xs_factor_atrproxy7d_rev_c40",
        "xs_factor_atrproxy7d_rev_c50",
        "xs_factor_atrproxy14d_rev_c40",
    ]
    metric = {a: i for i, a in enumerate(alphas)}
    kept = family_dedup(alphas, metric, level="signal_window_dir")
    # 7d and 14d are separate families; within 7d, c50 wins (higher metric)
    assert "xs_factor_atrproxy7d_rev_c50" in kept
    assert "xs_factor_atrproxy14d_rev_c40" in kept
    assert "xs_factor_atrproxy7d_rev_c40" not in kept
    assert len(kept) == 2


def test_family_dedup_preserves_input_order_for_first_appearance() -> None:
    alphas = [
        "xs_volume_rank",
        "xs_factor_atrproxy14d_rev_c40",
        "xs_factor_amihud60d_fwd_c20",
    ]
    metric = {a: 1.0 for a in alphas}
    kept = family_dedup(alphas, metric)
    assert kept == alphas


def test_family_dedup_missing_metric_defaults_to_neg_inf() -> None:
    alphas = ["xs_factor_atrproxy7d_rev_c20", "xs_factor_atrproxy14d_rev_c40"]
    metric = {"xs_factor_atrproxy7d_rev_c20": 0.3}  # second alpha missing
    kept = family_dedup(alphas, metric)
    assert kept == ["xs_factor_atrproxy7d_rev_c20"]
