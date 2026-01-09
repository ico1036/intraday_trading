#!/bin/bash
set -e

echo "=== Starting 4-Minute Time Arbitrage Strategy Generation ==="
echo "Target: Capture Alpha by front-running 5-minute candle closes using 4-minute signals validated by Microstructure metrics."

echo "[3/13] The 'Liquidity Hole' Sniper"
uv run python scripts/agent/run.py "4분 동안 거래량은 평소의 2배 이상 터졌는데 가격 변동폭(Range)이 0.1% 미만인 경우(Liquidity Hole/Iceberg)를 포착하라.
- 진입: 4분 00초 시점에 Order Flow Imbalance(OFI) 방향으로 진입.
[가설] 엄청난 거래량이 터졌는데 가격이 못 움직였다면 누군가 아이스버그 주문으로 다 받아낸 것이다. 5분봉 마감 직전 이 벽이 뚫리면 남은 1분 동안 폭발적인 시세가 나온다."

echo "[4/13] 4-Minute Funding Rate Scalper"
uv run python scripts/agent/run.py "실시간 펀딩비(Predicted Funding Rate)의 변화율을 4분봉 단위로 추적하라.
- 진입: 4분간 펀딩비가 급격히 상승(롱 쏠림) + 가격은 하락(Divergence) -> Short.
[가설] 8시간 마감이 아니더라도 펀딩비는 실시간으로 개미들의 포지션 쏠림을 보여준다. 4분봉 마감 즈음의 펀딩비 급변은 1분 뒤 봇들의 방향성을 예고한다."

echo "[5/13] VWAP Deviation on 4m Close"
uv run python scripts/agent/run.py "4분봉의 종가가 당일 VWAP(거래량 가중 평균가)에서 표준편차 2배 이상 벌어졌을 때 평균 회귀하라.
- 필터: 이때 VPIN이 낮아야 함 (낮은 독성 = 단순 노이즈). VPIN이 높으면 진입 금지.
[가설] 기관 알고리즘은 VWAP를 추종한다. 4분 시점에 VWAP와 너무 멀어졌다면, 남은 1분 동안 알고리즘이 가격을 VWAP 쪽으로 당겨놓으려 할 것이다."

echo "[6/13] OFI (Order Flow Imbalance) Pre-emption"
uv run python scripts/agent/run.py "4분 동안 누적된 OFI(주문 불균형) 값이 상위 10%일 때, 그 방향으로 진입하라.
- 로직: (매수체결량 - 매도체결량) > Threshold -> Long.
[가설] 주문 흐름(Flow)은 가격(Price)에 선행한다. 4분 동안 매수세가 압도적이었다면, 5분봉이 완성될 때까지 그 관성은 유지된다. 5분봉 캔들 색깔을 미리 맞추는 게임이다."

echo "[7/13] 4m Volatility Squeeze (Bollinger)"
uv run python scripts/agent/run.py "4분봉 기준 볼린저 밴드 폭이 극도로 좁아진(Squeeze) 상태에서 4분봉 종가가 밴드를 찢을 때 진입하라.
- 타겟: 5분봉 트레이더들이 '스퀴즈 발생'을 인지하기 1분 전에 진입.
[가설] 변동성 폭발 직전의 고요함은 4분봉에서 먼저 감지된다. 남들보다 1분 먼저 자리를 잡아야 슬리피지 없이 물량을 확보할 수 있다."

echo "[8/13] Sequential Counter (TD9 on 4m)"
uv run python scripts/agent/run.py "Tom Demark Sequential(TD9) 카운팅을 4분봉에 적용하여 추세 고갈을 노려라.
- 진입: 4분봉 기준 'Green 9' (9연속 상승) 발생 시 Short 준비. 단, 5분봉 마감 직전(4분 50초)에 진입.
[가설] 4분봉 9개는 36분이다. 크립토 인트라데이 추세가 한 방향으로 40분을 넘기는 힘들다. 5분봉 마감에 맞춰 차익실현 매물이 쏟아질 타이밍이다."

echo "[9/13] BTC-ETH Correlation Arbitrage (4m lag)"
uv run python scripts/agent/run.py "4분봉 기준 BTC는 양봉인데 ETH가 아직 음봉이거나 도지(Doji)인 상황을 포착하라.
- 진입: BTC 상승분 대비 ETH가 덜 올랐을 때 ETH Long.
[가설] 4분이라는 시간차는 메이저 알트코인이 대장주(BTC)를 따라가기에 충분히 짧지만, 5분봉 봇들에게는 '아직 완성 안 된' 시간이다. 갭 메우기(Catch-up)를 노린다."

echo "[10/13] The 'Volume Climax' Fade"
uv run python scripts/agent/run.py "4분봉 하나의 거래량이 직전 20개 평균의 5배 이상 터졌을 때(Buying/Selling Climax) 역매매하라.
- 필터: 캔들 꼬리가 몸통의 50% 이상일 것.
[가설] 4분 만에 평소의 5배가 거래됐다는 건 패닉 바잉/셀링의 정점이다. 5분봉이 마감될 땐 이미 추세가 꺾여 꼬리를 달고 있을 것이다."

echo "[11/13] Microstructure Support/Resistance Flip"
uv run python scripts/agent/run.py "과거 Order Book에서 매물대가 가장 두터웠던 가격(Weighted Mid Price)을 4분봉이 터치할 때 반응을 보라.
- 진입: 지지선 터치 후 4분봉 양봉 전환 시 Long.
[가설] 차트의 선(Line)이 아니라, 호가창의 잔량(Depth)이 진짜 지지선이다. 4분봉 마감 시점에 이 벽을 지켜냈다면 신뢰도가 매우 높다."

echo "[12/13] Gap Fill Strategy (Time-Bar Gap)"
uv run python scripts/agent/run.py "4분봉 시가(Open)와 직전 4분봉 종가(Close) 사이에 갭(Gap)이 발생하거나 급격한 장대봉의 50% 되돌림을 노려라.
- 진입: 급등 후 4분봉이 눌림목(0.5 Retracement)을 줄 때 지정가 매수.
[가설] 급등하는 5분봉 안에서도 4분 시점에는 차익실현으로 인한 눌림이 발생한다. 이때가 5분봉 추세를 타려는 자들에게 가장 유리한 평단가를 준다."

echo "[13/13] Regime Switching Meta-Agent"
uv run python scripts/agent/run.py "위 전략들을 시장 상황(Regime)에 따라 스위칭하는 메인 로직을 작성하라.
- 조건 1 (Trend): Slow VPIN(100 BTC) 높음 -> 1번(Front-Runner), 6번(OFI) 활성화.
- 조건 2 (Range): Slow VPIN 낮음 -> 5번(VWAP), 12번(Gap Fill) 활성화.
- 조건 3 (Crash): Fast VPIN(10 BTC) 극도로 높음 -> 2번(Divergence), 3번(Liquidity Hole) 활성화.
[가설] $1,000의 소액 계좌는 유연함이 무기다. 시장이 추세장인지 횡보장인지 VPIN으로 판단하여, 유리한 전략 카드만 꺼내 쓴다."

echo "=== All 4-Minute Strategies Generated ==="