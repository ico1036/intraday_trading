# PRD: Strategy Knowledge Base (Ontology Map)

> **Version**: 1.0
> **Date**: 2026-01-09
> **Author**: Agent Workflow Analysis
> **Status**: Draft

---

## Executive Summary

에이전트 워크플로우에서 **전략 간 지식 공유가 전혀 이루어지지 않음**. 26개 전략의 메모리와 48개 전략 코드가 각 폴더에 고립되어 있어, 새 전략 설계 시 기존 교훈을 참조하지 못하고 같은 실수를 반복함.

**해결책**: JSON 기반 온톨로지 맵 + Claude Skill로 lazy loading 접근

---

## 1. Problem Statement

### 1.1 Current State (실태 분석)

**에이전트별 참조 범위:**

| Agent | 읽는 파일 | 다른 전략 참조 |
|-------|----------|---------------|
| Researcher | `{name}_dir/memory.md` | ❌ 없음 |
| Developer | `{name}_dir/algorithm_prompt.txt`, `_template.py` | ❌ 없음 |
| Analyst | `{name}_dir/memory.md`, `algorithm_prompt.txt` | ❌ 없음 |

**결론**: 모든 에이전트가 **자기 전략의 루프 내 데이터만** 참조. 다른 전략의 성공/실패 경험을 전혀 활용하지 못함.

### 1.2 Concrete Problems

#### Problem 1: 반복되는 실수
```
VPIN Contrarian 전략의 교훈:
"Risk-Reward Inverted - Win Rate 58.8%이나 Avg Win < Avg Loss"
"원인: Take profit이 도달하기 전에 exit"

→ 이후 Dual VPIN RSI, VPIN RSI Mean Reversion 등에서 동일 실수 반복
→ 각 전략이 3-4 iterations 걸려 같은 교훈 재학습
```

#### Problem 2: 유사 전략 중복 설계
```
VPIN 기반 전략 5개 존재:
- vpin_contrarian
- dual_vpin
- dual_vpin_cdf
- dual_vpin_rsi
- vpin_breakout_filter

→ Researcher가 새 VPIN 전략 설계 시 기존 5개 참조 없음
→ 이미 실패한 접근법 재시도
```

#### Problem 3: 지표별 지식 분산
```
OFI(Order Flow Imbalance) 사용 전략:
- ofi_momentum
- ofi_vpin_explosion
- ofi_trend_momentum

→ OFI 관련 best practices가 각 memory.md에 분산
→ 종합적인 OFI 활용 가이드 없음
```

### 1.3 Impact

| Metric | Current | Estimated Waste |
|--------|---------|-----------------|
| Avg Iterations to APPROVED | 4-5 | 2-3 iterations 낭비 |
| 반복 실수 발생률 | ~30% | 시간/비용 낭비 |
| 컨텍스트 사용량 | 높음 | 불필요한 탐색 |

---

## 2. Proposed Solution

### 2.1 Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                  strategies_ontology.json            │
│  ┌─────────────┬─────────────┬─────────────────┐    │
│  │  strategies │ relationships│ lessons_learned │    │
│  │  (metadata) │ (graph)     │ (centralized)   │    │
│  └─────────────┴─────────────┴─────────────────┘    │
│  ┌─────────────────┬───────────────────────────┐    │
│  │indicator_taxonomy│    common_mistakes       │    │
│  │ (grouping)       │    (patterns)            │    │
│  └─────────────────┴───────────────────────────┘    │
└─────────────────────────────────────────────────────┘
                         │
                         ▼
              ┌─────────────────────┐
              │  Claude Skill       │
              │  /strategy-kb       │
              │  (lazy loading)     │
              └─────────────────────┘
                         │
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
    Researcher       Developer        Analyst
    (lessons)      (similar code)   (benchmarks)
