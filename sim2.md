# Agent strategy search loop

## 사용법

./auto_loop.sh                        # 새 실행 (auto-id, editor 열림)
./auto_loop.sh v1_accrual_focus_...   # 있으면 이어가기, 없으면 새로 만들고 실행
새 실행하면 `$EDITOR`로 PLAN.md가 열린다. 아래 두 가지를 작성하고 저장하면 루프 시작.

## PLAN.md — 실행 전 반드시 작성

## Targets (exit when met on a single trial)
info_ratio: 1.0
max_trials: 20          ← 최대 시도 횟수 (budget)

## Strategy request
- Long-only accrual-anomaly based strategy with monthly rebalancing.
  ← 여기에 원하는 전략 자유롭게 서술
Targets: info_ratio (S&P 500 대비 Information Ratio) ≥ 1.0 충족 시 자동 종료. 못 맞추면 `max_trials`에서 종료.
Strategy request: 에이전트가 매 iteration 읽고 이 방향으로 탐색.

## 제한값 (기본)

| 항목 | 기본값 | 변경 방법 |
|---|---|---|
| 최대 trial 수 | 20 | PLAN.md max_trials: N |
| IR 목표 (vs S&P 500) | 1.0 | PLAN.md info_ratio: X |
| Shell iter 상한 | 100 | ./auto_loop.sh --max N |
| Trial 타임아웃 | 600초 | scripts/execute_trial.py TIMEOUT_SEC |
| Universe 크기 | 3000 | _template.py univ_n |
| 포트폴리오 크기 | 100 | _template.py TOP_N (agent가 trial마다 변경) |

## 옵션

--no-edit    새 run에서 editor 스킵 (이전 PLAN 그대로 실행)
--edit       이어가기 전 PLAN.md 열기
--prepare    부트스트랩만, 실행 안 함
--max N      shell iter 상한 (default 100)
## 디렉토리 구조

