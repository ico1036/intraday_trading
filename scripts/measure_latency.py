"""
Binance API Latency 측정 스크립트

주문 전송 시 발생하는 네트워크 지연을 측정합니다.
1. REST API RTT (Round Trip Time)
2. WebSocket 메시지 지연 (서버 타임스탬프 vs 로컬 타임스탬프)
"""

import asyncio
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))


async def measure_rest_api_latency(iterations: int = 20) -> dict:
    """
    REST API 왕복 시간(RTT) 측정
    
    Binance /api/v3/time 엔드포인트를 사용합니다.
    이 엔드포인트는 가볍고 rate limit에 관대합니다.
    
    Returns:
        latency 통계 (ms 단위)
    """
    url = "https://api.binance.com/api/v3/time"
    latencies = []
    
    print(f"\n{'='*60}")
    print("REST API Latency 측정 (Binance /api/v3/time)")
    print(f"{'='*60}")
    print(f"측정 횟수: {iterations}회\n")
    
    async with httpx.AsyncClient() as client:
        # 워밍업 (첫 요청은 연결 설정 포함)
        await client.get(url)
        
        for i in range(iterations):
            start = time.perf_counter()
            response = await client.get(url)
            end = time.perf_counter()
            
            if response.status_code == 200:
                rtt_ms = (end - start) * 1000
                latencies.append(rtt_ms)
                
                # 서버 시간과 로컬 시간 차이도 계산
                server_time = response.json()["serverTime"]
                local_time_ms = int(time.time() * 1000)
                clock_diff = local_time_ms - server_time
                
                print(f"  [{i+1:2d}] RTT: {rtt_ms:6.2f}ms | "
                      f"Clock diff: {clock_diff:+4d}ms")
            
            await asyncio.sleep(0.1)  # Rate limit 방지
    
    if not latencies:
        return {"error": "측정 실패"}
    
    result = {
        "mean": statistics.mean(latencies),
        "median": statistics.median(latencies),
        "stdev": statistics.stdev(latencies) if len(latencies) > 1 else 0,
        "min": min(latencies),
        "max": max(latencies),
        "p95": sorted(latencies)[int(len(latencies) * 0.95)] if len(latencies) >= 20 else max(latencies),
    }
    
    print(f"\n{'='*60}")
    print("REST API Latency 결과")
    print(f"{'='*60}")
    print(f"  평균:   {result['mean']:6.2f}ms")
    print(f"  중앙값: {result['median']:6.2f}ms")
    print(f"  표준편차: {result['stdev']:6.2f}ms")
    print(f"  최소:   {result['min']:6.2f}ms")
    print(f"  최대:   {result['max']:6.2f}ms")
    print(f"  P95:    {result['p95']:6.2f}ms")
    print(f"{'='*60}\n")
    
    return result


async def measure_websocket_latency(duration_seconds: int = 10) -> dict:
    """
    WebSocket 메시지 지연 측정
    
    Trade 메시지의 서버 타임스탬프와 수신 시간을 비교합니다.
    
    Returns:
        latency 통계 (ms 단위)
    """
    import websockets
    import json
    
    url = "wss://stream.binance.com:9443/ws/btcusdt@trade"
    latencies = []
    
    print(f"\n{'='*60}")
    print("WebSocket Trade 메시지 지연 측정")
    print(f"{'='*60}")
    print(f"측정 시간: {duration_seconds}초\n")
    
    try:
        async with websockets.connect(url) as ws:
            start_time = time.time()
            message_count = 0
            
            while time.time() - start_time < duration_seconds:
                try:
                    message = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    recv_time_ms = int(time.time() * 1000)
                    
                    data = json.loads(message)
                    if "T" in data:  # Trade timestamp
                        server_time_ms = data["T"]
                        latency_ms = recv_time_ms - server_time_ms
                        latencies.append(latency_ms)
                        message_count += 1
                        
                        if message_count % 20 == 0:
                            print(f"  [{message_count:4d}] Latency: {latency_ms:4d}ms | "
                                  f"Price: ${float(data['p']):,.2f}")
                
                except asyncio.TimeoutError:
                    continue
    
    except Exception as e:
        print(f"WebSocket 연결 오류: {e}")
        return {"error": str(e)}
    
    if not latencies:
        return {"error": "측정 실패"}
    
    result = {
        "mean": statistics.mean(latencies),
        "median": statistics.median(latencies),
        "stdev": statistics.stdev(latencies) if len(latencies) > 1 else 0,
        "min": min(latencies),
        "max": max(latencies),
        "p95": sorted(latencies)[int(len(latencies) * 0.95)] if len(latencies) >= 20 else max(latencies),
        "count": len(latencies),
    }
    
    print(f"\n{'='*60}")
    print("WebSocket Latency 결과")
    print(f"{'='*60}")
    print(f"  수신 메시지: {result['count']}개")
    print(f"  평균:   {result['mean']:6.2f}ms")
    print(f"  중앙값: {result['median']:6.2f}ms")
    print(f"  표준편차: {result['stdev']:6.2f}ms")
    print(f"  최소:   {result['min']:6.2f}ms")
    print(f"  최대:   {result['max']:6.2f}ms")
    print(f"  P95:    {result['p95']:6.2f}ms")
    print(f"{'='*60}\n")
    
    return result