```

### 2.2 Why JSON (Not Graph DB)

| Option | Pros | Cons | Decision |
|--------|------|------|----------|
| **JSON + Skill** | 심플, 버전관리 용이, Opus 시맨틱 매칭 | 복잡한 쿼리 제한 | ✅ 선택 |
| Graph DB (Neo4j) | 강력한 관계 쿼리 | 운영 부담, 오버킬 | ❌ |
| Vector DB | 시맨틱 검색 우수 | 셋업 복잡, 비용 | ❌ |
| 현재 방식 (분산) | 변경 없음 | 비효율 지속 | ❌ |

**핵심 논거**:
- 전략 수 ~100개 수준에서 JSON으로 충분
- Opus 4.5가 자연어 → 필터링 변환 가능
- Git 버전 관리 가능

---

## 3. JSON Schema Design

### 3.1 Complete Schema

```json
{
  "version": "1.0",
  "last_updated": "2026-01-09T10:30:00Z",

  "strategies": {
    "bb_squeeze": {
      "name": "BBSqueezeStrategy",
      "display_name": "BB Squeeze Frontrun",
      "category": "volatility_breakout",
      "subcategory": "squeeze_detection",
      "indicators": ["bollinger_bands", "keltner_channel", "squeeze"],
      "bar_type": "TIME",
      "bar_size": 240,
      "asset_type": "FUTURES",
      "order_type": "LIMIT",
      "hypothesis": "변동성 폭발 직전의 Squeeze 감지, 5분봉 트레이더보다 1분 선점",
      "best_metrics": {
        "profit_factor": 3.57,
        "win_rate": 56.1,
        "sharpe": 0.46,
        "total_return": 18.46,
        "max_drawdown": -0.03
      },
      "status": "approved",
      "iterations": 9,
      "created_date": "2026-01-09",
      "last_backtest": "2026-01-09",
      "memory_path": "bb_squeeze_dir/memory.md",
      "code_path": "src/intraday/strategies/tick/bb_squeeze.py",
      "tags": ["volatility", "breakout", "frontrun", "bollinger"]
    }
  },

  "relationships": [
    {
      "source": "vpin_contrarian",
      "target": "dual_vpin_rsi",
      "type": "evolved_from",
      "description": "RSI 필터 추가하여 진화"
    },
    {
      "source": "bb_squeeze",
      "target": "breakout_frontrun",
      "type": "similar_to",
      "similarity_score": 0.85,
      "shared_concepts": ["breakout", "frontrun", "volatility"]
    },
    {
      "source": "ofi_momentum",
      "target": "ofi_vpin_explosion",
      "type": "shares_indicator",
      "shared_indicators": ["ofi", "vpin"]
    }
  ],

  "indicator_taxonomy": {
    "vpin": {
      "description": "Volume-synchronized Probability of Informed Trading",
      "strategies": ["vpin_contrarian", "dual_vpin", "dual_vpin_cdf", "dual_vpin_rsi", "vpin_breakout_filter", "ofi_vpin_explosion"],
      "best_practices": [
        "VOLUME bar와 함께 사용 권장",
        "bucket_size는 거래량의 1/50 수준",
        "CDF 변환으로 정규화 필요"
      ]
    },
    "ofi": {
      "description": "Order Flow Imbalance",
      "strategies": ["ofi_momentum", "ofi_vpin_explosion", "ofi_trend_momentum"],
      "best_practices": [
        "누적값보다 변화율이 더 유용",
        "고빈도 노이즈 필터링 필요"
      ]
    },
    "bollinger_bands": {
      "description": "Bollinger Bands with Squeeze Detection",
      "strategies": ["bb_squeeze"],
      "best_practices": [
        "Keltner Channel과 조합하여 Squeeze 판단",
        "bandwidth_percentile로 상대적 Squeeze 감지"
      ]
    },
    "rsi": {
      "description": "Relative Strength Index",
      "strategies": ["vpin_contrarian", "dual_vpin_rsi", "vpin_rsi_mean_reversion"],
      "best_practices": [
        "단독 사용보다 필터로 사용",
        "극단값 (20/80) 보다 중간값 크로스가 안정적"
      ]
    }
  },

  "lessons_learned": [
    {
      "id": "L001",
      "source_strategy": "vpin_contrarian",
      "iteration": 1,
      "date": "2026-01-08",
      "title": "Risk-Reward Inversion",
      "issue": "Win Rate 58.8%이나 총 손실 (PF 0.94)",
      "context": "Take Profit 0.8%, Stop Loss 0.4%로 설정했으나 실제 Avg Win < Avg Loss",
      "root_cause": "TP에 도달하기 전에 다른 조건(max_hold_bars, RSI 정상화)으로 먼저 exit",
      "fix": "exit 조건 우선순위 정리: TP/SL > time-based exit > indicator normalization",
      "prevention": "백테스트 후 Avg Win / Avg Loss 비율이 설계한 R:R와 일치하는지 확인",
      "tags": ["risk_reward", "exit_strategy", "parameter_tuning"],
      "severity": "critical",
      "affected_indicators": ["vpin", "rsi"]
    },
    {
      "id": "L002",
      "source_strategy": "bb_squeeze",
      "iteration": 2,
      "date": "2026-01-09",
      "title": "Short Position Underperformance",
      "issue": "Short 포함 시 IS 성과 하락",
      "context": "use_short=true일 때 PF 1.46 → use_short=false일 때 PF 3.57",
      "root_cause": "테스트 기간 BTC 상승 추세, Short은 구조적 불리",
      "fix": "use_short=false로 변경",
      "prevention": "Breakout/Momentum 전략에서 Short은 별도 필터 또는 비활성화 고려",
      "tags": ["short_selling", "regime_dependency", "directional_bias"],
      "severity": "high",
      "affected_indicators": ["bollinger_bands"]
    },
    {
      "id": "L003",
      "source_strategy": "multiple",
      "iteration": null,
      "date": "2026-01-09",
      "title": "Fee Ratio Threshold",
      "issue": "fee_ratio < 1.5인 전략은 수수료에 잠식됨",
      "context": "avg_volatility / round_trip_fee < 1.5이면 손익분기 어려움",
      "root_cause": "변동성 대비 수수료가 너무 높음",
      "fix": "EDA 단계에서 fee_ratio >= 1.5 검증 필수",
      "prevention": "Researcher EDA에서 fee_ratio 검증 단계 의무화",
      "tags": ["fees", "eda", "profitability"],
      "severity": "critical",
      "affected_indicators": []
    }
  ],

  "common_mistakes": {
    "fee_dominated_loss": {
      "pattern": "높은 Win Rate인데 Total Return 마이너스",
      "cause": "수수료 > 평균 수익",
      "symptoms": ["Win Rate > 50%", "Total Return < 0%", "Avg Win < fee"],
      "prevention": "fee_ratio >= 1.5 검증",
      "affected_count": 3
    },
    "rr_inversion": {
      "pattern": "설계한 R:R와 실제 R:R 불일치",
      "cause": "TP/SL 외 다른 exit 조건이 먼저 트리거",
      "symptoms": ["Avg Win / Avg Loss != TP / SL"],
      "prevention": "exit 우선순위 명확화, 백테스트 후 실제 R:R 검증",
      "affected_count": 2
    },
    "overfitting_to_period": {
      "pattern": "IS 우수, OS 급락",
      "cause": "특정 기간 패턴에 과적합",
      "symptoms": ["IS Return >> OS Return", "IS Sharpe 방향 != OS Sharpe 방향"],
      "prevention": "파라미터 수 최소화, 단순한 로직 선호",
      "affected_count": 4
    }
  },

  "category_taxonomy": {
    "volatility_breakout": ["bb_squeeze", "breakout_frontrun", "vpin_breakout_filter"],
    "mean_reversion": ["vpin_contrarian", "vpin_rsi_mean_reversion", "vwap_reversion"],
    "momentum": ["ofi_momentum", "ofi_vpin_explosion", "ofi_trend_momentum"],
    "market_making": ["dual_vpin", "dual_vpin_cdf"],
    "regime_based": ["dual_vpin_rsi", "funding_divergence"]
  }
}
```

### 3.2 Schema Design Principles

1. **Flat over Nested**: 깊은 중첩 피함, Opus가 파싱하기 쉽게
2. **Tags for Search**: 자연어 쿼리 매칭용 태그 필드
3. **Explicit Relationships**: 관계를 별도 배열로 명시
4. **Actionable Lessons**: 교훈에 `fix`, `prevention` 필드로 실행 가능한 조언

---

## 4. Claude Code Skill/Command/Agent 구현

> **참고**: Claude Code의 Skills, Commands, Agents 구조 기반 (Context7 문서 참조)

### 4.1 구현 옵션 비교

| 컴포넌트 | 용도 | 트리거 방식 | 추천 |
|----------|------|-------------|------|
| **Command** (`.claude/commands/`) | 사용자가 `/command` 호출 | 명시적 슬래시 커맨드 | ✅ KB 조회용 |
| **Skill** (`.claude/skills/`) | 맥락 기반 자동 활성화 | 프롬프트에 트리거 문구 | ✅ 자동 참조용 |
| **Agent** (`.claude/agents/`) | 복잡한 멀티스텝 작업 | Task tool로 spawn | ❌ 과도함 |

**결론**: Command + Skill 조합 사용
- **Command**: `/strategy-kb` - 사용자/에이전트가 명시적으로 호출
- **Skill**: `strategy-knowledge` - Researcher가 새 전략 설계 시 자동 트리거

---

### 4.2 Command 구현: `/strategy-kb`

**File**: `.claude/commands/strategy_kb.md`

```markdown
---
description: Query strategy knowledge base for lessons, similar strategies, and best practices
argument-hint: <subcommand> [args]
allowed-tools: Read, Grep
---

