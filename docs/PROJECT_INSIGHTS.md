# Intraday Trading Project Insights

작성일: 2026-05-01

## 1. 한 줄 요약

이 프로젝트는 Binance USDT-M 선물 중심의 인트라데이 전략 연구 플랫폼이다. 단순 백테스트 코드가 아니라, 틱 데이터 수집/캔들화, 단일/포트폴리오 백테스트, 실시간 포워드 테스트, 페이퍼 트레이딩, 전략 자동 생성 에이전트까지 포함한 연구 자동화 시스템으로 진화하고 있다.

## 2. 현재 프로젝트의 실제 성격

README의 표면 설명은 "Binance BTCUSDT 선물 전략 백테스트 시스템"이지만, 코드 기준으로는 범위가 더 넓다.

- 단일 심볼 틱 백테스트: `src/intraday/backtest/tick_runner.py`
- 다중 심볼 포트폴리오 틱 백테스트: `src/intraday/backtest/multi_tick_runner.py`
- 실시간 포트폴리오 포워드 테스트: `src/intraday/multi_forward_runner.py`
- 페이퍼 트레이딩/체결/수수료/레버리지/청산 시뮬레이션: `src/intraday/paper_trader.py`
- 전략 인터페이스와 시장 상태 공통 모델: `src/intraday/strategy.py`
- AI 전략 개발 루프 v1/v2: `scripts/agent/`
- 결정론적 연구 하네스 v2: `scripts/agent/v2/deterministic/`
- 전략 온톨로지와 표현 공간: `config/*.yaml`, `strategies_ontology.json`

따라서 이 저장소의 중심 가치는 "전략 하나를 백테스트하는 코드"보다 "전략 아이디어를 반복 실험 가능한 연구 단위로 바꾸는 시스템"에 있다.

## 3. 핵심 도메인 모델

### MarketState / Order

`src/intraday/strategy.py`의 `MarketState`와 `Order`가 전략과 실행 엔진 사이의 공통 계약이다.

- `Order`: 방향, 수량, 주문 타입, 지정가, 손절/익절 메타데이터, 포트폴리오 비중을 표현한다.
- `MarketState`: 주문서 기반 필드, OHLCV, VWAP, 현재 포지션, 심볼, 패널 데이터, 포트폴리오 포지션까지 담는다.
- `PortfolioOrder`: 한 번의 전략 호출에서 여러 심볼 주문을 반환할 수 있게 만든 확장 타입이다.

인사이트: `MarketState`가 단일 심볼 주문서 전략에서 포트폴리오 캔들 전략까지 모두 수용하도록 확장되어 있다. 유연성은 높지만, 필드가 많아질수록 "어떤 runner가 어떤 필드를 보장하는가"가 흐려질 수 있다.

### CandleBuilder

`src/intraday/candle_builder.py`는 틱을 네 가지 bar domain으로 변환한다.

- Volume bar
- Tick bar
- Time bar
- Dollar bar

인사이트: 이 프로젝트의 전략 연구는 시간봉보다 이벤트 기반 바(volume/tick/dollar)에 무게를 둔다. 이는 인트라데이/마이크로스트럭처 전략에 적합한 방향이다.

### PaperTrader

`src/intraday/paper_trader.py`는 현물/선물을 하나의 시뮬레이터에서 처리한다.

- maker/taker fee 분리
- 주문 큐와 TTL
- 레버리지 기반 선물 모드
- 공매도
- 청산가 계산
- realized/unrealized PnL 추적

인사이트: 백테스트 성과를 현실적으로 낮추는 비용 모델이 이미 들어가 있다. 단, 수수료 기본값에 spread/slippage까지 합산되어 있어 실제 거래소 수수료만 비교하면 과대하게 보일 수 있다. 이 의도는 문서에 더 명확히 남기는 편이 좋다.

## 4. 실행 흐름

### 수동 백테스트

