#!/usr/bin/env python3
"""
데이터 전처리 스크립트

원본 tick 데이터를 OHLCV 캔들로 리샘플링하여 저장합니다.
백테스트 시 빠른 로딩을 위해 미리 처리합니다.

Usage:
    python scripts/preprocess_data.py
    python scripts/preprocess_data.py --symbols BTCUSDT ETHUSDT --interval 5
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from intraday.config import get_default_data_dir
import pandas as pd
import pyarrow.parquet as pq

from intraday.data import get_config


def process_symbol(
    symbol: str,
    input_dir: Path,
    output_dir: Path,
    interval_minutes: int,
) -> None:
    """
    심볼 데이터 전처리

    Args:
        symbol: 심볼
        input_dir: 원본 데이터 디렉토리
        output_dir: 출력 디렉토리
        interval_minutes: 캔들 간격 (분)
    """
    symbol_dir = input_dir / symbol
    if not symbol_dir.exists():
        print(f"  {symbol}: Directory not found")
        return

    all_candles = []

    # 모든 parquet 파일 처리
    files = sorted(symbol_dir.rglob("*.parquet"))

    for f in files:
        try:
            # 메타데이터로 유효성 체크
            pq.read_metadata(f)
        except Exception:
            print(f"  {symbol}: Skipping corrupted {f.name}")
            continue

        print(f"  {symbol}: Processing {f.name}...", end=" ", flush=True)

        try:
            # Parquet 읽기
            df = pd.read_parquet(f, columns=["timestamp", "price", "quantity"])

            if df.empty:
                print("EMPTY")
                continue

            # 리샘플링
            df = df.set_index("timestamp")
            candles = df.resample(f"{interval_minutes}min").agg({
                "price": ["first", "max", "min", "last"],
                "quantity": "sum",
            }).dropna()

            candles.columns = ["open", "high", "low", "close", "volume"]
            candles = candles.reset_index()

            all_candles.append(candles)
            print(f"OK ({len(candles):,} candles)")

        except Exception as e:
            print(f"ERROR: {e}")

    if not all_candles:
        print(f"  {symbol}: No valid data")
        return

    # 병합 및 저장
    result = pd.concat(all_candles, ignore_index=True)
    result = result.sort_values("timestamp").drop_duplicates(subset=["timestamp"])
    result = result.reset_index(drop=True)

    output_file = output_dir / f"{symbol}_{interval_minutes}m.parquet"
    result.to_parquet(output_file, index=False)

    print(f"  {symbol}: Saved {len(result):,} candles to {output_file.name}")


def main():
    parser = argparse.ArgumentParser(description="Preprocess tick data to OHLCV candles")
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=None,
        help="Symbols to process (default: from config)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=5,
        help="Candle interval in minutes (default: 5)",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Input directory (default: INTRADAY_DATA_DIR)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output directory (default: input/candles)",
    )

    args = parser.parse_args()

    config = get_config()
    symbols = args.symbols or config.symbols
    input_dir = args.input or get_default_data_dir()
    output_dir = args.output or (input_dir / "candles")

    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("📊 Data Preprocessing")
    print("=" * 60)
    print(f"Symbols:  {symbols}")
    print(f"Interval: {args.interval}m")
    print(f"Input:    {input_dir}")
    print(f"Output:   {output_dir}")
    print("=" * 60)

    for symbol in symbols:
        print(f"\n🔄 Processing {symbol}...")
        process_symbol(symbol, input_dir, output_dir, args.interval)

    print("\n✅ Done!")


if __name__ == "__main__":
    main()