# Strategy Knowledge Base Query

You are querying the strategy ontology knowledge base.

## Available Subcommands

| Subcommand | Usage | Description |
|------------|-------|-------------|
| `lessons` | `/strategy-kb lessons <indicator\|tag>` | Get lessons for indicator/tag |
| `similar` | `/strategy-kb similar <strategy>` | Find similar strategies |
| `indicator` | `/strategy-kb indicator <name>` | Get best practices for indicator |
| `mistakes` | `/strategy-kb mistakes <pattern>` | Lookup common mistake patterns |
| `search` | `/strategy-kb search <query>` | Semantic search across KB |

## Arguments
$ARGUMENTS

## Data Source
@strategies_ontology.json

## Instructions

1. Parse the subcommand from `$1`
2. Read `strategies_ontology.json`
3. Filter relevant entries based on subcommand:
   - `lessons`: Filter `lessons_learned` by `affected_indicators` or `tags`
   - `similar`: Filter `relationships` where `type=similar_to` or `shares_indicator`
   - `indicator`: Return `indicator_taxonomy[name]`
   - `mistakes`: Return `common_mistakes[pattern]`
   - `search`: Semantic match against `hypothesis`, `tags`, `title` fields
4. Format response concisely (max 5 results)
5. Include actionable `fix` and `prevention` for lessons

## Response Format

```
## /strategy-kb {subcommand} {args}

### [Result Title] (severity: {level})
- **Source**: {strategy}, iteration {n}
- **Issue**: {brief description}
- **Fix**: {actionable fix}
- **Prevention**: {how to avoid}

---
Related strategies: {list}
```
```

---

### 4.3 Skill 구현: `strategy-knowledge`

**File**: `.claude/skills/strategy-knowledge/SKILL.md`

```markdown
---
name: Strategy Knowledge Base
description: This skill should be used when the user asks to "design a new strategy", "create a VPIN strategy", "implement mean reversion", mentions indicators like "VPIN", "OFI", "RSI", "Bollinger Bands", or when starting a new strategy design workflow. Provides access to lessons learned, best practices, and similar strategy references.
version: 1.0.0
---

