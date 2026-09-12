"""Funding tail filter: predict tomorrow's funding per symbol and name the
shorts that would pay a tail rate.

This is the live implementation of the frozen rule in
``research/notes/funding_tail_filter_v1_prereg.md`` (see also
``research/notes/funding_tail_onset.md`` for why it exists). Per symbol-day
it predicts the day's total funding (bps) from 23 features of past funding,
past price/volume, and the day's 00:00 settlement, with one gradient-boosted
model per settlement regime (8h vs 4h-or-faster). Models are refit on an
expanding window at fixed calendar boundaries. A short whose prediction is
below ``threshold_bps`` is dropped from the short leg for that day.

Timing. The strategy decides day T+1's book at T+1 00:00 UTC. Every feature
for row (T+1, sym) is built from bars and settlements dated <= T, plus the
T+1 00:00 settlement (``first``), which is published at that moment. Where the
research features used the *same-day* settlement count (not observable at the
open), this implementation uses the previous day's count. The label is the
day's realized total, so a model refit at boundary B trains on rows dated
< B, whose labels were complete by B 00:00.

Extension invariance: the feature panel is a function of trailing windows
only, so a row's features do not change when later data is appended. The
test suite checks this on synthetic data.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from intraday.data.funding_loader import DEFAULT_FUNDING_PATH, load_funding_daily

log = logging.getLogger(__name__)

DEFAULT_KLINES_PATH = Path("data/futures_klines_daily_pit")
DEFAULT_MODEL_DIR = Path("data/funding_filter_models")

FEATURES = [
    "lag1", "lag2", "lag3", "lag5", "ma5", "ma20", "sd20", "min5", "min20",
    "first", "first_x_n", "first_vs_lag",
    "volrel", "volrel5", "ret1", "ret5", "ret20", "vol20", "range", "drawdown",
    "logadv", "xs_rank_fund", "xs_rank_vol",
]
HYPERPARAMS = dict(
    n_estimators=300, max_depth=6, learning_rate=0.05, subsample=0.8,
    colsample_bytree=0.8, min_child_weight=20, reg_lambda=2.0,
    tree_method="hist", n_jobs=8, random_state=0,
)
THRESHOLD_BPS = -80.0
SEED_END = "2023-03-02"          # first day the filter is allowed to act
REFIT_MONTH_DAYS = ((4, 20), (10, 20))  # calendar refit boundaries after the seed
MIN_TRAIN_CELLS = 5000
REGIME_NSET = 6                  # >= 6 settlements/day yesterday -> "4h" regime


def refit_boundaries(seed_end: str | pd.Timestamp, last: pd.Timestamp) -> list[pd.Timestamp]:
    """``seed_end`` then every Apr-20 / Oct-20 at least 90 days after the previous boundary."""
    seed = pd.Timestamp(seed_end)
    out = [seed]
    for y in range(seed.year, last.year + 2):
        for m, d in REFIT_MONTH_DAYS:
            b = pd.Timestamp(year=y, month=m, day=d)
            if b > out[-1] + pd.Timedelta(days=90) and b <= last + pd.Timedelta(days=366):
                out.append(b)
    return out


def load_kline_panels(symbols: list[str], klines_path: Path | str) -> dict[str, pd.DataFrame]:
    root = Path(klines_path)
    cols = ["timestamp", "open", "high", "low", "close", "quote_volume"]
    parts: dict[str, list[pd.Series]] = {c: [] for c in cols[1:]}
    for sym in symbols:
        files = sorted((root / sym).glob("*.parquet"))
        if not files:
            continue
        df = pd.concat([pd.read_parquet(f, columns=cols) for f in files])
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.drop_duplicates("timestamp", keep="last").set_index("timestamp").sort_index()
        for c in cols[1:]:
            parts[c].append(df[c].rename(sym))
    return {c: (pd.concat(v, axis=1).sort_index() if v else pd.DataFrame()) for c, v in parts.items()}


def build_features(
    R: pd.DataFrame, FIRST: pd.DataFrame, NSET: pd.DataFrame,
    OP: pd.DataFrame, HI: pd.DataFrame, LO: pd.DataFrame, CL: pd.DataFrame, QV: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """Return ``(X, y_bps, is4)`` indexed by (dt, sym).

    ``X`` has a row wherever yesterday's funding and today's first settlement
    are both known; ``y_bps`` is the day's realized total (NaN until the day
    is complete); ``is4`` is the regime flag from yesterday's settlement count.
    """
    idx = OP.index.union(R.index).sort_values()
    cols = OP.columns.union(R.columns)
    al = lambda x: x.reindex(index=idx, columns=cols)  # noqa: E731
    R, FIRST, NSET = al(R), al(FIRST), al(NSET)
    OP, HI, LO, CL, QV = al(OP), al(HI), al(LO), al(CL), al(QV)
    ret1 = CL / CL.shift(1) - 1
    nset_obs = NSET.shift(1)
    R1 = R.shift(1)
    QV1 = QV.shift(1)
    adv = QV1.rolling(30, min_periods=10).median()
    F = {
        "lag1": R1, "lag2": R.shift(2), "lag3": R.shift(3), "lag5": R.shift(5),
        "ma5": R1.rolling(5).mean(), "ma20": R1.rolling(20).mean(), "sd20": R1.rolling(20).std(),
        "min5": R1.rolling(5).min(), "min20": R1.rolling(20).min(),
        "first": FIRST, "first_x_n": FIRST * nset_obs,
        "first_vs_lag": FIRST - R1 / nset_obs.replace(0, np.nan),
        "volrel": QV1 / adv, "volrel5": QV1.rolling(5).mean() / adv,
        "ret1": ret1.shift(1), "ret5": CL.shift(1) / CL.shift(6) - 1, "ret20": CL.shift(1) / CL.shift(21) - 1,
        "vol20": ret1.shift(1).rolling(20).std(), "range": ((HI - LO) / CL).shift(1),
        "drawdown": CL.shift(1) / CL.shift(1).rolling(20).max() - 1,
        "logadv": np.log1p(adv),
        "xs_rank_fund": R1.rank(axis=1, pct=True), "xs_rank_vol": QV1.rank(axis=1, pct=True),
    }
    X = pd.concat({k: v.stack(future_stack=True) for k, v in F.items()}, axis=1)[FEATURES]
    X = X[X["lag1"].notna() & X["first"].notna()]
    X.index.names = ["dt", "sym"]
    y = (R.stack(future_stack=True) * 1e4).reindex(X.index)
    is4 = (nset_obs >= REGIME_NSET).stack(future_stack=True).reindex(X.index).fillna(False).astype(bool)
    return X, y, is4


class FundingTailFilter:
    """Name the shorts to drop on a given day. Builds its panel from disk on
    first use; models are cached under ``model_dir``."""

    def __init__(
        self,
        symbols: list[str],
        funding_path: Path | str = DEFAULT_FUNDING_PATH,
        klines_path: Path | str = DEFAULT_KLINES_PATH,
        model_dir: Path | str = DEFAULT_MODEL_DIR,
        threshold_bps: float = THRESHOLD_BPS,
        seed_end: str = SEED_END,
        min_train_cells: int = MIN_TRAIN_CELLS,
        hyperparams: dict | None = None,
        panel: tuple[pd.DataFrame, pd.Series, pd.Series] | None = None,
    ):
        self.symbols = sorted({s.upper() for s in symbols})
        self.funding_path = Path(funding_path)
        self.klines_path = Path(klines_path)
        self.model_dir = Path(model_dir)
        self.threshold_bps = float(threshold_bps)
        self.seed_end = pd.Timestamp(seed_end)
        self.min_train_cells = int(min_train_cells)
        self.hp = dict(HYPERPARAMS if hyperparams is None else hyperparams)
        self._panel = panel
        self._mu: dict[pd.Timestamp, pd.Series] = {}   # block start -> predictions
        self._boundaries: list[pd.Timestamp] | None = None

    # ---- data -----------------------------------------------------------
    def panel(self) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
        if self._panel is None:
            R, FIRST, NSET = load_funding_daily(self.symbols, self.funding_path)
            K = load_kline_panels(self.symbols, self.klines_path)
            self._panel = build_features(R, FIRST, NSET, K["open"], K["high"], K["low"], K["close"], K["quote_volume"])
            X = self._panel[0]
            log.info("funding filter panel: %s rows, %s..%s", f"{len(X):,}",
                     X.index.get_level_values("dt").min().date(), X.index.get_level_values("dt").max().date())
        return self._panel

    def boundaries(self) -> list[pd.Timestamp]:
        if self._boundaries is None:
            X = self.panel()[0]
            self._boundaries = refit_boundaries(self.seed_end, X.index.get_level_values("dt").max())
        return self._boundaries

    def block_start(self, day: pd.Timestamp) -> pd.Timestamp | None:
        bs = [b for b in self.boundaries() if b <= day]
        return bs[-1] if bs else None

    # ---- models ---------------------------------------------------------
    def _fit_or_load(self, block: pd.Timestamp, regime: str, Xtr: pd.DataFrame, ytr: pd.Series):
        import xgboost as xgb
        key = hashlib.sha1(f"{len(Xtr)}|{ytr.sum():.6f}|{Xtr.index.get_level_values('dt').max()}".encode()).hexdigest()[:10]
        path = self.model_dir / f"ftf_{block:%Y%m%d}_{regime}_{key}.json"
        model = xgb.XGBRegressor(**self.hp)
        if path.exists():
            model.load_model(path)
            return model
        model.fit(Xtr, ytr)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        model.save_model(path)
        log.info("funding filter: fit %s/%s on %s cells -> %s", block.date(), regime, f"{len(Xtr):,}", path.name)
        return model

    def _predict_block(self, block: pd.Timestamp) -> pd.Series:
        if block in self._mu:
            return self._mu[block]
        X, y, is4 = self.panel()
        dts = X.index.get_level_values("dt")
        bs = self.boundaries()
        nxt = next((b for b in bs if b > block), None)
        in_block = (dts >= block) & ((dts < nxt) if nxt is not None else True)
        train = (dts < block) & y.notna()
        mu = pd.Series(np.nan, index=X.index[in_block])
        for regime, mask in (("8h", ~is4.values), ("4h", is4.values)):
            tr = train & mask
            te = in_block & mask
            if tr.sum() < self.min_train_cells or te.sum() == 0:
                continue
            model = self._fit_or_load(block, regime, X[tr], y[tr])
            mu.loc[X.index[te]] = model.predict(X[te])
        self._mu[block] = mu
        return mu

    # ---- public ---------------------------------------------------------
    def predictions(self, day: pd.Timestamp) -> pd.Series:
        """Predicted funding (bps) per symbol for ``day``; empty before the seed ends."""
        day = pd.Timestamp(day).normalize()
        block = self.block_start(day)
        if block is None:
            return pd.Series(dtype=float)
        mu = self._predict_block(block)
        if day not in mu.index.get_level_values("dt"):
            return pd.Series(dtype=float)
        return mu.xs(day, level="dt").dropna()

    def blocked(self, day: pd.Timestamp, candidates) -> set[str]:
        mu = self.predictions(day)
        if mu.empty:
            return set()
        hit = mu[mu < self.threshold_bps].index
        return {s for s in candidates if s in hit}
