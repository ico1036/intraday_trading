# CLAUDE.md - 코드 생성 지침

## 개발 방식: Client-First TDD

테스트는 **클라이언트 관점**에서 작성한다.
"이런 입력을 주면, 이런 결과가 나와야 한다"가 기본이다.

```python
# Good: 클라이언트가 기대하는 동작
def test_regime_strategy_buys_on_uptrend():
    strategy = RegimeStrategy(quantity=0.01)
    state = make_uptrend_state()  # 실제 데이터 기반

    order = strategy.generate_order(state)

    assert order is not None
    assert order.side == Side.BUY

# Bad: 구현 세부사항 테스트
def test_analyzer_internal_buffer_size():
    analyzer = RegimeAnalyzer()
    assert len(analyzer._prices) == 0  # 내부 구현에 의존
```

---

## TDD 사이클

```
1. Red   → 실패하는 테스트 작성 (클라이언트 관점)
2. Green → 테스트 통과하는 최소 코드 작성
3. Tidy  → 구조 개선 (동작 변경 없이)
```

### 실행 명령

```bash
uv run pytest tests/ -v           # 전체 테스트
uv run pytest tests/test_xxx.py   # 단일 파일
```

---

## 테스트 원칙

### 1. Mock 최소화, 실제 데이터 사용

```python
# Good: 실제 데이터 구조 사용
def test_backtest_with_real_data():
    loader = TickDataLoader(Path("./data/ticks"))
    strategy = OBIStrategy(quantity=0.01)
    runner = TickBacktestRunner(strategy=strategy, data_loader=loader)

    report = runner.run()

    assert report.total_trades >= 0

# Bad: 과도한 Mock
def test_with_mocks():
    mock_loader = Mock()
    mock_loader.iter_trades.return_value = iter([])
    # ... Mock 지옥
```

### 2. 테스트 이름은 기대 동작을 설명

```python
# Good
def test_obi_strategy_returns_buy_order_when_imbalance_exceeds_threshold():
def test_paper_trader_rejects_order_when_insufficient_balance():

# Bad
def test_strategy():
def test_order():
```

### 3. Given-When-Then 구조

```python
def test_limit_order_fills_when_price_reaches_target():
    # Given: 초기 상태
    trader = PaperTrader(initial_capital=10000)
    order = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.LIMIT, limit_price=100)
    trader.submit_order(order)

    # When: 동작 실행
    trade = trader.on_price_update(price=99, best_bid=99, best_ask=100)

    # Then: 결과 검증
    assert trade is not None
    assert trade.price == 100

```

---

## 커밋 규칙

### 구조 변경과 동작 변경 분리

```bash
# 구조 변경 (리팩토링)
git commit -m "refactor: extract RegimeAnalyzer from RegimeStrategy"

# 동작 변경 (기능 추가/수정)
git commit -m "feat: add OHLCV fields to MarketState for tick strategies"

# 버그 수정
git commit -m "fix: MarketState missing candle data in TickRunner"
```

### 커밋 조건

- 모든 테스트 통과
- Linter 경고 없음
- 하나의 논리적 변경 단위

---

## 프로젝트 구조

```
src/intraday/
├── strategies/
│   ├── base.py              # StrategyBase (수정 금지)
│   ├── orderbook/           # Orderbook 기반 전략
│   │   ├── _template.py     # 템플릿
│   │   └── obi.py
│   └── tick/                # Tick 기반 전략
│       ├── _template.py     # 템플릿
│       ├── volume_imbalance.py
│       └── regime.py
├── backtest/
│   ├── orderbook_runner.py  # OrderbookBacktestRunner
│   └── tick_runner.py       # TickBacktestRunner (선물 지원)
├── paper_trader.py          # PaperTrader (현물/선물 통합)
├── funding.py               # Funding Rate 정산
├── data/
│   ├── downloader.py        # Tick 다운로더 (현물/선물)
│   └── funding_downloader.py # Funding Rate 다운로더
└── ...

tests/
├── test_strategy_*.py       # 전략 테스트
├── test_backtest_*.py       # 백테스트 테스트
├── test_futures_*.py        # 선물 거래 테스트
├── test_funding_*.py        # Funding Rate 테스트
└── ...
```