# Strategy Knowledge Base Skill

## When to Activate

This skill provides proactive knowledge injection when:
1. User mentions designing a **new trading strategy**
2. User mentions specific indicators: **VPIN, OFI, RSI, Bollinger Bands, funding rate**
3. Strategy iteration begins (Researcher agent starts)
4. Debugging strategy failures (Analyst detects pattern)

## Proactive Triggering Examples

<example>
Context: User requests new VPIN-based strategy
user: "VPIN 기반 역매매 전략 설계해줘"
assistant: "VPIN 관련 교훈을 먼저 확인하겠습니다."
<commentary>
VPIN 언급 시 자동으로 /strategy-kb lessons vpin 호출하여
L001 (Risk-Reward Inversion), L003 (Fee Ratio) 등 사전 로드
</commentary>
</example>

<example>
Context: Strategy iteration fails with high win rate but negative return
user: "Win Rate 60%인데 왜 손실이지?"
assistant: "알려진 실수 패턴을 확인해보겠습니다."
<commentary>
fee_dominated_loss 또는 rr_inversion 패턴 매칭 시도
</commentary>
</example>

<example>
Context: Researcher starting new strategy design
user: "BB Squeeze와 비슷한 breakout 전략 만들어줘"
assistant: "기존 유사 전략을 먼저 참조하겠습니다."
<commentary>
bb_squeeze의 relationships에서 similar_to 관계 조회
breakout_frontrun, vpin_breakout_filter 등 참조
</commentary>
</example>

## Knowledge Base Location

- **Ontology JSON**: `strategies_ontology.json` (프로젝트 루트)
- **Command**: `/strategy-kb` for explicit queries

## Key Data Structures

### Lessons Learned (Critical First)
```json
{
  "id": "L001",
  "title": "Risk-Reward Inversion",
  "severity": "critical",
  "fix": "exit 조건 우선순위 정리",
  "prevention": "백테스트 후 실제 R:R 검증"
}
```

### Indicator Best Practices
```json
{
  "vpin": {
    "best_practices": [
      "VOLUME bar와 함께 사용 권장",
      "CDF 변환으로 정규화 필요"
    ]
  }
}
```

## Integration with Agent Workflow

| Agent | When to Inject | What to Inject |
|-------|----------------|----------------|
| Researcher | Step 1 (Context) | Lessons for main indicator |
| Researcher | Step 3 (Hypothesis) | Similar strategies |
| Developer | Step 1 (Read) | Similar implementations |
| Analyst | Step 4 (Analyze) | Mistake patterns |
```

---

### 4.4 Proactive Triggering 설계

Claude Code Skill의 **Proactive Triggering** 패턴 활용:

```markdown
## Type 1: Keyword Trigger (명시적)
- "VPIN 전략" → `/strategy-kb lessons vpin`
- "breakout 전략" → `/strategy-kb indicator bollinger_bands`

## Type 2: Context Trigger (암시적)
- Researcher 시작 → 해당 indicator의 lessons 자동 로드
- Analyst 실패 분석 → mistake patterns 자동 매칭

## Type 3: Pattern Trigger (진단)
- Win Rate > 50% && Return < 0 → `fee_dominated_loss` 패턴 제안
- IS >> OS → `overfitting_to_period` 패턴 제안
```

---

### 4.5 Directory Structure

```
.claude/
├── commands/
│   └── strategy_kb.md          # /strategy-kb command
├── skills/
│   └── strategy-knowledge/
│       ├── SKILL.md            # Skill definition
│       └── references/
│           └── query-examples.md
├── agents/
│   ├── researcher.md           # (기존) + KB 참조 추가
│   ├── developer.md            # (기존) + KB 참조 추가
│   └── analyst.md              # (기존) + KB 참조 추가
└── settings.json

strategies_ontology.json        # Knowledge base (프로젝트 루트)
```

---

### 4.6 Response Format Examples

#### `/strategy-kb lessons vpin` Response

```markdown
## /strategy-kb lessons vpin

Found 3 lessons related to "vpin":

### L001: Risk-Reward Inversion (critical)
- **Source**: vpin_contrarian, iteration 1
- **Issue**: Win Rate 58.8%이나 총 손실 (PF 0.94)
- **Fix**: exit 조건 우선순위 정리: TP/SL > time-based > indicator
- **Prevention**: 백테스트 후 Avg Win / Avg Loss 비율 검증

### L003: Fee Ratio Threshold (critical)
- **Source**: multiple strategies
- **Issue**: fee_ratio < 1.5인 전략은 수수료에 잠식
- **Fix**: EDA 단계에서 fee_ratio >= 1.5 검증 필수

### Best Practices for VPIN:
- VOLUME bar와 함께 사용 권장
- bucket_size는 거래량의 1/50 수준
- CDF 변환으로 정규화 필요

---
Strategies using VPIN: vpin_contrarian, dual_vpin, dual_vpin_cdf, dual_vpin_rsi, vpin_breakout_filter, ofi_vpin_explosion (6개)
```

#### `/strategy-kb similar bb_squeeze` Response

```markdown
## /strategy-kb similar bb_squeeze

