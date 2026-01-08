# PRD: Intraday Quant Research Agent

## Overview

Claude Agent SDK 기반 퀀트 연구 자동화 시스템.
사용자 아이디어 입력 → 코드 구현 → 백테스팅 → 검증 → 자동 개선.

## Design Philosophy

| Source | 채택 | 이유 |
|--------|------|------|
| **Helix** | 4-에이전트 워크플로우 | 퀀트 연구에 필요한 전문 역할 |
| **Helix** | Longterm Memory | 반복 개선을 위한 상태 추적 |
| **Helix** | MCP 도구로 백테스트 래핑 | 안정적인 실행 |
| **My-Jogyo** | 단순한 에이전트 구조 | 3-4개로 제한 |
| **My-Jogyo** | 구조화된 출력 마커 | 결과 파싱 용이 |
| **infra_doctor** | 진단 도구 | 문제 발생시 자가 진단 |

### 기각된 패턴

| Pattern | 이유 |
|---------|------|
| Helix의 5개 에이전트 | 과도한 복잡성 (senior-developer 통합) |
| Helix의 긴 프롬프트 | 300줄 → 100줄 이내로 제한 |
| My-Jogyo의 Adversarial Verification | 퀀트에선 메트릭이 검증 역할 |
| 복잡한 시그널 파일 | 단순 상태 파일 1개로 통합 |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    User: "볼륨 기반 모멘텀 전략 만들어줘"          │
└────────────────────────────────┬────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────┐
│                     ORCHESTRATOR (Main Agent)               │
│  - 워크플로우 조율                                             │
│  - 반복 관리 (max 5 iterations)                              │
│  - Longterm Memory 관리                                     │
└────────────────────────────────┬────────────────────────────┘
                                 │
         ┌───────────────────────┼───────────────────────┐
         ▼                       ▼                       ▼
┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
│   RESEARCHER    │   │    DEVELOPER    │   │    ANALYST      │
│                 │   │                 │   │                 │
│ - 아이디어 분석   │   │ - 전략 코드 구현  │   │ - 백테스트 실행   │
│ - 가설 생성      │   │ - 템플릿 기반     │   │ - 성과 분석       │
│ - 데이터 EDA    │   │ - 테스트 작성     │   │ - 피드백 생성     │
└─────────────────┘   └─────────────────┘   └─────────────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │    Feedback Loop        │
                    │                         │
                    │  APPROVED → 종료        │
                    │  NEED_IMPROVEMENT →     │
                    │    Researcher/Developer │
                    └─────────────────────────┘
```

---

## Agents

### 1. Orchestrator (Main Agent)

**역할**: 전체 워크플로우 조율

**책임**:
- 사용자 요청 해석 및 Core Goal 정의
- 워크플로우 디렉토리 생성 (`strategies/{name}/`)
- Longterm Memory 초기화 및 관리
- 에이전트 호출 순서 조율
- 반복 관리 (max 5 iterations)
- 완료/실패 판단

**Tools**: `Task`, `Bash`, `Read`, `Write`

### 2. Researcher (Sub-agent)

**역할**: 아이디어 분석 및 가설 생성

**책임**:
- 사용자 아이디어를 구체화
- 기존 데이터 EDA (tick data 특성 분석)
- 알고리즘 설계 문서 작성 (`algorithm_prompt.txt`)
- 실현 가능성 검증

**Tools**: `Read`, `Write`, `Bash` (데이터 분석용)

**출력**:
- `strategies/{name}/algorithm_prompt.txt`
- `strategies/{name}/research_report.md`

### 3. Developer (Sub-agent)

**역할**: 전략 코드 구현

**책임**:
- 템플릿 기반 전략 구현 (`_template.py` 복사)
- `should_buy()`, `should_sell()` 구현
- 테스트 코드 작성
- 린트/타입 검사 통과

**Tools**: `Read`, `Write`, `Edit`, `Bash` (pytest)

**출력**:
- `src/intraday/strategies/tick/{name}.py`
- `tests/test_strategy_{name}.py`

### 4. Analyst (Sub-agent)

**역할**: 백테스트 실행 및 성과 분석

**책임**:
- **Progressive Testing**: Phase 1 (1일) → Phase 2 (1주) → Phase 3 (2주)로 단계적 검증
- run_backtest MCP 도구로 백테스트 실행 (bar_size ≥ 10.0 필수)
- 성과 메트릭 분석 (Profit Factor, Max Drawdown, Total Return, Win Rate)
- 품질 게이트 검증
- APPROVED/NEED_IMPROVEMENT 결정
- 피드백 생성 (개선점, 다음 방향)

**Tools**: `mcp__backtest__run_backtest`, `mcp__backtest__get_available_strategies`, `Read`, `Write`, `Task` (피드백용)

**출력**:
- `strategies/{name}/backtest_report.md`
- `strategies/{name}/memory.md` 업데이트
- `strategies/{name}/APPROVED.signal` (승인 시)

---

## Workflow

### Phase 1: Research (1 iteration)

```
Orchestrator → Researcher
    ├── 아이디어 분석
    ├── 데이터 EDA
    ├── 알고리즘 설계
    └── algorithm_prompt.txt 생성
```

### Phase 2: Development (1 iteration)

```
Orchestrator → Developer
    ├── 템플릿 복사
    ├── 전략 구현
    ├── 테스트 작성
    └── 테스트 통과 확인
```

### Phase 3: Analysis & Feedback Loop (max 3 iterations)

```
Orchestrator → Analyst
    ├── 백테스트 실행
    ├── 성과 분석
    ├── 품질 게이트 검증
    │
    ├── IF APPROVED:
    │   └── 종료
    │
    └── IF NEED_IMPROVEMENT:
        ├── 피드백 생성
        ├── memory.md 업데이트
        └── Orchestrator → Developer (or Researcher)