---

## 새 기능 개발 워크플로우

### 예: MarketState에 OHLCV 추가

```bash
# 1. 실패하는 테스트 작성
# tests/test_market_state.py
def test_tick_runner_provides_ohlcv_to_strategy():
    # 전략이 OHLCV를 받을 수 있어야 함
    ...
    assert state.open is not None
    assert state.high is not None

# 2. 테스트 실행 → 실패 확인
uv run pytest tests/test_market_state.py -v

# 3. 최소 코드로 통과시키기
# strategy.py에 필드 추가, tick_runner.py에서 전달

# 4. 테스트 통과 확인
uv run pytest tests/ -v

# 5. 구조 개선 (필요시)
# 6. 커밋
```

---

## 전략 개발 가이드

### Tick 기반 전략

1. `strategies/tick/_template.py` 복사
2. `should_buy()`, `should_sell()` 구현
3. `TickBacktestRunner`로 테스트

### Orderbook 기반 전략

1. `strategies/orderbook/_template.py` 복사
2. `should_buy()`, `should_sell()` 구현
3. `OrderbookBacktestRunner`로 테스트

---

## 금지 사항

- Mock 남용 (외부 API 호출만 Mock)
- 내부 구현 테스트 (`_private` 메서드 직접 테스트)
- 테스트 없이 코드 작성
- 구조 변경과 동작 변경 동시 커밋
- 테스트 실패 상태에서 커밋

---

## 선물 거래 (USDT-M Futures)

### 핵심 공식 (Binance USDT-M Isolated Margin)

```python
# 청산가 계산
롱: LP = EP × (1/L - 1) / (MMR - 1)
숏: LP = EP × (1/L + 1) / (MMR + 1)

# 마진 계산
마진 = Notional / Leverage

# Funding 정산
지불액 = Position × MarkPrice × FundingRate
롱 + 양수펀딩 = 지불, 숏 + 양수펀딩 = 수취
```

### 선물 모드 활성화

```python
# leverage > 1이면 자동으로 선물 모드
trader = PaperTrader(initial_capital=10000, leverage=10)  # 선물
trader = PaperTrader(initial_capital=10000, leverage=1)   # 현물

runner = TickBacktestRunner(
    strategy=strategy,
    data_loader=loader,
    leverage=10,                    # 선물 모드
    funding_loader=funding_loader,  # Funding Rate 적용
)
```

### 선물 테스트 검증 항목

1. **레버리지**: 마진 = Notional / Leverage
2. **청산가**: Binance 공식과 일치 (test_futures_math_verification.py)
3. **공매도**: BTC 없이 SELL 가능 (선물만)
4. **Funding**: 8시간마다 정산, 캔들 타입과 독립

---

## 라이브러리 문서 조회

**외부 라이브러리 관련 작업 시 반드시 Context7 MCP를 활용한다.**

```
# 라이브러리 ID 조회
mcp_context7_resolve-library-id(libraryName="pandas", query="...")

# 문서/예제 조회
mcp_context7_query-docs(libraryId="/pandas/pandas", query="...")
```

### 필수 사용 상황

- 새 라이브러리 도입 시
- 라이브러리 API 사용법 확인 시
- 버전별 차이 확인 시
- 에러 해결 시

### 주요 라이브러리 ID

| 라이브러리 | Context7 ID |
|------------|-------------|
| pandas | `/pandas/pandas` |
| numpy | `/numpy/numpy` |
| pytest | `/pytest-dev/pytest` |
| plotly | `/plotly/plotly.py` |
| websockets | `/python-websockets/websockets` |