### Similar Strategies

| Strategy | Similarity | Shared Concepts |
|----------|------------|-----------------|
| breakout_frontrun | 0.85 | breakout, frontrun, volatility |
| vpin_breakout_filter | 0.72 | breakout, vpin_filter |

### bb_squeeze Details
- **Category**: volatility_breakout
- **Indicators**: bollinger_bands, keltner_channel, squeeze
- **Best Metrics**: PF 3.57, Win Rate 56.1%, Sharpe 0.46

### Recommendations
- breakout_frontrun의 frontrun 타이밍 로직 참조 가능
- vpin_breakout_filter의 VPIN 필터 아이디어 차용 고려

---
Code paths:
- bb_squeeze: src/intraday/strategies/tick/bb_squeeze.py
- breakout_frontrun: src/intraday/strategies/tick/breakout_frontrun.py
```

#### `/strategy-kb mistakes rr_inversion` Response

```markdown
## /strategy-kb mistakes rr_inversion

### Pattern: Risk-Reward Inversion

| Field | Value |
|-------|-------|
| Pattern | 설계한 R:R와 실제 R:R 불일치 |
| Cause | TP/SL 외 다른 exit 조건이 먼저 트리거 |
| Affected Count | 2 strategies |

### Symptoms
- Avg Win / Avg Loss != TP / SL ratio
- 예: TP/SL = 2:1 설계했으나 실제 Avg Win/Loss = 0.8:1

### Prevention
1. Exit 우선순위 명확화: `TP/SL > time-based > indicator normalization`
2. 백테스트 후 실제 R:R 검증 필수
3. max_hold_bars가 TP 도달 전에 exit하지 않는지 확인

### Related Lessons
- L001: vpin_contrarian에서 발견
```

---

## 5. Agent Workflow Integration

### 5.1 Researcher Prompt Changes

```diff
## Step 1: Understand the Context

**Read these first:**
1. User's idea from Orchestrator
2. `{name}_dir/memory.md` if exists (for iterations)
+ 3. `/strategy-kb lessons {main_indicator}` - Load relevant lessons
+ 4. `/strategy-kb search {hypothesis_keywords}` - Find similar strategies

+ **MANDATORY**: Before forming hypothesis, check known lessons for your indicators.
+ If a lesson with severity=critical exists, you MUST address it in your design.
```

### 5.2 Developer Prompt Changes

```diff
## Step 1: Read algorithm_prompt.txt

**Read `{name}_dir/algorithm_prompt.txt` and extract:**
...

+ **OPTIONAL but recommended:**
+ `/strategy-kb similar {strategy_name}` - Review similar implementations
+ Avoid reinventing patterns that already exist.
```

### 5.3 Analyst Prompt Changes

```diff
## Step 6: Output

### If APPROVED
1. **Create signal file FIRST**: `{name}_dir/APPROVED.signal`
2. Write `{name}_dir/backtest_report.md`
3. Update `{name}_dir/memory.md`
+ 4. **Update Knowledge Base**: Run ontology update script

### If NEED_IMPROVEMENT
...
+ **Extract Lesson**: If a new failure pattern is discovered, add to lessons_learned
```

---

## 6. Implementation Roadmap

### Phase 1: Bootstrap Ontology JSON (Hybrid Approach)

**2-Layer Generation 아키텍처:**

```
┌─────────────────────────────────────────────────────────────┐
│                    Ontology Generation                       │
├─────────────────────────────────────────────────────────────┤
│  Layer 1: Rule-Based (빠름, 구조화)                          │
│  - memory.md 파싱 → iterations, metrics                      │
│  - 코드 import 분석 → indicators                             │
│  - 디렉토리 구조 → strategy list                             │
├─────────────────────────────────────────────────────────────┤
│  Layer 2: Semantic Analysis (깊음, 뉘앙스) [--semantic]      │
│  - 코드 로직 이해 → "이 전략은 실제로 뭘 하는가?"            │
│  - memory.md 행간 → "왜 이 파라미터를 바꿨는가?"             │
│  - 전략 간 비교 → "A와 B의 진짜 차이점은?"                   │
└─────────────────────────────────────────────────────────────┘
```

**1. Script**: `scripts/build_ontology.py`

```bash
# 빠른 빌드 (Rule-Based only) - ~1분
uv run python scripts/build_ontology.py