대표 진입점은 다음 스크립트들이다.

- `scripts/run_tick_backtest.py`
- `scripts/run_orderbook_backtest.py`
- `scripts/run_vpin_backtest.py`
- `scripts/run_portfolio_momentum.py`
- `scripts/run_workflow_portfolio_backtest.py`
- `scripts/validate_is_os.py`

`TickBacktestRunner`의 기본 흐름은 다음과 같다.

1. `TickDataLoader`가 historical aggTrade를 순회한다.
2. `CandleBuilder`가 지정된 bar type/size로 캔들을 만든다.
3. 캔들 완성 시 strategy가 `MarketState`를 받아 주문을 만든다.
4. `PaperTrader`가 latency, fee, 체결, 포지션, PnL을 반영한다.
5. `PerformanceReport`가 결과를 산출한다.

### 포트폴리오 백테스트

`PortfolioTickBacktestRunner`는 여러 심볼의 틱 스트림을 `heapq.merge`로 시간순 병합한다.

인사이트: 심볼별 캔들 빌더와 최신 캔들을 유지하고, panel 형태로 전략에 넘기는 구조는 크로스섹션/랭킹 전략에 적합하다. 다만 포트폴리오 러너 내부에 포지션/체결 로직이 별도로 존재해 `PaperTrader`와 책임이 일부 중복된다.

### 실시간 포워드 테스트

`PortfolioForwardRunner`는 Binance aggTrade 스트림을 받아 포트폴리오 전략을 실시간으로 페이퍼 트레이딩한다.

- 심볼별 `SymbolState`가 실시간 가격/캔들 상태를 관리한다.
- 리밸런싱 주기마다 전략 신호를 실행한다.
- rebalance, execution, weight, NAV 이벤트를 영구 로그로 남기도록 설계되어 있다.

인사이트: 백테스트와 포워드 테스트가 같은 전략 인터페이스를 공유하려는 방향은 좋다. 하지만 실제 체결 모델이 백테스트 runner와 완전히 동일한지는 별도 검증 포인트다.

## 5. AI Agent 시스템

### v1

`scripts/agent/run.py`는 Claude Agent SDK 기반으로 세 역할을 조율한다.

- Researcher: 전략 가설과 설계 생성
- Developer: 전략 코드와 테스트 구현
- Analyst: 백테스트 실행과 성능 분석

워크스페이스는 `{strategy_name}_dir/` 형태로 생기고, `algorithm_prompt.txt`, `memory.md`, `backtest_report.md`를 남긴다.

### v2

`docs/v2/README.md`와 `scripts/agent/v2/`는 v1의 약점을 보완하려는 재설계다.

핵심 분리는 다음 세 축이다.

- Parameter: 같은 표현 안의 숫자 튜닝
- Expression: 같은 thesis를 다른 표현 축으로 구현
- Thesis: 경제적 주장 자체

결정론적 모듈은 agent 판단을 보조하거나 제한한다.

- `thesis_gate.py`: 반복 실패 패턴을 보고 ACTIVE / EXHAUSTED / REFUTED / SCOPE_RESTRICTED / APPROVED 판정
- `classify_failure.py`: 실패 모드 분류
- `exit_check.py`: 예산/목표 달성 여부 판단
- `oos_clamp.py`: OOS 기간 오염 방지
- `within_run_digest.py`, `build_wiki.py`: 실행 내/실행 간 지식 축적

인사이트: v2의 설계 방향은 매우 중요하다. "에이전트가 마음대로 전략을 바꾸는 루프"에서 "script가 thesis/expression 전환을 통제하는 연구 시스템"으로 전환하고 있다. 이는 과적합과 무한 튜닝을 줄이는 데 효과적이다.

## 6. 검증 철학

프로젝트의 테스트/검증 철학은 `CLAUDE.md`와 `docs/IS_OS_VALIDATION_RULES.md`에 잘 드러난다.

