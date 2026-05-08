#!/usr/bin/env python3
"""Download Binance USDT-M futures klines to parquet."""
from __future__ import annotations

import argparse
import io
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests


DEFAULT_SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "ADAUSDT",
]

BASE_URL = "https://data.binance.vision/data/futures/um"
COLUMNS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "trade_count",
    "taker_buy_volume",
    "taker_buy_quote_volume",
    "ignore",
]
KEEP_COLUMNS = [
    "timestamp",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "quote_volume",
    "trade_count",
    "taker_buy_volume",
    "taker_buy_quote_volume",
]


def parse_month(value: str) -> tuple[int, int]:
    year, month = value.split("-")
    return int(year), int(month)


def month_iter(start: str, end: str) -> list[tuple[int, int]]:
    year, month = parse_month(start)
    end_year, end_month = parse_month(end)
    out = []
    while (year, month) <= (end_year, end_month):
        out.append((year, month))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return out


def date_iter(start: str, end: str) -> list[date]:
    current = date.fromisoformat(start)
    last = date.fromisoformat(end)
    out = []
    while current <= last:
        out.append(current)
        current += timedelta(days=1)
    return out


def parse_zip(content: bytes, symbol: str) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        csv_name = zf.namelist()[0]
        with zf.open(csv_name) as f:
            df = pd.read_csv(f, header=None)

    if "open_time" in str(df.iloc[0, 0]).lower():
        df = df.iloc[1:].reset_index(drop=True)
        df.columns = COLUMNS[: len(df.columns)]
    elif len(df.columns) == len(COLUMNS):
        df.columns = COLUMNS
    else:
        raise ValueError(f"unexpected kline column count: {len(df.columns)}")

    df["timestamp"] = pd.to_datetime(pd.to_numeric(df["open_time"]), unit="ms", utc=False)
    df["symbol"] = symbol
    numeric_cols = [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_volume",
        "trade_count",
        "taker_buy_volume",
        "taker_buy_quote_volume",
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df[KEEP_COLUMNS]


def download_url(url: str, timeout: int) -> bytes:
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.content


def download_month(symbol: str, interval: str, year: int, month: int, output: Path, timeout: int) -> tuple[str, bool, str]:
    symbol = symbol.upper()
    key = f"{symbol}-{interval}-{year}-{month:02d}"
    out_dir = output / symbol / str(year)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{symbol}-{interval}-{year}-{month:02d}.parquet"
    if out_file.exists():
        return key, True, f"skip {key}"

    url = f"{BASE_URL}/monthly/klines/{symbol}/{interval}/{symbol}-{interval}-{year}-{month:02d}.zip"
    try:
        df = parse_zip(download_url(url, timeout), symbol)
        df.to_parquet(out_file, index=False, compression="snappy")
        return key, True, f"saved {key}: {len(df):,} rows"
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            return key, True, f"not available {key}"
        return key, False, f"failed {key}: {exc}"
    except Exception as exc:
        return key, False, f"failed {key}: {exc}"


def download_day(symbol: str, interval: str, day: date, output: Path, timeout: int) -> tuple[str, bool, str]:
    symbol = symbol.upper()
    key = f"{symbol}-{interval}-{day.isoformat()}"
    out_dir = output / symbol / str(day.year)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{symbol}-{interval}-{day.isoformat()}.parquet"
    if out_file.exists():
        return key, True, f"skip {key}"

    url = f"{BASE_URL}/daily/klines/{symbol}/{interval}/{symbol}-{interval}-{day.isoformat()}.zip"
    try:
        df = parse_zip(download_url(url, timeout), symbol)
        df.to_parquet(out_file, index=False, compression="snappy")
        return key, True, f"saved {key}: {len(df):,} rows"
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            return key, True, f"not available {key}"
        return key, False, f"failed {key}: {exc}"
    except Exception as exc:
        return key, False, f"failed {key}: {exc}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download Binance futures 1m klines")
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    parser.add_argument("--interval", default="1m")
    parser.add_argument("--monthly-start", default="2025-05")
    parser.add_argument("--monthly-end", default="2026-04")
    parser.add_argument("--daily-start", default="2026-05-01")
    parser.add_argument("--daily-end", default="2026-05-04")
    parser.add_argument("--output", type=Path, default=Path("data/futures_klines"))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=120)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    tasks = []
    for symbol in args.symbols:
        for year, month in month_iter(args.monthly_start, args.monthly_end):
            tasks.append(("month", symbol, year, month))
        for day in date_iter(args.daily_start, args.daily_end):
            tasks.append(("day", symbol, day))

    print(f"symbols={args.symbols}")
    print(f"monthly={args.monthly_start}..{args.monthly_end}")
    print(f"daily={args.daily_start}..{args.daily_end}")
    print(f"output={args.output}")
    print(f"tasks={len(tasks)}")

    failed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = []
        for task in tasks:
            if task[0] == "month":
                _, symbol, year, month = task
                futures.append(
                    executor.submit(
                        download_month,
                        symbol,
                        args.interval,
                        year,
                        month,
                        args.output,
                        args.timeout,
                    )
                )
            else:
                _, symbol, day = task
                futures.append(
                    executor.submit(
                        download_day,
                        symbol,
                        args.interval,
                        day,
                        args.output,
                        args.timeout,
                    )
                )

        for future in as_completed(futures):
            _key, ok, message = future.result()
            print(message, flush=True)
            failed += 0 if ok else 1

    if failed:
        print(f"failed={failed}")
        return 2
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
