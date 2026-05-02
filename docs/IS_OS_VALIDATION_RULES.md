# IS/OOS 검증 룰 (Backtest Workflow)

> 목표: `백테스트 결과의 과적합 위험`을 줄이고, 실제 운영 판단용 신호를 안정화

## 1) 기본 규칙

1. **IS/OOS는 항상 분리한다.**
   - `IS`는 전략 튜닝용
   - `OS`는 최종 검증용
   - `OS` 결과를 다시 튜닝 피드백에 사용하지 않는다.

2. **최소 데이터 룰**
   - `IS`/`OS` 모두 `trade_count >= 5`가 있어야 판단 유효
   - `IS`가 5 미만이면 **결과 미완료**(Need Improvement)
   - `Sharpe < -0.5`면 **결함 후보**로 간주

3. **기간은 트레이딩 빈도별로 달리 설정**
   - HFT(>100 trades/day): IS 3일 / OS 1주
   - MFT(10-100 trades/day): IS 2주 / OS 1개월
   - LFT(<10 trades/day): IS 1개월 / OS 2개월

4. **기본 기간 가이드(2025-2026 데이터 사용 시 권장)**
   - IS 후보: `2025-03-01 ~ 2025-09-30`
   - OS 후보: `2025-10-01 ~ 2026-01-31`
   - 위 범위는 전략 빈도에 따라 조정 가능

---

## 2) 지표 판정 기준

### IS 판정 (튜닝 허용)

- Total Return: 최소 **0%** (음수면 먼저 수정)
- Sharpe: 최소 `-0.5`
- Max Drawdown: `-25%` 미만은 주의
- Total Trades: `>= 5`
- Win Rate: 10% 미만은 재설계 후보

### OS 판정 (최종 검증)

- IS와 OS 비교:
  - Return: `OS >= IS * 0.5` 권장
  - Sharpe 부호 동일 권장 (부호 반대 시 overfit 경고)
  - Win Rate 차이 > 20%면 overfit 경고

---

## 3) 결과 사용 원칙

- `IS` 결과는 피드백 루프용
- `OS` 결과는 보고서 및 의사결정용
- 동일 전략 반복 테스트 시에도 
  - 매번 동일한 룰을 적용
  - OS에서 과적합 경향이 높으면 파라미터 범위를 축소/재설계

---

## 4) 위반 시 액션

- **IS 실패**: 전략 신호/파라미터 조정, 개발·연구 단계로 회귀
- **OS 과적합 경고**: 현재 파라미터 대역 축소, feature 검증, 리밸런싱 규칙 고정 후 재검증
- **두 구간 모두 OK**: 실전 고려 or 확장 실험(다중 기간) 실행

---

## 5) 실행 스크립트

`scripts/validate_is_os.py` (예정)로 다음 형식 실행:

```bash
uv run python scripts/validate_is_os.py \
  --strategy VPINTop5RebalanceStrategy \
  --symbols BTCUSDT ETHUSDT SOLUSDT BNBUSDT DOGEUSDT \
  --data-path ./data/futures_ticks \
  --bar-type VOLUME --bar-size 20 \
  --is-start 2025-03-01 --is-end 2025-03-31 \
  --os-start 2025-10-01 --os-end 2025-11-30
```

이 스크립트는 IS/OOS 지표를 한 번에 계산하고, 과적합 판정 규칙을 자동 출력한다.