async def measure_order_simulation_latency(iterations: int = 10) -> dict:
    """
    주문 시뮬레이션 latency 측정
    
    실제 주문 전송과 유사한 POST 요청의 latency를 측정합니다.
    (테스트넷 또는 /api/v3/ping 사용)
    
    Returns:
        latency 통계 (ms 단위)
    """
    # ping은 가장 가벼운 요청
    url = "https://api.binance.com/api/v3/ping"
    latencies = []
    
    print(f"\n{'='*60}")
    print("주문 시뮬레이션 Latency 측정 (Binance /api/v3/ping)")
    print(f"{'='*60}")
    print(f"측정 횟수: {iterations}회\n")
    
    async with httpx.AsyncClient() as client:
        # 워밍업
        await client.get(url)
        
        for i in range(iterations):
            start = time.perf_counter()
            response = await client.get(url)
            end = time.perf_counter()
            
            if response.status_code == 200:
                rtt_ms = (end - start) * 1000
                latencies.append(rtt_ms)
                print(f"  [{i+1:2d}] RTT: {rtt_ms:6.2f}ms")
            
            await asyncio.sleep(0.2)
    
    if not latencies:
        return {"error": "측정 실패"}
    
    result = {
        "mean": statistics.mean(latencies),
        "median": statistics.median(latencies),
        "stdev": statistics.stdev(latencies) if len(latencies) > 1 else 0,
        "min": min(latencies),
        "max": max(latencies),
    }
    
    print(f"\n결과: 평균 {result['mean']:.2f}ms, 중앙값 {result['median']:.2f}ms\n")
    
    return result


async def main():
    """전체 latency 측정 실행"""
    print("\n" + "="*60)
    print("🔍 Binance API Latency 측정")
    print("="*60)
    print(f"시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    
    # 1. REST API latency
    rest_result = await measure_rest_api_latency(iterations=20)
    
    await asyncio.sleep(1)
    
    # 2. WebSocket latency
    ws_result = await measure_websocket_latency(duration_seconds=10)
    
    await asyncio.sleep(1)
    
    # 3. Ping latency
    ping_result = await measure_order_simulation_latency(iterations=10)
    
    # 최종 요약
    print("\n" + "="*60)
    print("📊 최종 요약")
    print("="*60)
    
    if "error" not in rest_result:
        print(f"\n1. REST API (/api/v3/time)")
        print(f"   → 평균 RTT: {rest_result['mean']:.1f}ms")
        print(f"   → P95 RTT:  {rest_result['p95']:.1f}ms")
    
    if "error" not in ws_result:
        print(f"\n2. WebSocket (Trade 메시지)")
        print(f"   → 평균 지연: {ws_result['mean']:.1f}ms")
        print(f"   → P95 지연:  {ws_result['p95']:.1f}ms")
        print(f"   ⚠️  참고: 시계 동기화 오차 포함")
    
    if "error" not in ping_result:
        print(f"\n3. Ping (/api/v3/ping)")
        print(f"   → 평균 RTT: {ping_result['mean']:.1f}ms")
    
    # 권장 latency 설정
    print("\n" + "="*60)
    print("💡 백테스터 권장 설정")
    print("="*60)
    
    if "error" not in rest_result:
        recommended_latency = rest_result['p95']
        print(f"\n  latency_ms = {recommended_latency:.0f}")
        print(f"\n  (P95 기준 - 95%의 주문이 이 시간 내 도착)")
        print(f"  (보수적으로 하려면 2배: {recommended_latency * 2:.0f}ms)")
    
    print("\n" + "="*60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())