# 심층 빌드 (Semantic enrichment) - 전략당 ~30초
uv run python scripts/build_ontology.py --semantic
```

**Rule-Based Extraction (Layer 1):**
- Scan all `*_dir/` folders
- Extract strategy metadata from `memory.md` (정규식 파싱)
- Parse indicators from strategy code (`import` statements, class docstrings)
- Generate basic `strategies_ontology.json`

**Semantic Enrichment (Layer 2, --semantic flag):**

각 전략에 대해 Opus 4.5가 코드와 memory를 읽고 다음을 추출:

| 필드 | 설명 | 예시 |
|------|------|------|
| `core_logic` | 전략이 실제로 하는 것 (1문장) | "VPIN > 0.8일 때 가격 반전 베팅" |
| `implicit_assumptions` | 코드에 암묵적으로 가정된 시장 조건 | ["고 VPIN 후 즉각적 반전 가정"] |
| `failure_nuance` | memory에서 읽히는 실패의 진짜 원인 | "max_hold_bars가 TP 도달 전 트리거" |
| `similar_patterns` | 이 로직과 유사한 알려진 패턴 | ["mean_reversion", "vpin_fade"] |
| `hidden_risks` | 코드에서 발견되는 잠재적 위험 | ["Trending 시장에서 연속 손실 가능"] |

**Rule-Based vs Semantic 비교:**

| 항목 | Rule-Based | Semantic (Opus) |
|------|------------|-----------------|
| Indicator 사용 | `import vpin` → "uses VPIN" | "VPIN을 CDF 변환 없이 raw로 사용 → 불안정" |
| 실패 원인 | "PF < 1.0" | "TP 도달 전 max_hold_bars가 먼저 트리거" |
| 전략 유사성 | "둘 다 VPIN 사용" | "둘 다 역매매 가설이지만 A는 즉시, B는 확인 후 진입" |
| 숨겨진 가정 | ❌ 감지 불가 | "이 전략은 암묵적으로 trending 시장 가정" |

**2. JSON Output Schema (Enriched)**:

```json
{
  "strategies": {
    "vpin_contrarian": {
      "name": "VPINContrarianStrategy",
      "indicators": ["vpin", "rsi"],
      "best_metrics": {"pf": 0.94, "win_rate": 58.8},

      "_semantic": {
        "core_logic": "VPIN > 0.8일 때 가격 반전 베팅 (contrarian)",
        "implicit_assumptions": [
          "고 VPIN 후 즉각적 반전 가정 (실제론 지연 있음)",
          "단일 threshold로 모든 시장 상황 커버 가정"
        ],
        "failure_nuance": "Win Rate 58.8%에도 손실인 이유: exit 조건 중 max_hold_bars(30)가 TP(1.5%) 도달 전에 트리거되어 평균 수익이 평균 손실보다 작음",
        "similar_patterns": ["mean_reversion", "vpin_fade"],
        "hidden_risks": [
          "Trending 시장에서 연속 손실 가능",
          "VPIN spike가 실제 정보가 아닌 노이즈일 때 취약"
        ]
      }
    }
  }
}
```

**3. Manual Review**:
- Verify relationships (similar_to, evolved_from)
- Categorize strategies (volatility_breakout, mean_reversion, etc.)
- Curate lessons_learned (severity 태그, actionable fix 추가)
- **Semantic 결과 검증**: 잘못된 추론 수정

### Phase 2: Claude Code Command 등록 (30 min)

1. **Create Command File**:
   ```bash
   mkdir -p .claude/commands
   # PRD Section 4.2의 내용을 복사
   cat > .claude/commands/strategy_kb.md << 'EOF'
   ---
   description: Query strategy knowledge base
   argument-hint: <subcommand> [args]
   allowed-tools: Read, Grep
   ---
   ... (PRD 내용)
   EOF
   ```

2. **Test Command**:
   ```bash
   # Claude Code에서 테스트
   /strategy-kb lessons vpin
   /strategy-kb similar bb_squeeze
   ```

### Phase 3: Claude Code Skill 등록 (30 min)

1. **Create Skill Directory**:
   ```bash
   mkdir -p .claude/skills/strategy-knowledge/references
   # PRD Section 4.3의 내용을 복사
   cat > .claude/skills/strategy-knowledge/SKILL.md << 'EOF'
   ---
   name: Strategy Knowledge Base
   description: This skill should be used when...
   version: 1.0.0
   ---
   ... (PRD 내용)
   EOF
   ```

2. **Verify Skill Activation**:
   - "VPIN 전략 설계해줘" 입력 시 자동 트리거 확인
   - Proactive knowledge injection 동작 검증

### Phase 4: Agent Prompt Integration (1 hour)

1. **Update `scripts/agent/agents/researcher.py`**:
   ```python
   # System prompt에 추가
   """
   ## Step 0: Load Knowledge Base (NEW)

   Before designing, query relevant lessons:
   /strategy-kb lessons {main_indicator}
   /strategy-kb similar {hypothesis_keywords}

   If severity=critical lessons exist, you MUST address them.
   """
   ```

2. **Update `scripts/agent/agents/analyst.py`**:
   ```python
   # System prompt에 추가
   """
   ## Failure Diagnosis (NEW)

   When metrics fail, check known patterns:
   /strategy-kb mistakes fee_dominated_loss  # if Win Rate > 50%, Return < 0
   /strategy-kb mistakes rr_inversion        # if Avg Win < Avg Loss
   """
   ```

3. **Add Ontology Update to Analyst Flow**:
   ```python
   # After APPROVED or NEED_IMPROVEMENT
   """
   ## Step 7: Update Knowledge Base (NEW)

   If new lesson discovered:
   1. Extract lesson from failure analysis
   2. Add to strategies_ontology.json lessons_learned
   3. Tag with severity and affected_indicators
   """
   ```

### Phase 5: Auto-Update Hook (Optional, Future)

1. **Post-Backtest Hook** (`.claude/hooks/`):
   ```markdown
   ---
   event: PostToolUse
   tool: mcp__backtest__run_backtest
   ---
   After backtest completes, update strategies_ontology.json:
   - Update best_metrics for strategy
   - Increment iterations count
   - Add lesson if failure pattern detected
   ```

2. **Relationship Inference**:
   - Code similarity (AST diff) → `similar_to` 자동 생성
   - Shared imports → `shares_indicator` 자동 생성

---

## 7. Success Metrics

### Primary Metrics

| Metric | Baseline | Target | Measurement |
|--------|----------|--------|-------------|
| Iterations to APPROVED | 4-5 | 2-3 | Avg across 10 strategies |
| Repeated Mistakes | ~30% | <10% | Lesson match in failures |
| Context Efficiency | N/A | 60% reduction | Tokens used for exploration |

### Secondary Metrics

| Metric | Description |
|--------|-------------|
| Lesson Utilization | % of designs that reference lessons |
| Cross-Strategy Learning | Times similar strategy referenced |
| Knowledge Growth | New lessons added per week |

### Validation Plan

1. **A/B Test**:
   - 5 strategies with KB access
   - 5 strategies without
   - Compare iterations, repeated mistakes

2. **Qualitative Review**:
   - Are lessons being referenced?
   - Is advice actionable?
   - Are agents finding relevant similar strategies?

---

## 8. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| JSON gets stale | High | Medium | Auto-update hook after backtest |
| Semantic search inaccurate | Medium | Low | Tags as fallback, explicit relationships |
| Context overhead from KB | Low | Medium | Lazy loading, top-5 results only |
| Incorrect lessons propagate | Low | High | Manual review for critical lessons |
| Schema changes break Skill | Low | Medium | Version field, backward compatibility |

---

## 9. Future Enhancements

### 9.1 Auto-Relationship Inference
- Code similarity (AST diff) → `similar_to` 자동 생성
- Indicator usage → `shares_indicator` 자동 생성

### 9.2 Performance Benchmarking
- 같은 지표 사용 전략 간 성과 비교
- "VPIN 전략 중 BB Squeeze가 최고 PF" 자동 집계

### 9.3 Recommendation Engine
- "이 가설에는 X 전략 접근법이 적합"
- "Y 지표와 Z 지표 조합은 피하세요"

### 9.4 Multi-Asset Extension
- ETH, SOL 등 다른 자산 전략 추가
- Cross-asset 관계 (BTC 선행 지표로 ETH 예측)

---

## Appendix A: Sample Queries & Responses

### Query 1: New VPIN Strategy Design
```
User: VPIN 기반 새 역매매 전략 설계해줘

