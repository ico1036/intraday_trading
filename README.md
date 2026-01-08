# Intraday Trading

Binance BTCUSDT 선물 전략 백테스트 시스템

## 설치

```bash
uv sync
```

## 뭘 실행하면 되나요?

### 1. AI로 전략 자동 개발 (권장)

아이디어만 입력하면 AI가 전략 설계 → 구현 → 백테스트까지 자동 수행합니다.

```bash
uv run python scripts/agent/run.py "VPIN 기반 모멘텀 필터 전략"
```

**결과물**: `{전략명}_dir/` 폴더에 전략 코드, 테스트, 백테스트 리포트 생성

### 2. 수동 백테스트

기존 전략이나 직접 만든 전략을 백테스트합니다.

```bash
uv run python scripts/run_tick_backtest.py
```

### 3. 실시간 테스트

실시간 데이터로 전략을 검증합니다.

```bash
uv run python scripts/run_forward_test.py
```

## AI Agent 워크플로우

```
아이디어 입력 → Researcher(설계) → Developer(구현) → Analyst(검증)
                     ↑                                    │
                     └──────── 개선 필요시 피드백 ─────────┘
```

| 단계 | 역할 | 결과물 |
|------|------|--------|
| Researcher | 가설 설계, 리스크 분석 | `algorithm_prompt.txt` |
| Developer | 전략 코드 구현 | `{name}.py`, 테스트 |
| Analyst | 백테스트 실행 | `backtest_report.md` |

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
├── run_tick_backtest.py # 백테스트 실행
├── run_forward_test.py  # 실시간 테스트
└── agent/               # AI Agent 시스템
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

## 테스트

```bash
uv run pytest tests/ -v
```
