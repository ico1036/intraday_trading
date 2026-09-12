"""Feature panel of the funding tail filter: no lookahead, extension invariant."""
from __future__ import annotations

import numpy as np
import pandas as pd

from intraday.funding_filter import FEATURES, build_features, refit_boundaries


def _synthetic(n_days=80, syms=("AAA", "BBB", "CCC"), seed=0):
    rng = np.random.default_rng(seed)
    days = pd.date_range("2024-01-01", periods=n_days, freq="D")
    R = pd.DataFrame(rng.normal(1e-4, 5e-4, (n_days, len(syms))), index=days, columns=syms)
    FIRST = pd.DataFrame(rng.normal(1e-4, 2e-4, (n_days, len(syms))), index=days, columns=syms)
    NSET = pd.DataFrame(np.where(rng.random((n_days, len(syms))) < 0.5, 3, 6), index=days, columns=syms)
    px = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, (n_days, len(syms))), axis=0))
    OP = pd.DataFrame(px, index=days, columns=syms)
    CL = OP * (1 + rng.normal(0, 0.01, OP.shape))
    HI = np.maximum(OP, CL) * 1.01
    LO = np.minimum(OP, CL) * 0.99
    QV = pd.DataFrame(rng.lognormal(14, 0.5, (n_days, len(syms))), index=days, columns=syms)
    return R, FIRST, NSET, OP, HI, LO, CL, QV


def test_extension_invariance():
    full = _synthetic()
    X_full, y_full, is4_full = build_features(*full)
    cut = pd.Timestamp("2024-03-01")
    trunc = tuple(df.loc[:cut] for df in full)
    X_cut, y_cut, is4_cut = build_features(*trunc)
    common = X_cut.index
    pd.testing.assert_frame_equal(X_full.loc[common], X_cut, check_like=True)
    pd.testing.assert_series_equal(is4_full.loc[common], is4_cut)
    assert list(X_full.columns) == FEATURES


def test_no_lookahead_in_features():
    full = list(_synthetic())
    X0, _, _ = build_features(*full)
    day = pd.Timestamp("2024-02-15")
    # Perturb everything strictly after `day`: features on and before it must not move.
    for i, df in enumerate(full):
        d = df.copy()
        d.loc[d.index > day] = d.loc[d.index > day] * 3.0 + 1.0
        full[i] = d
    X1, _, _ = build_features(*full)
    idx = X0.index[X0.index.get_level_values("dt") <= day]
    pd.testing.assert_frame_equal(X0.loc[idx], X1.loc[idx], check_like=True)
    # Perturbing the same day's later settlements (total R) must not move features
    # either, but `first` (the 00:00 settlement) is part of the day's row.
    R = full[0].copy()
    R.loc[day] = R.loc[day] * 5.0
    X2, y2, _ = build_features(R, *full[1:])
    pd.testing.assert_frame_equal(X1.loc[idx], X2.loc[idx], check_like=True)
    assert (y2.xs(day, level="dt") != build_features(*full)[1].xs(day, level="dt")).all()


def test_refit_boundaries():
    b = refit_boundaries("2023-03-02", pd.Timestamp("2026-09-12"))
    assert [x.date().isoformat() for x in b][:4] == ["2023-03-02", "2023-10-20", "2024-04-20", "2024-10-20"]
    assert all((b[i + 1] - b[i]).days >= 90 for i in range(len(b) - 1))
