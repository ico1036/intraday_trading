#!/usr/bin/env python3
"""Incrementally sync settlement-level funding rates from Binance USDT-M perps.

Public fapi — no API key. One parquet per symbol in ``--out`` with columns
``timestamp`` (UTC, naive, ms precision), ``symbol``, ``funding_rate``. An
existing file is extended from its last settlement; a missing one is fetched
from ``--start``.

    uv run python scripts/tools/download_funding_rates.py --from-splits archive/<run>/splits.json
    uv run python scripts/tools/download_funding_rates.py --symbols BTCUSDT ETHUSDT

Network handling (wait for DNS, backoff on 429/5xx) is shared with
download_daily_klines.py so a laptop waking under launchd survives.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from download_daily_klines import _get, wait_for_network  # noqa: E402

FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate"
PAGE = 1000
DEFAULT_START = "2020-01-01"
DEFAULT_OUT = "data/funding_rates_full"


def fetch_funding(symbol: str, start_ms: int, end_ms: int | None = None) -> pd.DataFrame:
    rows: list[dict] = []
    cursor = start_ms
    while True:
        params = {"symbol": symbol, "startTime": cursor, "limit": PAGE}
        if end_ms is not None:
            params["endTime"] = end_ms
        r = _get(FUNDING_URL, params=params)
        if r.status_code >= 400:
            raise RuntimeError(f"{symbol}: HTTP {r.status_code} {r.text[:120]}")
        batch = r.json()
        if not batch:
            break
        rows.extend(batch)
        last = int(batch[-1]["fundingTime"])
        if len(batch) < PAGE or last <= cursor:
            break
        cursor = last + 1
        time.sleep(0.1)
    if not rows:
        return pd.DataFrame(columns=["timestamp", "symbol", "funding_rate"])
    df = pd.DataFrame(rows)
    out = pd.DataFrame({
        "timestamp": pd.to_datetime(df["fundingTime"].astype("int64"), unit="ms"),
        "symbol": symbol,
        "funding_rate": pd.to_numeric(df["fundingRate"], errors="coerce"),
    })
    return out.dropna(subset=["funding_rate"])


def sync_symbol(symbol: str, out_dir: Path, start_ms: int) -> tuple[int, int]:
    """Return ``(new_rows, total_rows)`` after extending ``<out_dir>/<symbol>.parquet``."""
    path = out_dir / f"{symbol}.parquet"
    old = None
    if path.exists():
        old = pd.read_parquet(path)
        if len(old):
            old["timestamp"] = pd.to_datetime(old["timestamp"])
            start_ms = max(start_ms, int(old["timestamp"].max().timestamp() * 1000) + 1)
    new = fetch_funding(symbol, start_ms)
    if old is not None and len(old):
        df = pd.concat([old, new], ignore_index=True) if len(new) else old
    else:
        df = new
    df = (df.drop_duplicates("timestamp", keep="last")
            .sort_values("timestamp")
            .reset_index(drop=True))
    if len(new) or not path.exists():
        out_dir.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False)
    return len(new), len(df)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols", nargs="*", help="explicit symbol list")
    ap.add_argument("--from-splits", default=None, help="take the universe from a splits.json")
    ap.add_argument("--start", default=DEFAULT_START, help="first settlement to fetch for a new file")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--network-wait", type=float, default=600.0,
                    help="seconds to wait for the API before starting (0 disables)")
    ap.add_argument("--max-failure-fraction", type=float, default=0.0,
                    help="return success when failed symbols are at or below this fraction")
    args = ap.parse_args(argv)

    symbols: list[str] = []
    if args.symbols:
        symbols = sorted({s.upper() for s in args.symbols})
    elif args.from_splits:
        sp = json.loads(Path(args.from_splits).read_text())
        symbols = sorted({s.upper() for s in sp.get("universe", [])})
    if not symbols:
        print("no symbols: pass --symbols or --from-splits", file=sys.stderr)
        return 2

    out_dir = Path(args.out)
    start_ms = int(pd.Timestamp(args.start).timestamp() * 1000)
    print(f"funding: {len(symbols)} symbols → {out_dir}", file=sys.stderr)
    if not wait_for_network(args.network_wait):
        return 1

    n_new = 0
    failures: list[tuple[str, str]] = []
    for i, sym in enumerate(symbols, 1):
        try:
            added, total = sync_symbol(sym, out_dir, start_ms)
            n_new += added
            if added:
                print(f"[{i}/{len(symbols)}] {sym}: +{added} (total {total})", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            failures.append((sym, f"{type(exc).__name__}: {exc}"))
            print(f"[{i}/{len(symbols)}] {sym}: FAILED {failures[-1][1][:100]}", file=sys.stderr)
    print(f"done: +{n_new} settlements, {len(failures)} failure(s)", file=sys.stderr)
    for sym, why in failures[:20]:
        print(f"  {sym}: {why}", file=sys.stderr)
    if failures and len(failures) / len(symbols) > args.max_failure_fraction:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