- Client-first TDD
- Mock 최소화
- 실제 데이터 구조 기반 테스트
- IS/OOS 분리
- OS 결과를 다시 튜닝 피드백에 사용하지 않음
- 기본 성공 기준: Profit Factor, Max Drawdown, Total Return, Total Trades
- 자동 거절 기준: 너무 낮은 win rate, 너무 낮은 sharpe, 너무 적은 trade count

인사이트: 이 프로젝트에서 가장 중요한 품질 기준은 "테스트가 많다"가 아니라 "실험 루프가 OS를 오염시키지 않는가"다.

## 7. 현재 강점

1. 전략 인터페이스가 비교적 단순하다.
   `generate_order(state)` 중심이라 새 전략 추가가 쉽다.

2. 이벤트 기반 바를 일급 개념으로 다룬다.
   volume/tick/dollar bar가 내장되어 있어 인트라데이 전략 탐색 범위가 넓다.

3. 선물 거래 현실 요소가 들어가 있다.
   레버리지, 공매도, 청산, funding, maker/taker fee가 고려된다.

4. 포트폴리오 전략으로 확장 중이다.
   `panel`, `positions`, `PortfolioOrder`가 이미 들어가 있어 단일 BTC 전략을 넘어설 수 있다.

5. v2 agent harness의 방향이 좋다.
   thesis와 expression을 분리하고 실패 모드를 enum으로 제한하는 것은 연구 자동화의 핵심 안전장치다.

6. 테스트 자산이 크다.
   현재 `tests/` 아래 test 파일이 143개 수준이고, 전략별 테스트도 다수 존재한다.

## 8. 주요 리스크와 정리 필요 지점

### 1. 문서와 코드 상태가 어긋난다

`docs/v2/README.md`의 phase status는 여전히 pending/in progress 중심이지만, 실제 코드에는 `orchestrator.py`, `thesis_gate.py`, `exit_check.py`, `build_wiki.py`, wiring 테스트가 존재한다.

권장: v2 README를 현재 구현 상태 기준으로 업데이트해야 한다.

### 2. Git worktree가 매우 많이 변경되어 있다

`git status --short` 기준 수정/삭제/신규 파일이 많다. 특히 전략 파일, 테스트 파일, agent v2 파일, runner 파일이 대량으로 untracked 또는 modified 상태다.

권장: 기능 단위로 커밋을 쪼개지 않으면 이후 회귀 원인 추적이 어려워진다.

### 3. 전략 파일이 실험 산출물처럼 누적되어 있다

`src/intraday/strategies/multi/`와 `tests/strategies/`에 Turtle/ATR 계열 실험 산출물이 다수 존재한다.

권장: production-ready 전략과 archived/generated 전략을 분리해야 한다. 예: `src/intraday/strategies/experimental/` 또는 `archive/strategies/`.

### 4. 포트폴리오 체결 모델이 중복된다

단일 runner는 `PaperTrader`를 쓰지만, 포트폴리오 runner는 내부 `_MultiPosition`과 자체 capital/trade log를 가진다.

권장: 포트폴리오 체결 모델을 `PaperTrader` 계열로 통합하거나, 의도적으로 별도 모델이라면 차이를 문서화해야 한다.

### 5. MarketState 계약이 넓어지고 있다

주문서, 캔들, 포트폴리오 panel, positions가 한 dataclass에 공존한다.

권장: runner별 보장 필드를 문서화하고, 전략 템플릿에서 필요한 필드를 명시하게 하는 것이 좋다.

### 6. 데이터 디렉터리는 비어 있거나 로컬 의존적이다

현재 `data/` 아래에서 확인 가능한 실제 데이터 파일은 없었다. 많은 실행 스크립트는 로컬 데이터 경로에 의존한다.

권장: 최소 샘플 데이터 또는 데이터 다운로드/전처리 smoke test를 문서화해야 재현성이 올라간다.

### 7. README의 프로젝트 구조가 실제 구조보다 단순하다

