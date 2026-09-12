"""Settlement-level funding rates from ``data/funding_rates_full/<SYM>.parquet``.

One file per symbol with columns ``timestamp`` (UTC, naive), ``symbol``,
``funding_rate`` (fraction per settlement). Written by
``scripts/tools/download_funding_rates.py``.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_FUNDING_PATH = Path("data/funding_rates_full")


def read_funding_file(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path, columns=["timestamp", "funding_rate"])
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.dropna().sort_values("timestamp")
    return df.drop_duplicates("timestamp", keep="last")


def load_funding_rates(
    symbols: list[str],
    funding_path: Path | str = DEFAULT_FUNDING_PATH,
) -> tuple[dict[str, tuple[np.ndarray, np.ndarray]], list[str]]:
    """Return ``({symbol: (ts_ns_sorted, rate)}, missing_symbols)`` for the runner."""
    root = Path(funding_path)
    out: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    missing: list[str] = []
    for sym in symbols:
        p = root / f"{sym.upper()}.parquet"
        if not p.exists():
            missing.append(sym)
            continue
        df = read_funding_file(p)
        if df.empty:
            missing.append(sym)
            continue
        out[sym.upper()] = (
            df["timestamp"].values.astype("datetime64[ns]").astype(np.int64),
            df["funding_rate"].to_numpy(dtype=float),
        )
    return out, missing


def load_funding_daily(
    symbols: list[str],
    funding_path: Path | str = DEFAULT_FUNDING_PATH,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Daily panels (index: day, columns: symbol) of the summed rate, the day's
    first settlement rate, and the settlement count."""
    root = Path(funding_path)
    tot, first, nset = {}, {}, {}
    for sym in symbols:
        p = root / f"{sym.upper()}.parquet"
        if not p.exists():
            continue
        df = read_funding_file(p)
        if df.empty:
            continue
        g = df.groupby(df["timestamp"].dt.floor("D"))["funding_rate"]
        tot[sym.upper()] = g.sum()
        first[sym.upper()] = g.first()
        nset[sym.upper()] = g.size()
    R = pd.DataFrame(tot).sort_index()
    return R, pd.DataFrame(first).reindex(R.index), pd.DataFrame(nset).reindex(R.index)