Researcher:
/strategy-kb lessons vpin

[KB Response: L001 Risk-Reward Inversion, L003 Fee Ratio...]

Based on lessons learned:
1. Exit 조건 우선순위 명확화 (L001 대응)
2. fee_ratio >= 1.5 검증 (L003 대응)
3. 기존 vpin_contrarian과 차별화: RSI 대신 OFI 사용
```

### Query 2: Debug Failing Strategy
```
Analyst: Win Rate 60%인데 Total Return -2%

/strategy-kb mistakes fee_dominated_loss

[KB Response: pattern matched, cause = 수수료 > 평균 수익]

진단: Avg Win ($0.50) < round_trip_fee ($0.80)
권장: bar_size 증가 또는 LIMIT order로 수수료 절감
```

### Query 3: Find Similar Strategy
```
Developer: breakout 전략 구현하는데 참고할 코드 있나?

/strategy-kb similar breakout_frontrun

[KB Response: bb_squeeze (similarity 0.85), vpin_breakout_filter (0.72)]

bb_squeeze의 squeeze 감지 로직 참조 가능
vpin_breakout_filter의 VPIN 필터 아이디어 차용 가능
```

---

## Appendix B: Ontology Update Script (Hybrid Approach)

```python
# scripts/build_ontology.py (pseudo-code)

import json
import argparse
from pathlib import Path

def build_ontology(semantic: bool = False):
    """
    2-Layer Ontology Generation

    Args:
        semantic: If True, run Opus 4.5 semantic analysis (Layer 2)
    """
    ontology = {
        "version": "1.0",
        "strategies": {},
        "relationships": [],
        "indicator_taxonomy": {},
        "lessons_learned": [],
        "common_mistakes": {}
    }

    # ========================================
    # Layer 1: Rule-Based Extraction (빠름)
    # ========================================

    # Scan strategy directories
    for dir in Path(".").glob("*_dir"):
        memory = parse_memory(dir / "memory.md")
        code_path = find_strategy_code(dir.stem)

        strategy_data = {
            **extract_metadata(memory),
            "indicators": extract_indicators_from_code(code_path),
            "code_path": str(code_path),
            "memory_path": str(dir / "memory.md"),
        }

        ontology["strategies"][dir.stem] = strategy_data
        ontology["lessons_learned"].extend(extract_lessons(memory))

    # Build indicator taxonomy
    for name, strategy in ontology["strategies"].items():
        for indicator in strategy.get("indicators", []):
            if indicator not in ontology["indicator_taxonomy"]:
                ontology["indicator_taxonomy"][indicator] = {"strategies": []}
            ontology["indicator_taxonomy"][indicator]["strategies"].append(name)

    # ========================================
    # Layer 2: Semantic Enrichment (깊음)
    # ========================================

    if semantic:
        print("Running semantic analysis with Opus 4.5...")
        for name, strategy in ontology["strategies"].items():
            print(f"  Analyzing {name}...")
            semantic_context = analyze_with_opus(
                code_path=strategy["code_path"],
                memory_path=strategy["memory_path"]
            )
            strategy["_semantic"] = semantic_context

    # Save
    with open("strategies_ontology.json", "w") as f:
        json.dump(ontology, f, indent=2, ensure_ascii=False)

    print(f"Generated strategies_ontology.json with {len(ontology['strategies'])} strategies")


