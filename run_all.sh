#!/bin/bash
set -e

echo "=== Starting Sequential Agent Runs ==="

echo "[1/13] VPIN 기본 구현"
uv run python scripts/agent/run.py "바이낸스 BTCUSDT 선물, Volume Bar 50 BTC로 VPIN을 구현하라. - BVC(Bulk Volume Classification)로 Buy/Sell 분류 - 50개 버킷 rolling window로 VPIN 계산 [가설] 정보를 가진 트레이더(Informed Trader)는 대량 주문을 넣는다. 이들의 거래 비중이 높아지면 VPIN이 상승한다. VPIN은 '시장에 정보 비대칭이 얼마나 존재하는가'를 수치화한 것이다."

echo "[2/13] VPIN 기반 가격 점프 예측"
uv run python scripts/agent/run.py "바이낸스 BTCUSDT 선물, Volume Bar 50 BTC로 VPIN 기반 가격 점프 예측 시스템을 만들어라. - VPIN 급등(1-sigma 이상) 감지 - 점프 방향은 Order Imbalance sign으로 예측 [가설] Informed Trader는 큰 뉴스가 터지기 전에 먼저 움직인다. 그들의 대량 매수/매도가 VPIN을 밀어올리고, 15-30분 후 가격이 따라온다. VPIN spike는 '누군가 뭔가를 알고 있다'는 신호다."

echo "[3/13] Momentum + VPIN 필터"
uv run python scripts/agent/run.py "바이낸스 BTCUSDT 선물, Volume Bar 50 BTC로 Momentum 신호를 VPIN으로 필터링하라. - Momentum 양수 + VPIN 낮음 → Long - Momentum 양수 + VPIN 높음 → 진입 보류 [가설] 모든 모멘텀이 같지 않다. Retail이 만든 모멘텀(Low VPIN)은 지속성이 있다. 하지만 Informed Trader가 만든 모멘텀(High VPIN)은 이미 정보가 반영 중이므로 늦게 진입하면 역전당한다. VPIN은 '이 추세에 올라타도 되는가'를 판별한다."

echo "[4/13] Order Flow Imbalance + VPIN"
uv run python scripts/agent/run.py "바이낸스 BTCUSDT 선물, Volume Bar 50 BTC로 Order Flow Imbalance와 VPIN을 결합하라. - OFI 강함 + VPIN 낮음 → Organic Flow, 추종 - OFI 강함 + VPIN 높음 → Informed Flow, 조기 진입 고려 [가설] OFI는 '방향'을 알려주고, VPIN은 '품질'을 알려준다. 같은 매수 우위라도 Retail 매수(Low VPIN)는 천천히 오르고, Informed 매수(High VPIN)는 급등 후 조정이 온다. 둘을 조합하면 진입 타이밍과 포지션 사이즈를 최적화할 수 있다."

echo "[5/13] VPIN 기반 동적 레버리지"
uv run python scripts/agent/run.py "바이낸스 BTCUSDT 선물, Volume Bar 50 BTC로 VPIN에 따른 동적 레버리지 시스템을 구현하라. - VPIN 낮음: 5x - VPIN 중간: 2-3x - VPIN 높음: 1x 또는 청산 [가설] High VPIN = High Uncertainty. 정보 비대칭이 클 때 큰 베팅을 하면 Informed Trader에게 털린다. 반대로 Low VPIN 환경은 '공정한 게임'이므로 확신 있는 신호에 레버리지를 실어도 된다. 레버리지는 시장 상태의 함수여야 한다."

echo "[6/13] VPIN 기반 동적 Stop-Loss"
uv run python scripts/agent/run.py "바이낸스 BTCUSDT 선물, Volume Bar 50 BTC로 VPIN에 따른 동적 Stop-Loss를 구현하라. - Low VPIN: ATR 2배 넓은 스탑 - High VPIN: ATR 1배 타이트 스탑 [가설] Low VPIN 환경은 노이즈가 많아도 추세가 유지된다. 넓은 스탑으로 휩소를 버텨야 한다. High VPIN 환경은 급변이 예고된 상태다. 틀리면 빠르게 손절해야 큰 손실을 피한다. 스탑 거리는 '현재 시장이 얼마나 위험한가'에 비례해야 한다."

