#!/usr/bin/env python3
"""
캔들 빌더 예제 스크립트

틱 데이터를 다양한 단위의 캔들로 변환하는 예제입니다.

사용법:
    python scripts/build_candles_example.py

지원하는 캔들 타입:
    - VOLUME: 거래량 단위 (예: 10 BTC마다)
    - TICK: 틱 수 단위 (예: 1000틱마다)
    - TIME: 시간 단위 (예: 60초 = 1분)
    - DOLLAR: 달러 금액 단위 (예: 100만 달러마다)
"""

import sys
from pathlib import Path

# 프로젝트 루트 추가
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from intraday import (
    TickDataDownloader,
    TickDataLoader,
    CandleBuilder,
    CandleType,
    build_candles,
)


def main():
    """캔들 빌더 메인 함수"""
    
    # === 설정 ===
    symbol = "BTCUSDT"
    data_dir = Path("./data/ticks")
    
    print("=" * 60)
    print("캔들 빌더 예제")
    print("=" * 60)
    
    # === 1. 데이터 확인 ===
    print("\n[Step 1] 데이터 확인...")
    
    try:
        loader = TickDataLoader(data_dir, symbol=symbol)
        print(f"로드된 파일 수: {loader.file_count}")
    except FileNotFoundError:
        print("데이터가 없습니다. 먼저 다운로드합니다...")
        
        downloader = TickDataDownloader()
        try:
            downloader.download_monthly(
                symbol=symbol,
                year=2024,
                month=1,
                output_dir=data_dir,
            )
            loader = TickDataLoader(data_dir, symbol=symbol)
        except Exception as e:
            print(f"다운로드 실패: {e}")
            return
    
    # === 2. 다양한 캔들 타입 생성 ===
    
    # --- 방법 1: CandleBuilder 직접 사용 ---
    print("\n[방법 1] CandleBuilder 직접 사용")
    print("-" * 40)
    
    # 볼륨 캔들 (10 BTC 단위)
    print("\n📊 볼륨 캔들 (10 BTC)")
    builder = CandleBuilder(CandleType.VOLUME, size=10.0)
    volume_candles = builder.build_from_loader(loader)
    print(f"생성된 캔들 수: {len(volume_candles)}")
    if volume_candles:
        c = volume_candles[0]
        print(f"첫 캔들: O={c.open:.2f} H={c.high:.2f} L={c.low:.2f} C={c.close:.2f}")
    
    # 틱 캔들 (1000 틱 단위)
    print("\n📊 틱 캔들 (1000 틱)")
    builder = CandleBuilder(CandleType.TICK, size=1000)
    tick_candles = builder.build_from_loader(loader)
    print(f"생성된 캔들 수: {len(tick_candles)}")
    if tick_candles:
        c = tick_candles[0]
        print(f"첫 캔들: O={c.open:.2f} H={c.high:.2f} L={c.low:.2f} C={c.close:.2f}")
    
    # 시간 캔들 (1분)
    print("\n📊 시간 캔들 (1분)")
    builder = CandleBuilder(CandleType.TIME, size=60)
    time_candles = builder.build_from_loader(loader)
    print(f"생성된 캔들 수: {len(time_candles)}")
    if time_candles:
        c = time_candles[0]
        print(f"첫 캔들: O={c.open:.2f} H={c.high:.2f} L={c.low:.2f} C={c.close:.2f}")
    
    # 달러 캔들 (100만 달러)
    print("\n📊 달러 캔들 (100만 USDT)")
    builder = CandleBuilder(CandleType.DOLLAR, size=1_000_000)
    dollar_candles = builder.build_from_loader(loader)
    print(f"생성된 캔들 수: {len(dollar_candles)}")
    if dollar_candles:
        c = dollar_candles[0]
        print(f"첫 캔들: O={c.open:.2f} H={c.high:.2f} L={c.low:.2f} C={c.close:.2f}")
    
    # --- 방법 2: 편의 함수 사용 (바로 DataFrame) ---
    print("\n\n[방법 2] build_candles() 편의 함수 (→ DataFrame)")
    print("-" * 40)
    
    # 5분 캔들을 DataFrame으로
    df = build_candles(
        data_path=data_dir,
        symbol=symbol,
        candle_type=CandleType.TIME,
        size=300,  # 5분 = 300초
    )
    print(f"\n📊 5분 캔들 DataFrame")
    print(f"Shape: {df.shape}")
    print(f"\n처음 3개:")
    print(df.head(3).to_string())
    
    # --- 캔들 속성 활용 예시 ---
    print("\n\n[캔들 속성 활용]")
    print("-" * 40)
    
    if volume_candles:
        c = volume_candles[0]
        print(f"\n볼륨 캔들 첫 번째:")
        print(f"  - VWAP: {c.vwap:.2f}")
        print(f"  - Volume Imbalance: {c.volume_imbalance:.4f}")
        print(f"  - Range: {c.range:.2f}")
        print(f"  - Body: {c.body:.2f}")
        print(f"  - Bullish: {c.is_bullish}")
    
    print("\n" + "=" * 60)
    print("완료!")


if __name__ == "__main__":
    main()