```

---

## Quality Gates

| Metric | APPROVED | NEED_IMPROVEMENT | REJECT |
|--------|----------|------------------|--------|
| Profit Factor | ≥ 1.3 | 1.0 ~ 1.3 | < 1.0 |
| Max Drawdown | ≥ -15% | -15% ~ -25% | < -25% |
| Total Return | ≥ 5% | 0% ~ 5% | < 0% |
| Total Trades | ≥ 30 | 15 ~ 30 | < 15 |
| Win Rate | ≥ 40% | 25% ~ 40% | < 25% (secondary) |
| Sharpe Ratio | ≥ 1.0 | 0 ~ 1.0 | < 0 (secondary) |

**자동 실패 조건** (REJECT → 즉시 Researcher 호출):
- Win Rate < 10%: "전략 로직 근본적 문제"
- Sharpe < -0.5: "손실 전략"
- Total Trades < 5: "신호 발생 안함"

## Progressive Testing Strategy

**CRITICAL: 백테스트는 반드시 단계적으로 실행**

| Phase | Period | Purpose | Pass Criteria |
|-------|--------|---------|---------------|
| 1 | 1 day | Logic verification | Trades > 0, no errors |
| 2 | 1 week | Consistency check | Primary metrics met |
| 3 | 2 weeks | Statistical validity | ALL metrics → APPROVED |

## Backtest Tool Validations

- `bar_size` ≥ 10.0 (VOLUME bars): 값이 작으면 수백만 개 bar 생성으로 수시간 소요
- 최대 기간 14일: Progressive testing 강제
- `output_dir` 파라미터: 리포트 자동 저장

---

## File Structure

```
intraday_trading/
├── scripts/
│   └── agent/
│       ├── run.py                # 메인 실행 (Orchestrator)
│       ├── agents/
│       │   ├── __init__.py
│       │   ├── researcher.py     # Researcher 정의
│       │   ├── developer.py      # Developer 정의
│       │   └── analyst.py        # Analyst 정의
│       ├── tools/
│       │   ├── __init__.py
│       │   └── backtest_tool.py  # MCP 도구
│       └── hooks/
│           ├── __init__.py
│           └── logging_hook.py   # 로깅 훅
│
├── strategies/                   # 전략별 워크스페이스
│   └── {strategy_name}/
│       ├── memory.md             # Longterm Memory
│       ├── algorithm_prompt.txt  # 알고리즘 설계
│       ├── research_report.md    # 연구 리포트
│       └── backtest_report.md    # 백테스트 리포트
│
└── logs/
    └── agent_runs.jsonl          # 에이전트 로그
```

---

## Longterm Memory Schema

`strategies/{name}/memory.md`:

```markdown
# {Strategy Name} - Memory

## CORE GOAL (IMMUTABLE)
| Field | Value |
|-------|-------|
| Goal | [사용자 원래 요청] |
| Strategy Type | [Momentum / Mean-Reversion / etc.] |
| Target Sharpe | [X.XX] |

## SUCCESS CRITERIA
| Metric | Target | Operator |
|--------|--------|----------|
| Sharpe Ratio | 0.5 | >= |
| Win Rate | 30% | >= |
| Max Drawdown | -20% | >= |

## ITERATION HISTORY

### Iteration 1 (YYYY-MM-DD HH:MM)

#### Research
- Hypothesis: [가설]
- EDA Findings: [발견]

#### Development
- Strategy File: [경로]
- Key Logic: [핵심 로직]

#### Analysis
| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Sharpe | X.XX | 0.5 | PASS/FAIL |
| Win Rate | XX% | 30% | PASS/FAIL |

#### Decision
| Field | Value |
|-------|-------|
| Status | APPROVED / NEED_IMPROVEMENT |
| Feedback | [개선 방향] |
| Next Action | [다음 행동] |

---
### Iteration 2 ...
```

---

## Implementation Plan

### Step 1: 기반 구조 (이미 완료)
- [x] `scripts/agent/tools/backtest_tool.py`
- [x] `scripts/agent/hooks/logging_hook.py`

### Step 2: 에이전트 정의
- [ ] `scripts/agent/agents/researcher.py`
- [ ] `scripts/agent/agents/developer.py`
- [ ] `scripts/agent/agents/analyst.py`

### Step 3: Orchestrator 구현
- [ ] `scripts/agent/run.py` 확장
- [ ] AgentDefinition 등록
- [ ] 피드백 루프 구현

### Step 4: 통합 테스트
- [ ] 단일 전략 개발 E2E 테스트
- [ ] 피드백 루프 테스트

---

## Usage

```bash
# 대화형 모드
uv run python scripts/agent/run.py

# 쿼리와 함께 실행
uv run python scripts/agent/run.py "볼륨 기반 모멘텀 전략 만들어줘"

# 기존 전략 개선
uv run python scripts/agent/run.py "VolumeImbalanceStrategy 승률 개선해줘"
```

---

## Comparison with Helix

| Feature | Helix | Intraday Agent |
|---------|-------|----------------|
| 에이전트 수 | 5 | 4 |
| 프롬프트 길이 | 300줄+ | 100줄 이내 |
| 백테스트 시간 | 10-30분 | 1-5분 |
| 피드백 루프 | ✅ | ✅ |
| MCP 도구 | ✅ | ✅ |
| Hook 로깅 | ✅ | ✅ |
| 복잡한 시그널 | ✅ | ❌ (단순화) |
| DB 연결 | ✅ | ❌ (파일 기반) |
