# PRD: Helix Market Maker PoC

## 실행 방법

```bash
cd ~/helix-mm
claude -p "$(cat docs/HELIX_MM_PRD.md)" \
  --allowedTools "Read,Edit,Write,Bash,Glob,Grep" \
  --dangerously-skip-permissions \
  2>&1 | tee build.log
```

---

## 0. Mission

SmartFish(https://github.com/ico1036/smart_fish-)를 포크하여, 소셜미디어 시뮬레이터를 **Limit Order Book(LOB) 기반 마켓메이킹 시뮬레이터**로 도메인 전환한다.

**최종 산출물**: 1000틱 시뮬레이션을 실행하면 Avellaneda-Stoikov MM Agent의 PnL, Inventory, Sharpe, MDD가 출력되는 동작하는 시스템.

---

## 1. 프로젝트 초기화

### 1.1 클론 및 리네임

```bash
cd ~
git clone https://github.com/ico1036/smart_fish-.git helix-mm
cd helix-mm
rm -rf frontend/           # 프론트엔드 불필요 (나중에 Streamlit)
rm -rf docs/superpowers/    # 기존 SmartFish 문서 불필요
```

### 1.2 디렉토리 구조 전환

SmartFish 구조를 유지하되 도메인만 교체한다:

```
helix-mm/
├── CLAUDE.md                           # 새로 작성
├── pyproject.toml                      # 수정 (이름, 의존성)
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── config.py                   # 유지 (설정)
│   │   ├── main.py                     # 유지 (FastAPI 엔트리)
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── market.py               # 신규: Order, Trade, LOBState
│   │   │   └── simulation.py           # 수정: SimState → MarketSimState
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── lob_engine.py           # 신규: sim_engine.py 대체
│   │   │   ├── market_agents.py        # 신규: NoiseTrader, Fundamentalist, InformedTrader
│   │   │   ├── mm_agent.py             # 신규: Avellaneda-Stoikov MM
│   │   │   ├── simulation_runner.py    # 수정: 시장 시뮬레이션 루프
│   │   │   ├── metrics.py              # 신규: PnL, Sharpe, MDD, Inventory
│   │   │   └── data_replayer.py        # 신규: CSV 틱 데이터 리플레이
│   │   ├── agents/                     # Helix 에이전트 (Phase 2용, 지금은 빈 모듈)
│   │   │   ├── __init__.py
│   │   │   └── orchestrator.py         # 유지: PipelineOrchestrator 구조
│   │   ├── api/                        # 유지 (나중에 대시보드 연결)
│   │   │   └── simulation.py           # 수정: 시장 시뮬레이션 API
│   │   └── utils/
│   │       ├── __init__.py
│   │       └── math_utils.py           # 신규: A-S 수식 순수 함수
│   ├── conftest.py
│   └── tests/
│       ├── __init__.py
│       ├── test_models/
│       │   └── test_market.py          # Order, Trade 모델 테스트
│       ├── test_services/
│       │   ├── test_lob_engine.py      # LOB 핵심 테스트
│       │   ├── test_market_agents.py   # 에이전트 테스트
│       │   ├── test_mm_agent.py        # A-S MM 테스트
│       │   ├── test_simulation_runner.py # 시뮬레이션 통합 테스트
│       │   └── test_metrics.py         # 메트릭 계산 테스트
│       └── test_utils/
│           └── test_math_utils.py      # A-S 수식 단위 테스트
└── data/                               # 샘플 틱 데이터
```

### 1.3 pyproject.toml 수정

```toml
[project]
name = "helix-mm"
version = "0.1.0"
description = "Helix: AI-driven autonomous market maker with ABM simulator"
requires-python = ">=3.11"
dependencies = [
    "numpy>=1.26.0",
    "pydantic>=2.0",
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "ruff>=0.8.0",
]
dashboard = [
    "streamlit>=1.30.0",
    "plotly>=5.18.0",
]

[tool.pytest.ini_options]
testpaths = ["backend/tests"]
pythonpath = ["backend"]

[tool.ruff]
target-version = "py311"
line-length = 120
src = ["backend"]
```

### 1.4 불필요한 파일 삭제

삭제 대상 (소셜미디어 도메인):
- `backend/app/services/sim_engine.py` → `lob_engine.py`로 대체
- `backend/app/services/profile_generator.py` → 불필요
- `backend/app/services/ontology_service.py` → 불필요
- `backend/app/services/graph_builder.py` → 불필요
- `backend/app/services/graph_service.py` → 불필요
- `backend/app/services/report_generator.py` → Phase 2
- `backend/app/services/chat_service.py` → Phase 2
- `backend/app/agents/ontology_agent.py` → 불필요
- `backend/app/agents/graph_agent.py` → 불필요
- `backend/app/agents/report_agent.py` → Phase 2
- `backend/app/agents/sim_agent.py` → `mm_agent.py`로 대체
- `backend/app/tools/file_tools.py` → 불필요
- `backend/app/tools/graph_tools.py` → 불필요
- `backend/app/tools/report_tools.py` → Phase 2
- `backend/app/tools/sim_tools.py` → 수정
- `backend/app/models/graph.py` → 불필요
- `backend/app/models/project.py` → 불필요
- `backend/app/models/report.py` → Phase 2
- `backend/app/api/graph.py` → 불필요
- `backend/app/api/project.py` → 불필요
- `backend/app/api/report.py` → Phase 2
- `backend/app/utils/file_parser.py` → 불필요
- `backend/app/utils/text_processor.py` → 불필요
- `backend/app/utils/llm_client.py` → Phase 2 (Helix 에이전트용)
- 관련 테스트 파일 모두 삭제

삭제 후 남은 기존 테스트 파일도 모두 삭제하고, 새 테스트만 작성한다.

---

## 2. 핵심 데이터 모델 (models/)

### 2.1 market.py — 주문/체결/LOB 상태

```python
"""Market data models for LOB simulation."""
from enum import Enum
from pydantic import BaseModel, Field
from datetime import datetime
import uuid


class Side(str, Enum):
    BID = "bid"
    ASK = "ask"


class OrderType(str, Enum):
    LIMIT = "limit"
    MARKET = "market"


class Order(BaseModel):
    order_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: float  # 시뮬레이션 틱 (float)
    side: Side
    price: float
    quantity: float
    order_type: OrderType = OrderType.LIMIT
    agent_id: str = ""  # 주문 제출 에이전트 식별자

    class Config:
        frozen = True  # 주문은 불변


class Trade(BaseModel):
    trade_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: float
    price: float
    quantity: float
    buyer_id: str
    seller_id: str
    aggressor_side: Side  # 공격적 주문의 방향 (taker)


class LOBSnapshot(BaseModel):
    """특정 시점의 LOB 상태."""
    timestamp: float
    best_bid: float | None = None
    best_ask: float | None = None
    mid_price: float | None = None
    spread: float | None = None
    bid_depth: list[tuple[float, float]] = []  # [(price, qty), ...]
    ask_depth: list[tuple[float, float]] = []
```

### 2.2 simulation.py — 시뮬레이션 상태

```python
"""Market simulation state models."""
from enum import Enum
from pydantic import BaseModel, Field
from datetime import datetime
import uuid


class SimStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentConfig(BaseModel):
    """시장 참여 에이전트 설정."""
    agent_id: str
    agent_type: str  # "noise", "fundamentalist", "informed", "mm"
    params: dict = {}  # 에이전트별 파라미터


class MarketSimState(BaseModel):
    simulation_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    status: SimStatus = SimStatus.CREATED
    agents: list[AgentConfig] = []
    current_tick: int = 0
    max_ticks: int = 1000
    initial_mid_price: float = 100.0
    tick_size: float = 0.01
    created_at: datetime = Field(default_factory=datetime.now)


class TickRecord(BaseModel):
    """매 틱의 기록."""
    tick: int
    mid_price: float
    spread: float
    mm_inventory: float
    mm_pnl: float
    mm_bid: float | None = None
    mm_ask: float | None = None
    num_trades: int = 0
```

---

## 3. LOB Engine (services/lob_engine.py)

SmartFish의 `sim_engine.py`를 완전히 대체한다.

### 3.1 요구사항

- **FIFO 가격-시간 우선순위**: 같은 가격이면 먼저 들어온 주문이 먼저 체결
- **자료구조**: `collections.defaultdict` + `collections.deque` 사용. 가격별로 deque 관리.
  - `bids: dict[float, deque[Order]]` — 높은 가격 우선
  - `asks: dict[float, deque[Order]]` — 낮은 가격 우선
- **시장가 주문**: 반대편 최우선 호가에 즉시 매칭
- **부분 체결 지원**: 수량이 남으면 잔량은 오더북에 존치

### 3.2 인터페이스

```python
class LOBEngine:
    def __init__(self, tick_size: float = 0.01):
        """초기화. tick_size는 최소 호가 단위."""

    def add_order(self, order: Order) -> list[Trade]:
        """주문 추가. 시장가면 즉시 매칭 시도. 체결된 Trade 리스트 반환."""

    def cancel_order(self, order_id: str) -> bool:
        """주문 취소. 성공 여부 반환."""

    def get_best_bid(self) -> float | None:
        """최우선 매수 호가."""

    def get_best_ask(self) -> float | None:
        """최우선 매도 호가."""

    def get_mid_price(self) -> float | None:
        """(best_bid + best_ask) / 2. 한쪽이 없으면 None."""

    def get_spread(self) -> float | None:
        """best_ask - best_bid. 한쪽이 없으면 None."""

    def get_depth(self, levels: int = 5) -> LOBSnapshot:
        """상위 N 레벨의 호가 깊이 스냅샷."""

    def get_order_count(self) -> int:
        """현재 오더북에 남아있는 총 주문 수."""

    def clear(self):
        """오더북 초기화."""
```

### 3.3 매칭 로직

```
add_order(bid) 시:
  1. asks에서 bid.price >= ask.price인 것 찾기 (최저 ask부터)
  2. FIFO로 체결, Trade 생성
  3. 잔량 있으면 bids에 추가

add_order(ask) 시:
  1. bids에서 ask.price <= bid.price인 것 찾기 (최고 bid부터)
  2. FIFO로 체결, Trade 생성
  3. 잔량 있으면 asks에 추가

시장가 주문:
  - bid market order: price = float('inf') 로 처리 (어떤 ask든 매칭)
  - ask market order: price = 0 으로 처리 (어떤 bid든 매칭)
  - 잔량은 오더북에 추가하지 않음 (IOC 방식)
```

### 3.4 필수 테스트 (test_lob_engine.py)

```python
def test_empty_lob_returns_none_for_prices():
    """빈 오더북은 best_bid, best_ask, mid_price 모두 None."""

def test_add_limit_bid_appears_in_book():
    """지정가 매수 주문이 오더북에 등록된다."""

def test_add_limit_ask_appears_in_book():
    """지정가 매도 주문이 오더북에 등록된다."""

def test_crossing_orders_produce_trade():
    """매수가 >= 매도가이면 체결이 발생한다."""

def test_trade_price_is_passive_order_price():
    """체결가는 먼저 들어온(passive) 주문의 가격이다."""

def test_fifo_priority_at_same_price():
    """같은 가격에 여러 주문이 있으면 먼저 들어온 주문이 먼저 체결된다."""

def test_partial_fill():
    """수량이 부족하면 부분 체결되고, 잔량은 오더북에 남는다."""

def test_market_order_fills_immediately():
    """시장가 주문은 반대편 최우선 호가에 즉시 체결된다."""

def test_market_order_no_residual():
    """시장가 주문의 미체결 잔량은 오더북에 남지 않는다."""

def test_cancel_order_removes_from_book():
    """주문 취소 후 오더북에서 사라진다."""

def test_cancel_nonexistent_returns_false():
    """없는 주문 취소 시 False 반환."""

def test_get_depth_returns_correct_levels():
    """get_depth가 정확한 호가 레벨을 반환한다."""

def test_spread_calculation():
    """스프레드 = best_ask - best_bid."""

def test_multiple_trades_from_large_order():
    """큰 주문이 여러 호가 레벨을 관통하며 다수의 Trade를 생성한다."""
```

---

## 4. 수학 유틸리티 (utils/math_utils.py)

### 4.1 Avellaneda-Stoikov 순수 함수

```python
"""Avellaneda-Stoikov market making model — pure functions."""
import numpy as np


def reservation_price(
    mid_price: float,
    inventory: float,
    gamma: float,
    sigma: float,
    T: float,
) -> float:
    """
    적정 가격 (Reservation Price).
    r = s - q * γ * σ² * T

    Args:
        mid_price: 현재 미드프라이스 (s)
        inventory: 현재 재고량 (q), 양수=롱, 음수=숏
        gamma: 위험 회피 계수 (γ), 클수록 보수적
        sigma: 변동성 (σ)
        T: 잔존 시간 (0~1)
    """


def optimal_spread(
    gamma: float,
    sigma: float,
    T: float,
    k: float,
) -> float:
    """
    최적 스프레드 (Optimal Spread).
    δ = γσ²T + (2/γ) * ln(1 + γ/k)

    Args:
        gamma: 위험 회피 계수
        sigma: 변동성
        T: 잔존 시간
        k: 오더북 유동성 파라미터 (주문 도달 강도)
    """


def compute_quotes(
    mid_price: float,
    inventory: float,
    gamma: float,
    sigma: float,
    T: float,
    k: float,
) -> tuple[float, float]:
    """
    최종 bid/ask 호가 계산.
    bid = r - δ/2
    ask = r + δ/2

    Returns:
        (bid_price, ask_price)
    """
```

### 4.2 필수 테스트 (test_math_utils.py)

```python
def test_reservation_price_zero_inventory():
    """재고 0이면 reservation price == mid_price."""

def test_reservation_price_long_inventory_lowers_price():
    """롱 재고(q>0)이면 reservation price < mid_price. (팔고 싶으니까 가격을 낮춤)"""

def test_reservation_price_short_inventory_raises_price():
    """숏 재고(q<0)이면 reservation price > mid_price. (사고 싶으니까 가격을 올림)"""

def test_optimal_spread_positive():
    """스프레드는 항상 양수."""

def test_higher_gamma_wider_spread():
    """γ가 클수록 스프레드가 넓어진다. (위험 회피 ↑ → 보수적 호가)"""

def test_higher_volatility_wider_spread():
    """σ가 클수록 스프레드가 넓어진다."""

def test_compute_quotes_symmetric_at_zero_inventory():
    """재고 0이면 bid/ask가 mid_price 기준 대칭."""

def test_compute_quotes_bid_less_than_ask():
    """항상 bid < ask."""

def test_higher_k_narrower_spread():
    """k(유동성)가 클수록 스프레드가 좁아진다."""
```

---

## 5. Market Agents (services/market_agents.py)

SmartFish의 `SimulationRunner.run_round()`에서 LLM을 호출하던 패턴을 수식 기반으로 교체한다.

### 5.1 공통 인터페이스

```python
from abc import ABC, abstractmethod

class MarketAgent(ABC):
    """모든 시장 참여 에이전트의 베이스 클래스."""

    def __init__(self, agent_id: str, params: dict):
        self.agent_id = agent_id
        self.params = params

    @abstractmethod
    def generate_orders(self, tick: int, lob_snapshot: LOBSnapshot) -> list[Order]:
        """현재 LOB 상태를 보고 주문 리스트를 생성한다."""
```

### 5.2 NoiseTrader

```python
class NoiseTrader(MarketAgent):
    """
    무작위 주문 생성 에이전트.

    매 틱마다 Poisson(λ) 확률로 주문 발생.
    50% 확률로 시장가/지정가 결정.
    지정가는 mid_price ± U(0, max_spread) 범위.

    params:
        arrival_rate: float = 1.0    # 틱당 평균 주문 수 (λ)
        market_order_pct: float = 0.3  # 시장가 비율
        max_spread: float = 2.0      # 지정가 범위 (mid ±)
        quantity: float = 1.0        # 주문 수량
    """
```

### 5.3 Fundamentalist

```python
class Fundamentalist(MarketAgent):
    """
    기본 가치(fundamental value)로 회귀하는 에이전트.

    mid_price가 fundamental_value보다 높으면 매도, 낮으면 매수.
    괴리율이 threshold를 넘을 때만 주문 제출.

    params:
        fundamental_value: float = 100.0
        threshold: float = 0.5       # 괴리율 임계치
        aggression: float = 0.5      # 0=항상 지정가, 1=항상 시장가
        quantity: float = 2.0
        update_speed: float = 0.01   # fundamental_value의 랜덤워크 속도
    """
```

### 5.4 InformedTrader

```python
class InformedTrader(MarketAgent):
    """
    미래 가격 방향 정보를 일부 아는 에이전트 (역선택 리스크 테스트용).

    외부에서 future_prices 시퀀스를 받아, 현재 mid_price 대비
    미래가가 높으면 매수, 낮으면 매도.
    시장가 주문을 공격적으로 제출하여 MM에게 역선택 비용 부과.

    params:
        look_ahead: int = 10         # 몇 틱 뒤 가격을 아는가
        accuracy: float = 0.7        # 정보 정확도 (0.5=noise, 1.0=완전정보)
        arrival_rate: float = 0.3    # 틱당 참여 확률
        quantity: float = 3.0
    """
```

### 5.5 필수 테스트 (test_market_agents.py)

```python
def test_noise_trader_generates_orders():
    """NoiseTrader가 주문을 생성한다 (seed 고정으로 결정론적 테스트)."""

def test_noise_trader_respects_arrival_rate():
    """arrival_rate=0이면 주문 없음, 높으면 많은 주문."""

def test_fundamentalist_buys_when_price_below_value():
    """mid_price < fundamental_value이면 BID 주문."""

def test_fundamentalist_sells_when_price_above_value():
    """mid_price > fundamental_value이면 ASK 주문."""

def test_fundamentalist_no_order_within_threshold():
    """괴리율 < threshold이면 주문 없음."""

def test_informed_trader_buys_before_price_rise():
    """미래가 상승 예상 시 매수."""

def test_informed_trader_uses_market_orders():
    """InformedTrader는 시장가 주문을 사용한다."""

def test_all_agents_return_valid_orders():
    """모든 에이전트가 Order 타입의 유효한 주문을 반환한다."""
```

---

## 6. MM Agent (services/mm_agent.py)

### 6.1 HelixMMAgent

```python
class HelixMMAgent(MarketAgent):
    """
    Avellaneda-Stoikov 기반 마켓메이커.

    매 틱마다:
    1. 현재 재고 확인
    2. A-S 수식으로 bid/ask 호가 계산
    3. 이전 호가 취소 후 새 호가 제출
    4. 체결 시 재고/PnL 업데이트

    params:
        gamma: float = 0.1           # 위험 회피 계수
        k: float = 1.5               # 오더북 유동성 파라미터
        sigma: float = 0.3           # 변동성 추정치
        T: float = 1.0               # 잔존 시간 (시뮬레이션 동안 1.0 → 0.0)
        quantity: float = 1.0        # 호가 수량
        max_inventory: int = 10      # 재고 한도 (절댓값)

    state:
        inventory: float = 0.0       # 현재 재고
        cash: float = 0.0            # 누적 현금
        active_bid_id: str | None    # 현재 활성 매수 호가 ID
        active_ask_id: str | None    # 현재 활성 매도 호가 ID
    """
```

### 6.2 재고 관리 로직

```
재고 > max_inventory:  ask만 제출 (매도하여 재고 축소)
재고 < -max_inventory: bid만 제출 (매수하여 재고 축소)
|재고| <= max_inventory: 양방향 호가 제출
```

### 6.3 PnL 계산

```
Mark-to-Market PnL = cash + inventory * mid_price
Realized PnL = cash (inventory=0일 때)
```

### 6.4 필수 테스트 (test_mm_agent.py)

```python
def test_mm_generates_two_sided_quotes():
    """재고 0일 때 bid와 ask 모두 생성."""

def test_mm_quotes_straddle_mid_price():
    """bid < mid_price < ask."""

def test_mm_skews_quotes_with_inventory():
    """롱 재고이면 ask가 mid에 더 가까움 (팔고 싶음)."""

def test_mm_only_asks_at_max_long_inventory():
    """재고 = max_inventory이면 ask만 제출."""

def test_mm_only_bids_at_max_short_inventory():
    """재고 = -max_inventory이면 bid만 제출."""

def test_mm_cancels_previous_quotes():
    """새 호가 제출 전 이전 호가를 취소한다."""

def test_mm_pnl_tracks_correctly():
    """체결 후 cash와 inventory가 정확히 업데이트된다."""

def test_mm_remaining_time_decreases():
    """틱이 진행될수록 T가 감소한다."""
```

---

## 7. Simulation Runner (services/simulation_runner.py)

SmartFish의 `SimulationRunner.run_round()`를 시장 시뮬레이션으로 전환한다.

### 7.1 인터페이스

```python
class MarketSimulationRunner:
    """
    ABM 시장 시뮬레이션 실행기.

    SmartFish의 SimulationRunner 패턴 유지:
    - run_round() → run_tick()
    - LLM 호출 → 수식 기반 주문 생성
    """

    def __init__(
        self,
        lob: LOBEngine,
        agents: list[MarketAgent],
        mm_agent: HelixMMAgent,
        max_ticks: int = 1000,
        initial_mid_price: float = 100.0,
    ):
        """초기화."""

    def run_tick(self, tick: int) -> TickRecord:
        """
        1틱 실행:
        1. LOB 스냅샷 생성
        2. 각 에이전트 → generate_orders() 호출
        3. MM 에이전트 → 이전 호가 취소 + 새 호가 제출
        4. 모든 주문을 LOB에 제출 (체결 처리)
        5. MM 체결 확인 → inventory/cash 업데이트
        6. TickRecord 반환
        """

    def run(self) -> list[TickRecord]:
        """
        전체 시뮬레이션 실행.
        max_ticks만큼 run_tick() 반복.
        list[TickRecord] 반환.
        """

    def get_results_summary(self) -> dict:
        """
        시뮬레이션 결과 요약:
        - total_ticks, total_trades
        - mm_final_pnl, mm_final_inventory
        - sharpe_ratio, max_drawdown
        - avg_spread, inventory_std
        """
```

### 7.2 시뮬레이션 초기화

```
1. LOB에 initial_mid_price 기준으로 양쪽 5 레벨 시드 주문 배치
   - bids: [99.95, 99.90, ..., 99.75] 각 수량 10
   - asks: [100.05, 100.10, ..., 100.25] 각 수량 10
2. 에이전트 생성: NoiseTrader 3개, Fundamentalist 1개, InformedTrader 1개
3. MM Agent 1개
```

### 7.3 필수 테스트 (test_simulation_runner.py)

```python
def test_simulation_runs_to_completion():
    """1000틱 시뮬레이션이 에러 없이 완료된다."""

def test_simulation_produces_tick_records():
    """run()이 max_ticks 개의 TickRecord를 반환한다."""

def test_simulation_has_trades():
    """시뮬레이션 중 체결이 1건 이상 발생한다."""

def test_mm_pnl_is_finite():
    """MM의 최종 PnL이 유한한 값이다 (NaN/Inf 아님)."""

def test_mm_inventory_bounded():
    """MM의 재고가 max_inventory를 크게 초과하지 않는다."""

def test_mid_price_series_is_continuous():
    """mid_price 시계열에 급격한 단절이 없다 (>10% 점프 없음)."""

def test_results_summary_contains_required_fields():
    """get_results_summary()가 필수 필드를 모두 포함한다."""

def test_short_simulation_runs():
    """max_ticks=10인 짧은 시뮬레이션도 정상 동작한다."""
```

---

## 8. Metrics (services/metrics.py)

### 8.1 인터페이스

```python
def compute_sharpe_ratio(pnl_series: list[float], risk_free_rate: float = 0.0) -> float:
    """PnL 시계열의 Sharpe Ratio. returns의 mean/std."""

def compute_max_drawdown(pnl_series: list[float]) -> float:
    """최대 낙폭 (MDD). 0~1 사이 비율. PnL이 전부 음수여도 동작."""

def compute_inventory_stats(inventory_series: list[float]) -> dict:
    """재고 통계: mean, std, max_abs, zero_crossings."""

def compute_spread_stats(spread_series: list[float]) -> dict:
    """스프레드 통계: mean, std, min, max."""

def generate_report(tick_records: list[TickRecord]) -> dict:
    """TickRecord 리스트에서 전체 성과 보고서 생성."""
```

### 8.2 필수 테스트 (test_metrics.py)

```python
def test_sharpe_ratio_positive_returns():
    """양수 수익 시 Sharpe > 0."""

def test_sharpe_ratio_zero_std():
    """수익률 변동이 0이면 Sharpe = 0 (0 나누기 방지)."""

def test_max_drawdown_no_drawdown():
    """단조 증가 PnL이면 MDD = 0."""

def test_max_drawdown_known_case():
    """알려진 PnL 시퀀스 [100, 80, 90, 70] → MDD = 0.3."""

def test_inventory_stats_symmetric():
    """[-5, 5, -5, 5] → mean ≈ 0, max_abs = 5."""

def test_generate_report_from_tick_records():
    """TickRecord 리스트로 보고서 생성 성공."""
```

---

## 9. 실행 엔트리포인트

### 9.1 scripts/run_simulation.py

```python
"""
Helix MM 시뮬레이션 실행 스크립트.

Usage:
    uv run python scripts/run_simulation.py
    uv run python scripts/run_simulation.py --ticks 5000 --gamma 0.2
"""
import argparse
from backend.app.services.lob_engine import LOBEngine
from backend.app.services.market_agents import NoiseTrader, Fundamentalist, InformedTrader
from backend.app.services.mm_agent import HelixMMAgent
from backend.app.services.simulation_runner import MarketSimulationRunner
from backend.app.services.metrics import generate_report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticks", type=int, default=1000)
    parser.add_argument("--gamma", type=float, default=0.1)
    parser.add_argument("--k", type=float, default=1.5)
    parser.add_argument("--sigma", type=float, default=0.3)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    # Setup
    lob = LOBEngine(tick_size=0.01)

    agents = [
        NoiseTrader("noise_1", {"arrival_rate": 1.0, "seed": args.seed}),
        NoiseTrader("noise_2", {"arrival_rate": 0.8, "seed": args.seed + 1}),
        NoiseTrader("noise_3", {"arrival_rate": 0.6, "seed": args.seed + 2}),
        Fundamentalist("fund_1", {"fundamental_value": 100.0, "threshold": 0.5}),
        InformedTrader("informed_1", {"accuracy": 0.7, "arrival_rate": 0.3}),
    ]

    mm = HelixMMAgent("mm_helix", {
        "gamma": args.gamma,
        "k": args.k,
        "sigma": args.sigma,
        "quantity": 1.0,
        "max_inventory": 10,
    })

    runner = MarketSimulationRunner(
        lob=lob, agents=agents, mm_agent=mm,
        max_ticks=args.ticks, initial_mid_price=100.0,
    )

    # Run
    records = runner.run()
    report = generate_report(records)

    # Print
    print("=" * 60)
    print("HELIX MM SIMULATION REPORT")
    print("=" * 60)
    for key, value in report.items():
        print(f"  {key}: {value}")
    print("=" * 60)


if __name__ == "__main__":
    main()
```

---

## 10. 작업 순서 및 검증

반드시 아래 순서로 진행한다. 각 단계 완료 시 `uv run pytest -v` 전체 통과를 확인한다.

### Phase 1: 프로젝트 셋업 (Step 1)
1. 레포 클론, 불필요 파일 삭제
2. pyproject.toml 수정
3. CLAUDE.md 작성
4. `uv sync` 및 `uv run pytest` 동작 확인

### Phase 2: 데이터 모델 (Step 2)
1. `models/market.py` 작성
2. `models/simulation.py` 작성
3. 모델 테스트 작성 및 통과

### Phase 3: 수학 유틸리티 (Step 3)
1. `utils/math_utils.py` 작성
2. `test_math_utils.py` 작성 및 통과

### Phase 4: LOB Engine (Step 4)
1. `services/lob_engine.py` 작성
2. `test_lob_engine.py` 작성 및 전체 통과

### Phase 5: Market Agents (Step 5)
1. `services/market_agents.py` 작성
2. `test_market_agents.py` 작성 및 통과

### Phase 6: MM Agent (Step 6)
1. `services/mm_agent.py` 작성
2. `test_mm_agent.py` 작성 및 통과

### Phase 7: Simulation Runner (Step 7)
1. `services/simulation_runner.py` 작성
2. `services/metrics.py` 작성
3. `test_simulation_runner.py` 및 `test_metrics.py` 통과

### Phase 8: 통합 검증 (Step 8)
1. `scripts/run_simulation.py` 작성
2. 1000틱 시뮬레이션 실행 → 결과 출력
3. 전체 테스트 스위트 통과 확인
4. 커밋

---

## 11. 품질 기준

### 테스트
- 모든 테스트 통과 (`uv run pytest -v`)
- 테스트 수: 최소 40개 이상
- 커버리지: 핵심 로직 100%

### 코드
- Type hint: 모든 함수 시그니처
- Docstring: 모든 public 클래스/함수
- Ruff: 경고 0개 (`uv run ruff check backend/`)
- 외부 의존성: numpy, pydantic만 (LLM 호출 없음)

### 시뮬레이션 결과
- 1000틱 시뮬레이션이 5초 이내 완료
- MM Agent의 PnL이 유한한 값
- 체결 건수 > 0
- 재고가 max_inventory ± 2 이내 유지

---

## 12. 하지 말 것

- LLM 호출하지 않는다 (Phase 2에서 Helix 루프 연동 시 추가)
- Streamlit 대시보드 만들지 않는다 (Phase 3)
- 실제 거래소 API 연동하지 않는다
- pandas 사용하지 않는다 (numpy만)
- 과도한 최적화하지 않는다 (Cython, C extension 등)
- frontend/ 관련 작업하지 않는다
- SmartFish의 소셜미디어 관련 코드를 남기지 않는다
