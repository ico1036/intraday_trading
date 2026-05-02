#!/usr/bin/env python3
"""
데이터 다운로드 스크립트

메이저 코인 선물 데이터를 Binance에서 다운로드합니다.
병렬 처리, 재시작 가능, 진행상황 저장.

Usage:
    uv run python scripts/download_data.py
    uv run python scripts/download_data.py --symbols BTCUSDT ETHUSDT
    uv run python scripts/download_data.py --start 2025-01 --end 2025-06
"""

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from intraday.config import get_default_data_dir
from intraday.data.downloader import MarketType, TickDataDownloader


# 기본 설정
DEFAULT_SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT", 
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "ADAUSDT",
]

DEFAULT_OUTPUT_DIR = get_default_data_dir()
PROGRESS_FILE = DEFAULT_OUTPUT_DIR / ".download_progress.json"


def get_months_range(start: str, end: str) -> list[tuple[int, int]]:
    """
    월 범위 생성
    
    Args:
        start: "YYYY-MM" 형식
        end: "YYYY-MM" 형식
        
    Returns:
        [(year, month), ...] 리스트
    """
    start_year, start_month = map(int, start.split("-"))
    end_year, end_month = map(int, end.split("-"))
    
    months = []
    year, month = start_year, start_month
    
    while (year, month) <= (end_year, end_month):
        months.append((year, month))
        month += 1
        if month > 12:
            month = 1
            year += 1
    
    return months


def load_progress() -> dict:
    """진행상황 로드"""
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text())
    return {"completed": []}


def save_progress(progress: dict):
    """진행상황 저장"""
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_FILE.write_text(json.dumps(progress, indent=2))


def download_one(
    symbol: str,
    year: int,
    month: int,
    output_dir: Path,
    downloader: TickDataDownloader,
) -> tuple[str, bool, str]:
    """
    단일 파일 다운로드
    
    Returns:
        (key, success, message)
    """
    key = f"{symbol}-{year}-{month:02d}"
    symbol_dir = output_dir / symbol / str(year)
    
    try:
        filepath = downloader.download_monthly(
            symbol=symbol,
            year=year,
            month=month,
            output_dir=symbol_dir,
        )
        return (key, True, f"✅ {key}")
    except Exception as e:
        error_msg = str(e)
        if "404" in error_msg:
            return (key, True, f"⏭️ {key} (not available yet)")
        return (key, False, f"❌ {key}: {error_msg[:50]}")


def main():
    parser = argparse.ArgumentParser(description="Download futures tick data")
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=DEFAULT_SYMBOLS,
        help="Symbols to download",
    )
    parser.add_argument(
        "--start",
        default="2025-01",
        help="Start month (YYYY-MM)",
    )
    parser.add_argument(
        "--end",
        default="2026-01",
        help="End month (YYYY-MM)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=3,
        help="Number of parallel downloads",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if already completed",
    )
    
    args = parser.parse_args()
    
    # 설정 출력
    print("=" * 60, flush=True)
    print("📥 Futures Data Downloader", flush=True)
    print("=" * 60, flush=True)
    print(f"Symbols: {args.symbols}", flush=True)
    print(f"Period: {args.start} ~ {args.end}", flush=True)
    print(f"Output: {args.output}", flush=True)
    print(f"Workers: {args.workers}", flush=True)
    print("=" * 60, flush=True)
    
    # 다운로드 목록 생성
    months = get_months_range(args.start, args.end)
    progress = load_progress() if not args.force else {"completed": []}
    
    tasks = []
    for symbol in args.symbols:
        for year, month in months:
            key = f"{symbol}-{year}-{month:02d}"
            if key not in progress["completed"]:
                tasks.append((symbol, year, month))
    
    print(f"Tasks: {len(tasks)} files to download")
    print(f"Skipped: {len(args.symbols) * len(months) - len(tasks)} already done")
    print("=" * 60)
    
    if not tasks:
        print("Nothing to download!")
        return
    
    # 다운로드 실행
    downloader = TickDataDownloader(market_type=MarketType.FUTURES)
    completed = 0
    failed = 0
    
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                download_one, symbol, year, month, args.output, downloader
            ): (symbol, year, month)
            for symbol, year, month in tasks
        }
        
        for future in as_completed(futures):
            key, success, message = future.result()
            print(message)
            
            if success:
                progress["completed"].append(key)
                save_progress(progress)
                completed += 1
            else:
                failed += 1
    
    # 요약
    print("=" * 60)
    print(f"✅ Completed: {completed}")
    print(f"❌ Failed: {failed}")
    print("=" * 60)


if __name__ == "__main__":
    main()
