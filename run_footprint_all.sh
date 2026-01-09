#!/bin/bash
set -e

echo "=== Starting Sequential Agent Runs (Pure Footprint & Microstructure Alpha) ==="


# [Pattern 2: Imbalance] Stacked Imbalance Momentum
echo "[3/13] Stacked Imbalance Drive"
uv run python scripts/agent/run.py "Footprint 상에서 3개 이상의 연속된 Price Node가 한쪽 방향으로 300% 이상 Imbalance(매수량이 매도량의 3배 등)를 보일 때 추세 추종 진입.
- 조건: Consecutive Nodes Imbalance Ratio > 3.0 AND Price Trend Direction Consistent.
- 논리: 'Stacked Imbalance'는 기관의 알고리즘이 특정 가격대 구간을 'Sweep' 해버린 흔적이다. 이는 강력한 모멘텀의 시작점이다."

# [Pattern 3: Exhaustion] V-Shape Reversal
echo "[4/13] Exhaustion Gap Fade"
uv run python scripts/agent/run.py "신규 고점/저점에서 거래량이 급감하며 Delta(순매수-순매도)가 반전될 때 역추세 진입.
- 조건: New High Price + Top Node Volume < Bottom Node Volume * 0.1 (Tip Exhaustion).
- 논리: 고점에서 더 이상 매수할 사람이 없는 '매수세 고갈(Exhaustion)' 상태다. 유동성 공백으로 인해 적은 매도세로도 가격은 급락한다."

# [Pattern 4: Trapped Traders] Stop-Run Hunting
echo "[5/13] Trapped Buyers/Sellers Strategy"
uv run python scripts/agent/run.py "직전 Bar의 POC(Point of Control) 위에서 매수했거나 아래에서 매도한 물량이 현재 가격 반대편에 고립될 때 진입.
- 조건: Previous Bar POC > Current Price AND Previous Bar Delta > 0 (매수 우위였으나 가격 하락).
- 논리: 고점에서 매수한 'Trapped Buyers'는 가격이 하락하면 손절(Sell) 물량을 쏟아내며 하락을 가속화시킨다. 이들의 고통(Pain)을 수익화한다."

# [Pattern 5: OBI Proxy] Liquidity Replenishment
echo "[6/13] Derived OBI Liquidity Scalping"
uv run python scripts/agent/run.py "단시간 내에 특정 가격대에서 반복적으로 체결이 일어나지만 가격이 뚫리지 않는 'Iceberg Order'를 감지하여 반대 방향 스캘핑.
- 로직: Trade Frequency High + Price Displacement $\approx$ 0 $\rightarrow$ Hidden Liquidity(Iceberg) Detection.
- 논리: 눈에 보이지 않는 거대 호가(Iceberg)가 존재하는 곳은 강력한 지지/저항선이다."

# [Pattern 6: Delta Divergence] Limit vs Market
echo "[7/13] CVD (Cumulative Volume Delta) Divergence"
uv run python scripts/agent/run.py "가격은 고점을 높이는데 CVD(누적 순매수량)는 낮아지는 다이버전스 발생 시 매도 진입.
- 조건: Price High($t$) > Price High($t-1$) BUT CVD($t$) < CVD($t-1$).
- 논리: 가격 상승을 주도하는 것이 공격적인 매수세(Market Buy)가 아니라, 매도 호가의 공백(Thin Book) 때문임을 시사한다. 이는 가짜 상승이다."

# [Pattern 7: Auction Theory] Unfinished Business
echo "[8/13] Failed Auction (Unfinished Business) Target"
uv run python scripts/agent/run.py "Footprint의 상단/하단 끝에서 매수/매도 물량이 남아있는(Imbalance가 해소되지 않은) 상태로 Bar가 마감되면, 해당 가격을 다시 터치하러 갈 때 진입.
- 논리: 경매 이론상 호가창의 끝은 '0'이어야 한다. 매수/매도 잔량이 남은 상태로 회군했다면 시장은 반드시 그 가격을 다시 테스트하여 유동성을 확인하려는 성질(Magnet Effect)이 있다."

# [Pattern 8: Value Area] POC Migration
echo "[9/13] Value Area Migration Following"
uv run python scripts/agent/run.py "최근 $N$개 Bar의 POC(최대 거래량 가격)와 Value Area(거래량의 70% 구간)가 일관되게 상승/하락할 때 추세 추종.
- 논리: 단순 가격 이동이 아니라 '거래가 합의된 가격대(Fair Value)' 자체가 이동하는 것이 진짜 추세다."

# [Pattern 9: Volatility] Delta Percentile Breakout
echo "[10/13] Absolute Delta Breakout"
uv run python scripts/agent/run.py "Bar의 순매수/매도 총량(Delta)이 지난 100개 Bar의 95분위수(Percentile)를 초과할 때 해당 방향으로 모멘텀 진입.
- 논리: 평소와 다른 막대한 자금 유입(Inflow)은 새로운 추세의 시작을 알리는 'Ignition Bar'일 확률이 높다."

# [Pattern 10: Correction] Large Lot Reversion
echo "[11/13] Large Lot Mean Reversion"
uv run python scripts/agent/run.py "필터링된 대량 체결(Large Lots, e.g., > 5 BTC/tick)만 따로 집계하여, 이들의 진입 방향과 단기 가격이 과도하게 벌어졌을 때(Dislocation) 대량 체결 방향으로 회귀 매매.
- 논리: 고래(Smart Money)의 평단가는 강력한 중력장 역할을 한다. 가격이 노이즈로 인해 이탈하더라도 결국 고래의 평단가로 수렴한다."

# [Pattern 11: Speed] Velocity-Based Impulse
echo "[12/13] Trade Velocity Impulse"
uv run python scripts/agent/run.py "단위 시간당 체결 횟수(Velocity)가 급증하면서 특정 방향의 Imbalance가 동반될 때 스캘핑 진입.
- 조건: Trades per Second > 2$\sigma$ AND Delta Direction is Clear.
- 논리: HFT 알고리즘들이 동시에 반응하는 순간이다. 방향성을 고민하지 말고 속도에 편승해야 한다."

# [Orchestration] Strategy Ensemble
echo "[13/13] Microstructure Master Ensemble"
uv run python scripts/agent/run.py "위의 전략들의 시그널을 취합하되, 'High Volatility(Trend)' 국면에서는 Stacked Imbalance/Breakout에 가중치를, 'Low Volatility(Range)' 국면에서는 Absorption/Exhaustion에 가중치를 두는 메타 모델.
- 입력: 각 전략의 시그널 (-1, 0, 1) 및 확신도(Confidence Score).
- 출력: 최종 포지션 Sizing."

echo "=== All Footprint Strategy Agents Executed Successfully ==="