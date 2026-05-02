# 포트폴리오 전략 개발 보고서

## 개요

TDD 기반으로 두 가지 포트폴리오 전략을 개발하고 백테스트했습니다.

- **개발 기간**: 2026-02-04 ~ 2026-02-05
- **테스트 기간**: 2025-01-01 ~ 2026-01-31 (13개월)
- **대상 코인**: BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT

---

## 1. 데이터 준비

### 다운로드
- **소스**: Binance Public Data (data.binance.vision)
- **데이터**: USDT-M 선물 aggTrades
- **기간**: 2025-01 ~ 2026-01 (13개월)
- **심볼**: 7개 메이저 코인

### 전처리
- 원본 tick 데이터 → 5분 OHLCV 캔들로 리샘플링
- 저장 위치: `/Users/jwcorp/trading_data/futures/candles/`

| 파일 | 크기 | 캔들 수 |
|------|------|---------|
| BTCUSDT_5m.parquet | 4.3MB | 105,981 |
| ETHUSDT_5m.parquet | 4.2MB | 105,405 |
| SOLUSDT_5m.parquet | 4.5MB | 114,045 |
| BNBUSDT_5m.parquet | 4.5MB | 114,045 |

---

## 2. 전략 1: Portfolio Momentum

### 개념
- 여러 코인의 수익률(모멘텀)을 비교
- 가장 강한 코인 롱, 가장 약한 코인 숏
- 주기적 리밸런싱

### 구현
- `src/intraday/strategies/multi/momentum.py`
- `src/intraday/backtest/multi_runner.py`

### 테스트 결과

| 설정 | IS (3~9월) | OS (10~1월) | 전체 |
|------|-----------|-------------|------|
| 롱온리, 4h 리밸런싱 | +2.02% | N/A | N/A |
| 롱온리, 1d 리밸런싱 | **+13.81%** | -8.89% | N/A |
| 롱/숏, 1d 리밸런싱 | -8.42% | **+5.12%** | **-7.51%** |

### 최적 파라미터
```yaml
lookback: 1440 min (1일)
rebalance: 1440 min (1일)
top_n: 1
bottom_n: 1 (롱/숏)
position_size: 30%
```

### 결론
- IS와 OS 성과가 불일치 → **과적합 위험**
- 단순 모멘텀으로는 안정적 수익 어려움
- 필터(변동성, 추세) 추가 필요

---

## 3. 전략 2: Pair Trading

### 개념
- 상관관계 높은 두 코인의 스프레드 트레이딩
- Z-score 기반 평균 회귀 전략
- 스프레드가 극단에서 중립으로 복귀할 때 수익

### 구현
- `src/intraday/strategies/multi/pair.py`
- `src/intraday/backtest/pair_runner.py`

### 테스트 결과

| 페어 | IS | OS | 전체 | 승률 |
|------|-----|-----|------|------|
| BTC/ETH | -30.03% | N/A | N/A | 61% |
| SOL/BNB | **+0.67%** | -1.54% | -13.82% | 68% |

### 최적 파라미터
```yaml
entry_zscore: 2.5
exit_zscore: 0.0
lookback: 576 (48h)
position_size: 50%
```

### 결론
- 승률은 높지만 손익비가 낮음
- 큰 손실 거래가 전체 성과를 훼손
- 손절선 추가 필요

---

## 4. TDD 테스트 현황

| 테스트 파일 | 테스트 수 | 상태 |
|------------|----------|------|
| test_portfolio_coin_momentum.py | 11 | ✅ Pass |
| test_pair_trading.py | 10 | ✅ Pass |
| test_portfolio_coin_backtest.py | 12 | ✅ Pass |
| **합계** | **33** | **✅ All Pass** |

---

## 5. 파일 구조

```
src/intraday/
├── strategies/
│   ├── multi/           # 포트폴리오 전용 전략 모듈
│   │   ├── __init__.py
│   │   ├── momentum.py      # Portfolio Momentum
│   │   └── pair.py          # Pair Trading
├── backtest/
│   ├── portfolio_backtest_runner.py      # Momentum 백테스터
│   └── pair_runner.py       # Pair Trading 백테스터
└── data/
    └── timeframe.py         # Timeframe 설정 로더

scripts/
├── download_data.py         # 데이터 다운로드
├── preprocess_data.py       # OHLCV 전처리
├── run_portfolio_momentum_candles.py  # Portfolio 백테스트
└── run_pair_trading.py      # Pair Trading 백테스트

config/
└── timeframes.yaml          # EDA/IS/OS 기간 설정
```

---

## 6. 향후 개선 방향

### 단기
1. **손절선 추가**: Pair Trading에 최대 손실 제한
2. **변동성 필터**: 변동성 높을 때만 진입
3. **추세 필터**: 추세 방향과 일치할 때만 진입

### 중기
1. **머신러닝 모델**: 진입/청산 타이밍 예측
2. **포트폴리오 최적화**: 여러 전략 조합
3. **실시간 연동**: Forward Test 통합

### 장기
1. **자동 파라미터 최적화**: Walk-forward optimization
2. **리스크 관리 고도화**: Kelly Criterion, VaR
3. **실전 배포**: Paper Trading → Live Trading

---

## 7. 결론

단순한 포트폴리오 전략(Momentum, Pair Trading)만으로는 **안정적인 수익을 내기 어렵습니다**.

하지만 이번 작업으로:
- ✅ TDD 기반 전략 개발 프레임워크 구축
- ✅ 포트폴리오 백테스트 인프라 완성
- ✅ 데이터 파이프라인 구축 (다운로드 → 전처리 → 백테스트)

이 기반 위에 더 복잡한 전략을 빠르게 테스트할 수 있습니다.