README에는 `src/intraday/data`와 일부 전략 폴더 설명이 과거 구조처럼 보이는 부분이 있다. 실제로는 `strategies/tick`, `strategies/multi`, `strategies/orderbook`, `scripts/agent/v2`, `docs/v2`가 중요하다.

권장: 신규 기여자용 "현재 지도"를 README 또는 docs index에 연결한다.

## 9. 우선순위 제안

### P0: 상태 안정화

- 현재 변경 파일을 기능 단위로 분류한다.
- agent v2, 포트폴리오 runner, 전략 실험 산출물, 문서 업데이트를 별도 커밋 단위로 나눈다.
- 삭제된 `scripts/run_forward_test.py`, `scripts/run_tick_forward_test.py`가 의도된 삭제인지 확인한다.

### P1: 재현성 확보

- `uv run pytest tests/ -v` 전체 실행 기준을 세운다.
- 느린/네트워크/실데이터 의존 테스트는 marker로 분리한다.
- 최소 로컬 샘플 데이터 또는 fixture 기반 백테스트 smoke test를 유지한다.

### P2: v2 harness 문서 업데이트

- `docs/v2/README.md`의 phase status를 실제 구현과 맞춘다.
- v2 실행 예시를 최신 CLI 기준으로 검증한다.
- `failure_modes.yaml`, `expression_axes.yaml`, `targets.yaml`가 run lifecycle에서 어떻게 쓰이는지 한 페이지로 정리한다.

### P3: 전략 산출물 관리

- 검증 완료 전략, 실험 전략, 자동 생성 전략을 분리한다.
- 전략별 metadata를 붙인다. 예: thesis, expression axes, IS/OOS 성과, 마지막 검증일.
- `strategies_ontology.json`와 실제 파일 목록의 동기화 절차를 자동화한다.

### P4: 실행 모델 정리

- 단일/포트폴리오/포워드 runner의 공통 계약을 명확히 한다.
- 체결/수수료/슬리피지/funding 모델을 공통화하거나 차이를 명시한다.
- `MarketState` 필드 보장 매트릭스를 만든다.

## 10. 다음에 보면 좋은 파일

- `README.md`: 현재 사용자용 진입점
- `CLAUDE.md`: 개발/테스트 원칙
- `src/intraday/strategy.py`: 전략 계약
- `src/intraday/candle_builder.py`: bar 생성 핵심
- `src/intraday/paper_trader.py`: 체결/선물 시뮬레이션
- `src/intraday/backtest/tick_runner.py`: 단일 심볼 백테스트
- `src/intraday/backtest/multi_tick_runner.py`: 포트폴리오 백테스트
- `src/intraday/multi_forward_runner.py`: 실시간 포워드 테스트
- `scripts/agent/run.py`: v1 agent loop
- `scripts/agent/run_v2.py`: v2 CLI/wiring
- `scripts/agent/v2/orchestrator.py`: v2 순수 오케스트레이터
- `scripts/agent/v2/deterministic/thesis_gate.py`: thesis 판정 핵심
- `config/failure_modes.yaml`: 실패 모드 taxonomy
- `config/expression_axes.yaml`: expression 탐색 공간
- `config/targets.yaml`: 승인/거절 기준

## 11. 결론

이 프로젝트는 이미 "전략 백테스트 모음" 단계를 지나 "자동화된 quant research loop"로 가고 있다. 가장 큰 기회는 v2 harness를 중심으로 연구 산출물을 구조화하는 것이다. 가장 큰 위험은 실험 산출물과 핵심 프레임워크 코드가 같은 공간에 계속 누적되어, 어느 전략/코드가 검증된 상태인지 흐려지는 것이다.

단기적으로는 문서-코드 상태를 맞추고, 변경 파일을 정리하고, v2 실행 경로의 재현성을 확보하는 것이 가장 높은 레버리지 작업이다.