echo "[7/13] Volume Bar vs Time Bar 비교"
uv run python scripts/agent/run.py "바이낸스 BTCUSDT 선물에서 Volume Bar 50 BTC와 Time Bar 5분봉의 동일 전략 성능을 비교하라. - 동일한 RSI Mean-Reversion 전략 적용 [가설] Time Bar는 정보 도착과 무관하게 균일한 간격이다. 새벽의 한산한 5분과 뉴스 직후의 폭발적인 5분이 같은 무게를 갖는다. Volume Bar는 '시장이 X만큼 거래했을 때'를 1단위로 정의하므로 정보 밀도가 균일하다. 통계적 성질이 좋아져 신호 품질이 올라간다."

echo "[8/13] 가격-VPIN 다이버전스 반전"
uv run python scripts/agent/run.py "바이낸스 BTCUSDT 선물, Volume Bar 50 BTC로 가격-VPIN 다이버전스 반전 전략을 만들어라. - 가격 신고점 + VPIN 상승 → Short 준비 - 가격 신저점 + VPIN 하락 → Long 준비 [가설] 가격이 신고점을 찍는데 VPIN이 오른다면, Informed Trader가 고점에서 팔고 있다는 뜻이다. 그들은 우리보다 먼저 안다. 반대로 가격이 떨어지는데 VPIN이 낮아지면 매도 압력이 소진 중이다."

echo "[9/13] Funding Rate + VPIN"
uv run python scripts/agent/run.py "바이낸스 BTCUSDT 선물, Volume Bar 50 BTC로 Funding Rate와 VPIN을 결합한 전략을 만들어라. - High Funding + High VPIN → Short - Low Funding + High VPIN → Long [가설] Funding Rate는 Retail 심리를 반영하고, VPIN은 Informed 행동을 반영한다. 둘이 같은 방향이면 강한 추세. 둘이 반대면 Retail이 틀린 쪽에 서있다는 뜻이다. Informed를 따라가고 Retail을 Fade하라."

echo "[10/13] 다중 타임프레임 VPIN"
uv run python scripts/agent/run.py "바이낸스 BTCUSDT 선물, Volume Bar 50 BTC로 다중 타임프레임 VPIN을 분석하라. - Short VPIN: 20 버킷 window - Long VPIN: 100 버킷 window [가설] 단기 VPIN spike는 일시적 정보 충격일 수 있다. 하지만 장기 VPIN도 함께 상승 중이라면 구조적으로 Informed 비중이 높아지고 있다는 뜻이다. 단기만 spike하고 장기는 안정적이면 노이즈로 무시해도 된다. 다중 타임프레임은 신호와 노이즈를 분리한다."

echo "[11/13] VPIN Breakout 필터"
uv run python scripts/agent/run.py "바이낸스 BTCUSDT 선물, Volume Bar 50 BTC로 VPIN 기반 Breakout 필터를 만들어라. - Breakout + VPIN 상승 → Real Breakout (추종) - Breakout + VPIN 하락 → Fake Breakout (Fade) [가설] 진짜 Breakout은 Informed Trader가 동반한다. 그들이 브레이크아웃 방향으로 대량 매수/매도를 넣으면 VPIN이 오른다. 반대로 가격만 뚫고 VPIN이 안 오르면 유동성 사냥(Stop Hunting)일 가능성이 높다. VPIN은 브레이크아웃의 '진위'를 판별한다."

echo "[12/13] BTC-ETH VPIN 상관관계"
uv run python scripts/agent/run.py "바이낸스에서 BTCUSDT와 ETHUSDT 선물의 VPIN 상관관계를 분석하라. - BTC: Volume Bar 50 BTC - ETH: Volume Bar 500 ETH (비슷한 USD 규모) [가설] BTC가 크립토의 선행 지표다. BTC에서 Informed 활동이 먼저 나타나고 ETH가 따라온다. BTC VPIN이 급등하면 ETH에서 Mean Reversion 진입 기회를 포착한다."

echo "[13/13] HMM 기반 VPIN 레짐 분류"
uv run python scripts/agent/run.py "바이낸스 BTCUSDT 선물, Volume Bar 50 BTC로 HMM 기반 VPIN 레짐 분류 시스템을 만들어라. - State 1 (Low Toxicity): Mean Reversion 전략 - State 2 (Medium Toxicity): Trend Following 전략 - State 3 (High Toxicity): Defensive, 현금화 [가설] 시장은 단일 상태가 아니다. Low VPIN 구간에서는 가격이 평균 회귀하고, High VPIN 구간에서는 추세가 지속된다. 레짐에 따라 전략을 선택하면 단일 전략보다 적응력이 높다."

echo "=== All Agent Runs Completed ==="