archive/<run_id>/
├── PLAN.md              targets + strategy request (사용자 작성)
├── trial_log.jsonl      trial 기록 (자동)
├── research_map.md      테마 집계 (자동, 매 iter)
├── themes/*.md          테마별 탐색 일지 (자동)
├── patterns/*.md        발견된 규칙 (자동, 드물게)
├── source/trial_*.py    생성된 전략 소스 (자동)
├── trials/*.csv         trial별 yearly performance CSV (자동)
├── manifest.md          run 종료 요약 (자동)
└── DONE                 종료 센티넬 (자동)
## 산출물 저장 위치

| 산출물 | 위치 | 설명 |
|---|---|---|
| 템플릿 | auto_strategies/_template.py | 전략 스켈레톤. 여기에만 존재 |
| 전략 코드 | archive/<run>/source/trial_NNN.py | 에이전트가 템플릿 복사 후 생성 |
| 성과 CSV | archive/<run>/trials/trial_NNN_<name>.csv | yearly summary 등 경량 메트릭 |
| 백테스트 산출물 | backtest_output/<name>_<timestamp>/ | result.save(lite=True) 출력 (summary CSV, parquet, plot PNG) |

`auto_strategies/`에는 `_template.py`만 존재하며, 실행 중 생성되는 전략 코드는 전부 해당 run의 `archive/<run>/source/`에 저장된다. `backtest_output/`에는 run과 무관하게 모든 trial의 백테스트 결과가 timestamp 기준으로 누적된다.

## 종료 조건

info_ratio ≥ 목표 충족 OR max_trials 도달 → DONE 파일 생성 → 루프 자동 종료.

## 이어가기 / 연장

./auto_loop.sh v1_accrual_focus_...          # DONE 없으면 바로 이어감
rm archive/v1_.../DONE && ./auto_loop.sh v1_...  # DONE 있으면 지우고 연장
## 두 갈래 압축 — raw에서 파생되는 2개의 뷰

`archive/<run_id>/trial_log.jsonl`이 단일 source of truth. 이 raw 로그에서 에이전트가 읽을 2개의 압축 뷰가 서로 다른 cadence·주체로 파생된다.

       archive/<run_id>/trial_log.jsonl   ← raw facts (append-only)
                    │
       ┌────────────┴────────────┐
       │                         │
 매 iter (scripts)          run 종료 (LLM)
       │                         │
       ▼                         ▼
research_map.md            wiki/themes/<t>.md
constraints.json           wiki/combinations/<A>_x_<B>.md
theses.json                wiki/runs/<run>.md
(within-run digest)        (cross-run belief)
| 축 | within-run digest | cross-run wiki |
|---|---|---|
| 범위 | 단일 run | 전체 run |
| 갱신 | 매 iter 자동 | run 종료 시 한 번 |
| 생산 주체 | 결정론적 스크립트 | LLM (`/wiki-compile` 스킬) |
| 목적 | 중복·정체·블록리스트 실시간 체크 | 팩터·페어 belief 재서술 |
| 읽는 시점 | ORIENT Step 1 | ORIENT Step 1 |

두 갈래 모두 **raw를 직접 읽지 않는 에이전트를 위한 요약 레이어**다 (AGENT.md core rule #4: "Never read the whole `trial_log.jsonl`"). ORIENT는 이 두 압축 뷰만 읽고, raw는 `tail -n 5`로만 엿본다. wiki-compile은 예외적으로 raw를 직접 읽어 cross-run belief로 재압축하는 주체이며, 이는 런 종료 시 한 번만 실행된다.

결정론적 디지스트 ↔ 의미론적 위키의 분리는 CLAUDE.md 원칙 #6("deterministic rules vs. agent judgment")의 저장 레이어 구현이다.

## Wiki — Fact-based knowledge layer

매 run 종료 시 `scripts/build_wiki.py`가 `wiki/`를 재생성한다. presentation이 아니라 compiled belief — trial 원본은 `archive/`에 있고, wiki는 factor 단위로 증거를 집계한 믿음 상태.

### 구조
wiki/
├── facts/
│   ├── factors/<theme>.md          ← factor별 belief (12개 이하, bounded)
│   └── combinations/<A>_x_<B>.md   ← factor-pair composite 효과 (C(12,2)=66 상한)
└── cross_run/
    ├── best_recipes.md              ← run별 top 3 (ORIENT에서 매번 읽음)
    ├── dead_ends.md                 ← 실패 케이스
    └── pair_correlations.md         ← 원시 return 상관 테이블
핵심 특성: 파일 개수가 factor 종류로 bounded. 1000 run 돌려도 ~100 파일 상한 → Grep/Read로 영원히 retrieval 가능.

### Factor 페이지 포맷

---
factor: size
evidence_count: 11       # 이 factor가 관여한 trial 수
accepted_count: 11
best_sharpe: 0.98
mean_sharpe: 0.85
confidence: high         # n ≥ 5 = high, ≥ 2 = medium, 1 = low
---

# size
**Best observed**: v0/trial_018_size_qual_lowvol_mom — Sharpe 0.98

## Evidence
| Run/Trial | Components | Sharpe | CAGR | MDD |
| v0/018 | low_vol+momentum+quality+size | 0.98 | 16.09% | -43.05% |
| ...
Frontmatter는 agent/Dataview용 구조화 메타데이터, 본문은 인간 확인용 증거 리스트.

### Combination 페이지 포맷

Factor 두 개가 동시에 들어간 composite trial들을 집계. 예: quality_x_size.md = size와 quality가 함께 든 모든 composite 이력 + 최고 Sharpe + evidence count.

### Agent retrieval 패턴

# Factor belief 조회 (매 PROPOSE 시)
cat wiki/facts/factors/size.md

# 특정 factor 조합 조회 (composite 제안 시)
cat wiki/facts/combinations/size_x_quality.md

# 어떤 factor와 짝지었는지 목록
ls wiki/facts/combinations/ | grep size

# 아직 안 시도된 조합 찾기
comm -23 <(예상 pair 리스트) <(ls wiki/facts/combinations/)

# 고신뢰도 factor만
grep -l "confidence: high" wiki/facts/factors/
AGENT.md ORIENT 단계가 이 명령들로 retrieval 수행. 벡터 DB 없이 Unix 도구만으로 작동.

### 왜 이 구조인가

- Cardinality 상한: factor 수는 제한적 (~12). 파일 수 폭발 없음.
- Semantic path: facts/factors/size.md = 파일 이름이 개념. `wiki/trials/trial_018_...`처럼 opaque ID 아님.
- Evidence-weighted belief: evidence_count + `confidence`가 n=1 운빨과 n=50 축적을 구분.
- Markdown + frontmatter: Git diff 가능, 인간 편집 가능, Grep 가능, Obsidian 시각화 가능.

### Obsidian 설정 (선택)

`wiki/`를 Obsidian vault로 열면 그래프 시각화. Graph view 우상단 톱니 → Groups:

| Query | 색 |
|---|---|
| path:facts/factors | 파랑 (factor 허브) |
| path:facts/combinations | 초록 (조합 노드) |
| path:cross_run | 노랑 (cross-run 인덱스) |

노드 ~50개로 읽기 쉬운 그래프. factor hub가 중심, combination이 주변부, cross_run이 상단 요약.

### Wiki vs archive 역할 분담

- `archive/<run>/` — immutable raw record. trial_log.jsonl, source/*.py 등. 특정 trial 원본 보려면 cat archive/v47/source/trial_018.py.
- `wiki/` — 모든 run의 컴파일된 믿음. run 종료 시마다 rebuild (idempotent). factor-pair 단위 belief.


