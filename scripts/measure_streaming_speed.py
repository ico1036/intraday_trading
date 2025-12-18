"""
데이터 스트리밍 속도 측정 스크립트

실제 Binance WebSocket에서 데이터가 얼마나 빠르게 오는지 측정합니다.
"""
import asyncio
import sys
import time
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from intraday.client import BinanceWebSocketClient, OrderbookSnapshot


async def measure_streaming_speed(update_speed: str = "100ms", duration_seconds: int = 10):
    """
    스트리밍 속도 측정
    
    Args:
        update_speed: "100ms" 또는 "1000ms"
        duration_seconds: 측정 시간 (초)
    """
    client = BinanceWebSocketClient("btcusdt", depth_levels=20, update_speed=update_speed)
    
    timestamps = []
    message_count = 0
    start_time = None
    
    def on_data(snapshot: OrderbookSnapshot):
        nonlocal message_count, start_time
        
        if start_time is None:
            start_time = time.time()
        
        timestamps.append(time.time())
        message_count += 1
        
        # 주기적으로 출력
        if message_count % 10 == 0:
            elapsed = time.time() - start_time
            rate = message_count / elapsed if elapsed > 0 else 0
            print(f"[{message_count:4d}개] 경과: {elapsed:.2f}초 | "
                  f"속도: {rate:.2f} msg/s | "
                  f"Best Bid: ${snapshot.bids[0][0]:,.2f}")
    
    print(f"\n{'='*60}")
    print(f"스트리밍 속도 측정 시작")
    print(f"{'='*60}")
    print(f"설정: {update_speed} 업데이트 속도")
    print(f"측정 시간: {duration_seconds}초")
    print(f"{'='*60}\n")
    
    # 백그라운드에서 일정 시간 후 종료
    async def auto_stop():
        await asyncio.sleep(duration_seconds)
        await client.disconnect()
    
    # 자동 종료 태스크 시작
    stop_task = asyncio.create_task(auto_stop())
    
    try:
        await client.connect(on_data)
    except KeyboardInterrupt:
        await client.disconnect()
    finally:
        stop_task.cancel()
    
    # 결과 분석
    if len(timestamps) < 2:
        print("\n❌ 데이터가 충분히 수집되지 않았습니다.")
        return
    
    elapsed = timestamps[-1] - timestamps[0]
    total_messages = len(timestamps)
    
    # 메시지 간격 계산
    intervals = [timestamps[i] - timestamps[i-1] for i in range(1, len(timestamps))]
    avg_interval = sum(intervals) / len(intervals) if intervals else 0
    min_interval = min(intervals) if intervals else 0
    max_interval = max(intervals) if intervals else 0
    
    # 초당 메시지 수
    messages_per_second = total_messages / elapsed if elapsed > 0 else 0
    
    print(f"\n{'='*60}")
    print(f"측정 결과")
    print(f"{'='*60}")
    print(f"총 수신 메시지: {total_messages}개")
    print(f"측정 시간: {elapsed:.2f}초")
    print(f"평균 수신 속도: {messages_per_second:.2f} msg/s")
    print(f"\n메시지 간격 분석:")
    print(f"  평균 간격: {avg_interval*1000:.2f}ms")
    print(f"  최소 간격: {min_interval*1000:.2f}ms")
    print(f"  최대 간격: {max_interval*1000:.2f}ms")
    
    # 이론적 속도와 비교
    if update_speed == "100ms":
        theoretical_rate = 10.0  # 초당 10개
        print(f"\n이론적 속도: {theoretical_rate} msg/s (100ms = 10개/초)")
    else:
        theoretical_rate = 1.0  # 초당 1개
        print(f"\n이론적 속도: {theoretical_rate} msg/s (1000ms = 1개/초)")
    
    efficiency = (messages_per_second / theoretical_rate * 100) if theoretical_rate > 0 else 0
    print(f"효율성: {efficiency:.1f}%")
    
    if efficiency >= 95:
        print("✅ 매우 우수한 수신 속도!")
    elif efficiency >= 80:
        print("✅ 양호한 수신 속도")
    elif efficiency >= 60:
        print("⚠️  보통 수신 속도 (네트워크 지연 가능)")
    else:
        print("❌ 낮은 수신 속도 (네트워크 문제 가능)")
    
    print(f"{'='*60}\n")


async def main():
    """두 가지 속도 모두 측정"""
    print("\n🔍 Binance WebSocket 스트리밍 속도 측정\n")
    
    # 100ms 속도 측정
    print("📊 [1/2] 100ms 업데이트 속도 측정 (10초)")
    await measure_streaming_speed("100ms", duration_seconds=10)
    
    await asyncio.sleep(2)  # 잠시 대기
    
    # 1000ms 속도 측정
    print("\n📊 [2/2] 1000ms 업데이트 속도 측정 (10초)")
    await measure_streaming_speed("1000ms", duration_seconds=10)
    
    print("\n✅ 측정 완료!\n")


if __name__ == "__main__":
    asyncio.run(main())

