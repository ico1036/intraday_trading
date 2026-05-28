#!/usr/bin/env python3
"""Download daily klines for Binance USDT-M perpetual futures.

Writes one parquet per (symbol, year) under ``data/futures_klines_daily/``
matching the schema used by ``data/futures_klines/`` so existing
``BarDataLoader`` works unchanged.

Idempotent: skips (symbol, year) pairs whose parquet already exists.
Public Binance fapi — no API key required.

One-click reproduction (universe + date range pulled from the frozen
splits.json of a specific run):

    # 274-symbol live universe
    uv run python scripts/tools/download_daily_klines.py \\
        --from-splits live/splits/run_2026_05_xs500.splits.json

    # 531-symbol full reproduction baseline
    uv run python scripts/tools/download_daily_klines.py \\
        --from-splits live/splits/run_2026_05_full531.splits.json

``--symbols`` / ``--start`` / ``--end`` override the splits values when
both are passed.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests


EXCHANGE_INFO_URL = "https://fapi.binance.com/fapi/v1/exchangeInfo"
KLINES_URL = "https://fapi.binance.com/fapi/v1/klines"

KLINE_COLS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trade_count",
    "taker_buy_volume", "taker_buy_quote_volume", "ignore",
]


def fetch_perp_symbols() -> list[str]:
    r = requests.get(EXCHANGE_INFO_URL, timeout=30)
    r.raise_for_status()
    info = r.json()
    return sorted(
        s["symbol"]
        for s in info["symbols"]
        if s.get("status") == "TRADING"
        and s.get("quoteAsset") == "USDT"
        and s.get("contractType") == "PERPETUAL"
    )


def fetch_klines(symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    rows: list[list[Any]] = []
    cursor = start_ms
    while cursor < end_ms:
        r = requests.get(
            KLINES_URL,
            params={
                "symbol": symbol,
                "interval": "1d",
                "startTime": cursor,
                "endTime": end_ms,
                "limit": 1500,
            },
            timeout=30,
        )
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        rows.extend(batch)
        next_cursor = batch[-1][0] + 86_400_000
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        time.sleep(0.3)
    return pd.DataFrame(rows, columns=KLINE_COLS)


def normalize(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["open_time"], unit="ms")
    df["symbol"] = symbol
    for c in (
        "open", "high", "low", "close", "volume",
        "quote_volume", "taker_buy_volume", "taker_buy_quote_volume",
    ):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["trade_count"] = pd.to_numeric(df["trade_count"], errors="coerce").astype("Int64")
    return df[[
        "timestamp", "symbol", "open", "high", "low", "close", "volume",
        "quote_volume", "trade_count",
        "taker_buy_volume", "taker_buy_quote_volume",
    ]]


def save_by_year(df: pd.DataFrame, out_dir: Path, symbol: str) -> int:
    if df.empty:
        return 0
    df = df.copy()
    df["year"] = df["timestamp"].dt.year
    sym_dir = out_dir / symbol
    sym_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for year, year_df in df.groupby("year"):
        year_df = year_df.drop(columns=["year"]).sort_values("timestamp")
        path = sym_dir / f"{symbol}-1d-{int(year)}.parquet"
        year_df.to_parquet(path, index=False)
        written += len(year_df)
    return written


def already_complete(out_dir: Path, symbol: str, years: range) -> bool:
    sym_dir = out_dir / symbol
    return all((sym_dir / f"{symbol}-1d-{y}.parquet").exists() for y in years)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=None, help="default 2020-01-01 unless --from-splits")
    ap.add_argument("--end", default=None, help="default 2026-05-31 unless --from-splits")
    ap.add_argument("--out", default="data/futures_klines_daily")
    ap.add_argument("--symbols", nargs="*", help="explicit symbol list (skip exchangeInfo)")
    ap.add_argument("--from-splits", default=None,
                    help="path to splits.json — seeds universe + start (IS) + end (OS) for full reproduction")
    ap.add_argument("--limit", type=int, default=None, help="process at most N symbols")
    ap.add_argument("--force", action="store_true", help="re-download even if files exist")
    args = ap.parse_args(argv)

    splits_universe: list[str] | None = None
    splits_start: str | None = None
    splits_end: str | None = None
    if args.from_splits:
        sp = json.loads(Path(args.from_splits).read_text())
        splits_universe = list(sp.get("universe", []))
        splits_start = sp.get("is", {}).get("start")
        splits_end = sp.get("os", {}).get("end") or sp.get("is", {}).get("end")

    start_str = args.start or splits_start or "2020-01-01"
    end_str = args.end or splits_end or "2026-05-31"
    out_dir = Path(args.out)
    start_ts = pd.Timestamp(start_str)
    end_ts = pd.Timestamp(end_str)
    start_ms = int(start_ts.timestamp() * 1000)
    end_ms = int(end_ts.timestamp() * 1000)
    years = range(start_ts.year, end_ts.year + 1)

    if args.symbols:
        symbols = sorted({s.upper() for s in args.symbols})
    elif splits_universe is not None:
        symbols = sorted({s.upper() for s in splits_universe})
    else:
        symbols = fetch_perp_symbols()
    if args.limit:
        symbols = symbols[: args.limit]

    print(
        f"target: {len(symbols)} symbols  range: {start_str} → {end_str}  out: {out_dir}",
        file=sys.stderr,
    )

    n_ok = 0
    n_skip = 0
    failures: list[tuple[str, str]] = []
    for i, sym in enumerate(symbols, 1):
        if not args.force and already_complete(out_dir, sym, years):
            n_skip += 1
            continue
        try:
            df = fetch_klines(sym, start_ms, end_ms)
            df = normalize(df, sym)
            rows = save_by_year(df, out_dir, sym)
            n_ok += 1
            print(f"[{i}/{len(symbols)}] {sym}: {rows} rows", file=sys.stderr)
        except Exception as exc:
            failures.append((sym, str(exc)))
            print(f"[{i}/{len(symbols)}] {sym}: FAIL {exc}", file=sys.stderr)

    print(
        f"\ndone: ok={n_ok} skip={n_skip} fail={len(failures)}",
        file=sys.stderr,
    )
    for sym, err in failures:
        print(f"  {sym}: {err}", file=sys.stderr)
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
