# Intraday Trading

Binance BTCUSDT 선물 전략 백테스트 시스템

## 설치

```bash
cd /Users/jwcorp/intraday_trading
uv sync
```

## 실행 환경 (.env)

`intraday_trading`은 하드코딩 경로를 버리고 `.env` 기반으로 동작합니다.

```bash
cp .env.example .env
# 필요시 경로/키만 수정
```

예시:

```bash
INTRADAY_DATA_DIR=./data
INTRADAY_CONFIG_PATH=./config/timeframes.yaml
```

## 뭘 실행하면 되나요?

### 1. AI로 전략 자동 개발 (권장)

아이디어만 입력하면 AI가 전략 설계 → 구현 → 백테스트까지 자동 수행합니다.

```bash
uv run python scripts/agent/run_v2.py alpha_run
# PLAN.md의 Strategy request를 수정한 뒤:
uv run python scripts/agent/run_v2.py alpha_run --run
```

**결과물**: `archive/alpha_run/` 아래에 thesis, expression, 전략 코드, 테스트, `weights.parquet`, `metrics.json`, 백테스트 리포트 생성

### 2. 수동 백테스트

기존 전략이나 직접 만든 전략을 백테스트합니다.

```bash
uv run python scripts/run_tick_backtest.py
```

### 3. 실시간 Forward Test

실시간 Binance 데이터로 전략을 검증합니다.

```bash
# 심볼 수와 무관하게 동일 포트폴리오 파이프라인으로 처리되는 실시간 테스트는 run_portfolio_forward_test.py에서 관리
uv run python scripts/run_portfolio_forward_test.py --help

# VPIN Top5 포트폴리오 (예: BTC/ETH)
uv run python scripts/run_portfolio_forward_test.py --strategy vpin_top5 --symbols BTCUSDT ETHUSDT --candle-type volume --candle-size 100 --duration 3600

# 포트폴리오 모멘텀 예시
uv run python scripts/run_portfolio_forward_test.py --strategy momentum --symbols BTCUSDT ETHUSDT SOLUSDT --lookback 60 --top-n 1

# 단일 심볼도 단일 심볼 모드로 실행 가능
uv run python scripts/run_portfolio_forward_test.py --strategy momentum --symbols BTCUSDT --top-n 1

# 무한 실행 (Ctrl+C로 종료, 결과 리포트 출력됨)
uv run python scripts/run_portfolio_forward_test.py --strategy momentum --symbols BTCUSDT ETHUSDT
```

## AI Agent 워크플로우

```
아이디어 입력 → 단일 에이전트가 Research → Develop → Analyze 단계를 순차 실행
                         ↑                              │
                         └──── 개선 필요시 다음 단계로 반복 ────┘
```

| 단계 | 역할 | 결과물 |
|------|------|--------|
| Research | 가설 설계, 리스크 분석 | `algorithm_prompt.txt` |
| Develop | 전략 코드 구현 | `{name}.py`, 테스트 |
| Analyze | 백테스트 실행, weight/metrics 저장 | `weights.parquet`, `metrics.json`, `backtest_report.md` |

## 핵심 설정

| 항목 | 값 | 설명 |
|------|-----|------|
| 운용자산 | $100K | 백테스트 기준 |
| 리스크 관리 | 2% Rule | Leverage = 2% / Stop Loss |
| bar_size | >= 10.0 BTC | Volume bar 최소값 |

## 더 알아보기

<details>
<summary>프로젝트 구조</summary>

```
src/intraday/
├── strategies/           # 전략 구현
│   ├── tick/            # Tick 기반 전략
│   └── orderbook/       # Orderbook 기반 전략
├── backtest/            # 백테스터
└── data/                # 데이터 다운로드/로딩

scripts/
├── run_tick_backtest.py         # 백테스트 실행
├── run_portfolio_forward_test.py   # 유니버스 공통 실시간 테스트
└── agent/                      # AI Agent 시스템
    └── run.py           # Agent 진입점
```

</details>

<details>
<summary>선물 거래 (레버리지, 청산)</summary>

- `leverage > 1` 설정 시 선물 모드 활성화
- 공매도 가능 (BTC 없이 SELL)
- Binance USDT-M Isolated Margin 청산 공식 적용
- Funding Rate 8시간마다 정산

| 레버리지 | 청산 거리 |
|---------|----------|
| 10x | ~9.6% |
| 20x | ~4.6% |
| 100x | ~0.6% |

</details>

<details>
<summary>Bar 타입</summary>

| 타입 | 설명 | 예시 |
|-----|------|------|
| VOLUME | 거래량 기반 | 10 BTC마다 바 생성 |
| TICK | 체결 횟수 기반 | 100틱마다 바 생성 |
| TIME | 시간 기반 | 60초마다 바 생성 |
| DOLLAR | 달러 기반 | $1M마다 바 생성 |

</details>


## IS/OOS 워크플로우 규칙

전략 검증은 반드시 **IS(학습/튜닝)** 과 **OS(최종검증)** 를 분리해서 진행합니다.

- IS: 전략 파라미터 점검/개선에 사용
- OS: 최종 성능 확인용 (피드백에 직접 재사용 금지)
- 기본 룰과 과적합 경고 기준은 `docs/IS_OS_VALIDATION_RULES.md` 참조

빠른 실행:
```bash
uv run python scripts/validate_is_os.py \
  --strategy VPINTop5RebalanceStrategy \
  --symbols BTCUSDT ETHUSDT SOLUSDT BNBUSDT DOGEUSDT \
  --data-path ./data/futures_ticks \
  --bar-type VOLUME --bar-size 20 \
  --is-start 2025-03-01 --is-end 2025-03-31 \
  --os-start 2025-10-01 --os-end 2025-11-30
```

## 테스트

```bash
uv run pytest tests/ -v
```
