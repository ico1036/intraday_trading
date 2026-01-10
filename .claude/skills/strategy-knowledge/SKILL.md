---
name: Strategy Knowledge Base
description: This skill should be used when the user asks to "design a new strategy", "create a VPIN strategy", "implement mean reversion", mentions indicators like "VPIN", "OFI", "RSI", "Bollinger Bands", or when starting a new strategy design workflow. Provides access to lessons learned, best practices, and similar strategy references.
version: 1.0.0
---

# Strategy Knowledge Base Skill

This skill provides proactive knowledge injection for trading strategy development.

## When to Activate

Activate this skill when:
1. User mentions designing a **new trading strategy**
2. User mentions specific indicators: **VPIN, OFI, RSI, Bollinger Bands, funding rate, squeeze**
3. Strategy iteration begins (Researcher agent starts)
4. Debugging strategy failures (Analyst detects pattern)
5. User asks about **past strategy failures** or **lessons learned**

## Proactive Triggering Examples

<example>
Context: User requests new VPIN-based strategy
user: "VPIN 기반 역매매 전략 설계해줘"
assistant: "VPIN 관련 교훈을 먼저 확인하겠습니다."
<commentary>
VPIN 언급 시 자동으로 /strategy-kb lessons vpin 호출하여
관련 실패 사례와 best practices 사전 로드.
vpin_contrarian의 6번 iteration 실패 교훈이 중요함.
</commentary>
</example>

<example>
Context: Strategy iteration fails with high win rate but negative return
user: "Win Rate 60%인데 왜 손실이지?"
assistant: "알려진 실수 패턴을 확인해보겠습니다."
<commentary>
fee_dominated_loss 또는 rr_inversion 패턴 매칭 시도.
/strategy-kb mistakes fee_dominated_loss 호출.
</commentary>
</example>

<example>
Context: Researcher starting new strategy design
user: "BB Squeeze와 비슷한 breakout 전략 만들어줘"
assistant: "기존 유사 전략을 먼저 참조하겠습니다."
<commentary>
/strategy-kb similar bb_squeeze 호출하여
breakout_frontrun, vpin_breakout_filter 등 참조.
bb_squeeze는 approved 상태이므로 참고 가치 높음.
</commentary>
</example>

<example>
Context: User asks about indicator best practices
user: "RSI를 어떻게 써야 효과적이야?"
assistant: "RSI 사용 전략들의 경험을 확인하겠습니다."
<commentary>
/strategy-kb indicator rsi 호출하여
15개 전략에서의 RSI 사용 패턴 분석.
</commentary>
</example>

<example>
Context: Asking about what strategies exist
user: "지금까지 만든 전략 중에 성공한 게 뭐야?"
assistant: "전략 현황을 확인하겠습니다."
<commentary>
/strategy-kb stats 호출 후 approved 상태인 전략 필터링.
bb_squeeze가 PF 3.57로 가장 성공적.
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
  "source_strategy": "vpin_contrarian",
  "content": "Win Rate 58.8%이나 총 손실 (PF 0.94)",
  "affected_indicators": ["vpin", "rsi"]
}
```

### Strategy Entry
```json
{
  "name": "BBSqueezeStrategy",
  "category": "volatility_breakout",
  "indicators": ["bollinger_bands", "squeeze"],
  "best_metrics": {"profit_factor": 3.57, "win_rate": 56.1},
  "status": "approved",
  "iterations": 3
}
```

### Indicator Taxonomy
```json
{
  "vpin": {
    "strategies": ["vpin_contrarian", "dual_vpin", ...],
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

## Commands Available

- `/strategy-kb lessons <indicator>` - 특정 지표 관련 교훈
- `/strategy-kb similar <strategy>` - 유사 전략 찾기
- `/strategy-kb indicator <name>` - 지표 사용 현황
- `/strategy-kb mistakes <pattern>` - 실수 패턴 조회
- `/strategy-kb search <query>` - 자연어 검색
- `/strategy-kb stats` - KB 통계

## Best Practices for Usage

1. **새 전략 설계 전**: 해당 indicator의 lessons 먼저 확인
2. **실패 분석 시**: common_mistakes 패턴 매칭 시도
3. **유사 전략 참조**: similar 명령으로 기존 구현 확인
4. **severity=critical 교훈**: 반드시 설계에 반영 필요
