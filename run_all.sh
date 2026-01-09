#!/bin/bash
set -e

echo "=== Starting Sequential Agent Runs (Pure Strategy Logic) ==="


echo "[3/13] Safe Zone Market Making"
uv run python scripts/agent/run.py "Fast/Slow VPIN이 모두 Low Toxicity 구간(Safe Zone)일 때 RSI 역매매(Mean Reversion)를 수행하라. - 필터: 포지션 보유 중 Fast VPIN 급등 시 즉시 청산 - 논리: 정보 비대칭이 없는 'Noise Trading' 구간에서만 스프레드를 수취한다."

echo "[4/13] OFI Divergence Sniper"
uv run python scripts/agent/run.py "가격 변동성이 낮은 상태에서 OFI(주문 불균형) 누적값이 급증하고 Fast VPIN이 상승할 때 진입하라. - 논리: 가격이 움직이기 전, 체결 데이터(OFI)와 독성(VPIN)이 먼저 반응하는 선행성을 포착한다."

echo "[5/13] VPIN-Validated Breakout"
uv run python scripts/agent/run.py "가격이 주요 레벨을 돌파할 때 Slow VPIN CDF가 High 상태인지 확인하라. - 진입: Breakout + High Slow VPIN (진성 돌파) - 무시: Breakout + Low Slow VPIN (Fakeout/Stop Hunting) - 논리: 정보(VPIN)가 실리지 않은 돌파는 신뢰하지 않는다."

echo "[6/13] Volatility-Adjusted Sizing"
uv run python scripts/agent/run.py "Slow VPIN CDF 값에 반비례하여 진입 포지션 사이즈를 조절하라. - 로직: Size = Base_Size * (1 - VPIN_CDF) - 논리: 정보 불확실성(독성)이 높을수록 변동성 위험이 크므로 비중을 줄여 리스크를 제어한다."

echo "[7/13] Liquidity Hole Short"
uv run python scripts/agent/run.py "High Fast VPIN 상태에서 Order Book Depth(호가 잔량)가 급감할 때 매도(Short) 대응하라. - 조건: High VPIN + Low Liquidity -> Short - 논리: 독성 매물이 나오는데 받아줄 호가가 얇아지면 가격 급락(Flash Crash)이 발생한다."

echo "[8/13] Cross-Asset Lead-Lag"
uv run python scripts/agent/run.py "BTC의 Fast VPIN 스파이크 발생 시, 시차를 두고 ETH/Altcoin의 동일 방향으로 진입하라. - 논리: 시장의 독성 정보는 BTC에 먼저 반영되며, 알트코인은 이를 후행적으로 반영한다."

echo "[9/13] Regime-Based Stop Loss"
uv run python scripts/agent/run.py "Slow VPIN 레짐에 따라 손절(Stop-Loss) 폭을 차등 적용하라. - High VPIN Regime: Tight Stop (빠른 손절) - Low VPIN Regime: Wide Stop (노이즈 허용) - 논리: 독성 시장에서의 역행은 위험하며, 비독성 시장에서의 변동은 단순 노이즈다."

echo "[10/13] Duration Momentum"
uv run python scripts/agent/run.py "Volume Bar 생성 소요 시간(Duration)이 급감하고 Fast VPIN이 상승할 때 추세 추종으로 진입하라. - 논리: 거래 체결 속도가 비정상적으로 빨라지는 것 자체가 강력한 정보 유입 신호다."

echo "[11/13] Funding Rate & VPIN Filter"
uv run python scripts/agent/run.py "High Funding Rate 상황에서 Slow VPIN을 필터로 역매매 여부를 결정하라. - High Funding + Low VPIN -> Fade (반대 매매) - High Funding + High VPIN -> Follow (추세 지속) - 논리: 스마트 머니(High VPIN)가 비용을 지불하며 포지션을 잡는다면 추세는 지속된다."

echo "[12/13] Iceberg Detection"
uv run python scripts/agent/run.py "가격 변화 없이 체결량만 증가하며 VPIN이 상승하는 구간을 포착하여 해당 방향으로 진입하라. - 논리: 호가창에 드러나지 않는 숨겨진 주문(Iceberg)이 독성 정보를 처리하고 있음을 탐지한다."

echo "[13/13] Regime Switching Master"
uv run python scripts/agent/run.py "현재 VPIN 상태에 따라 활성화할 전략 그룹을 스위칭하라. - High Fast VPIN -> Momentum/Scalping 전략군 활성화 - Low VPIN -> Mean-Reversion/MM 전략군 활성화 - 논리: 시장의 정보 상태(VPIN)에 따라 승률이 높은 전략군은 정해져 있다."

echo "=== All Agent Runs Completed ==="