def analyze_with_opus(code_path: str, memory_path: str) -> dict:
    """
    Opus 4.5 시멘틱 분석

    Input: strategy code + memory.md
    Output: semantic enrichment fields
    """
    code = Path(code_path).read_text() if Path(code_path).exists() else ""
    memory = Path(memory_path).read_text() if Path(memory_path).exists() else ""

    prompt = f'''
    다음 전략 코드와 메모리를 분석하라:

    ## Code
    {code[:5000]}  # truncate for context limit

    ## Memory
    {memory[:3000]}  # truncate for context limit

    ## 분석 요청
    JSON으로 응답 (다른 텍스트 없이):
    {{
        "core_logic": "이 전략이 실제로 하는 것 (1문장)",
        "implicit_assumptions": ["코드에 암묵적으로 가정된 시장 조건 리스트"],
        "failure_nuance": "memory에서 읽히는 실패의 진짜 원인 (있다면)",
        "similar_patterns": ["이 로직과 유사한 알려진 트레이딩 패턴"],
        "hidden_risks": ["코드에서 발견되는 잠재적 위험"]
    }}
    '''

    # Call Anthropic API with Claude Opus 4.5
    response = call_anthropic_api(prompt, model="claude-opus-4-5-20251101")
    return json.loads(response)


def extract_indicators_from_code(code_path: Path) -> list[str]:
    """코드에서 사용된 지표 추출 (import, docstring 분석)"""
    known_indicators = [
        "vpin", "ofi", "rsi", "bollinger_bands", "keltner_channel",
        "macd", "volume_imbalance", "funding_rate", "cvd"
    ]

    if not code_path.exists():
        return []

    code = code_path.read_text().lower()
    return [ind for ind in known_indicators if ind in code]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build strategy ontology")
    parser.add_argument(
        "--semantic",
        action="store_true",
        help="Run Opus 4.5 semantic analysis (slower but deeper)"
    )
    args = parser.parse_args()

    build_ontology(semantic=args.semantic)
```

### 실행 예시

```bash
# 빠른 빌드 (Rule-Based only) - ~1분, 26개 전략
$ uv run python scripts/build_ontology.py
Generated strategies_ontology.json with 26 strategies

# 심층 빌드 (Semantic enrichment) - 전략당 ~30초
$ uv run python scripts/build_ontology.py --semantic
Running semantic analysis with Opus 4.5...
  Analyzing bb_squeeze...
  Analyzing vpin_contrarian...
  ...
Generated strategies_ontology.json with 26 strategies
```

---

## Document History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-09 | Initial PRD |
| 1.1 | 2026-01-09 | Claude Code Skill/Command/Agent 구조 반영 (Context7 문서 기반) |
| 1.2 | 2026-01-09 | Hybrid Approach 추가: Rule-Based + Semantic (Opus 4.5) 2-Layer 생성 |

---

## Appendix C: Claude Code Component Reference

> Context7 `/anthropics/claude-code` 문서 참조

### Command vs Skill vs Agent

| Component | Location | Trigger | Use Case |
|-----------|----------|---------|----------|
| **Command** | `.claude/commands/*.md` | `/command-name` | 명시적 사용자 호출 |
| **Skill** | `.claude/skills/*/SKILL.md` | 프롬프트 키워드 매칭 | 맥락 기반 자동 활성화 |
| **Agent** | `.claude/agents/*.md` | Task tool spawn | 복잡한 멀티스텝 작업 |

### Command File Format

```markdown
---
description: Brief description
argument-hint: [arg1] [arg2]
allowed-tools: Read, Bash(git:*)
---

Command prompt content with:
- Arguments: $1, $2, or $ARGUMENTS
- Files: @path/to/file
- Bash: !`command here`
```

### Skill File Format

```markdown
---
name: Skill Name
description: This skill should be used when the user asks to "phrase 1", "phrase 2"...
version: 1.0.0
---

# Skill Content

## When to Activate
...

## Proactive Triggering Examples
<example>
Context: ...
user: "..."
assistant: "..."
<commentary>
Why this triggers the skill
</commentary>
</example>
```

### Proactive Triggering Types

1. **Type 1: Explicit Request** - 사용자가 명시적으로 요청
2. **Type 2: Proactive After Work** - 관련 작업 후 자동 트리거
3. **Type 3: Tool Usage Pattern** - 특정 도구 사용 패턴 감지
4. **Type 4: Error/Failure Pattern** - 에러/실패 패턴 감지
