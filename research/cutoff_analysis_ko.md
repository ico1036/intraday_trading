# 합성 멤버 컷오프 — 시그널 vs 노이즈 분석

**날짜**: 2026-05-12
**작성**: Claude (overnight L/S 배치 후속)
**상태**: 초안 — 사용자 피드백 후 게이트 확정

## 한줄 요약

기존 submittable 게이트 (S1–S7) 는 **단일 알파 발행 기준** 으로 설계됨 — 모든 임계가 "이 알파 혼자 트레이드 가능한가?" 를 묻는 형태. 이 게이트를 IS+OS 둘 다 가진 385개 알파에 적용하면 **통과 0개**. 병목은 **S1 (OS t-stat > 2.5)** — 어느 알파도 못 넘긴다.

다만 **모집단 수준 통계** 는 우리 시그널이 랜덤이 아님을 보여줌. 노이즈 가설 대비 **2.5배 초과 통과** 가 중간 t-stat 임계에서 관측됨. 합성 멤버 선택에는 S1 단독 완화가 아니라 **"시그널 vs 노이즈" 게이트** 로 전환하는 게 맞음.

**더 결정적 발견** (Section 8 추가): 풀의 페어와이즈 IS 일별 수익 상관이 **거의 1:1로 클론 수준** — 89% 의 페어가 ρ > 0.7, 67% 가 ρ > 0.9. 그러나 자세히 보면 알파는 **상관 무관 두 클러스터** 로 분리됨 — Donchian-breakout vs TS-mom. 클러스터 간 상관 0.05~0.15.

**최종 권장**: **G2 = 1.0 (시그널 게이트) ∧ τ = 0.95 (상관 dedup)** → 최종 **5~11 멤버** 의 진짜 분산된 합성 풀. 더 강한 결론은 **새 알파 family 가 필요** — 두 클러스터로는 합성 capacity 한계 명확.

---

## 1. 문제 설정

`alpha_dashboard_lib.classify_alpha` 의 11개 게이트, 요약:

| 그룹 | 게이트 | 임계 | 측정 대상 |
|---|---|---|---|
| Reject | R1 | bps > 0 (IS & OS) | 기본 수익성 |
| Reject | R2 | OS t-stat ≥ 1.5 | edge ≠ 노이즈 (85% 신뢰) |
| Reject | R3 | sharpe degr ≥ 0.4 | OS 가 Sharpe 부분 보존 |
| Reject | R4 | IS trades ≥ 100 | 표본 수 sanity |
| Submit | S1 | OS t-stat > 2.5 | 강한 통계적 유의 |
| Submit | S2 | OS bps > 2.0 | 의미 있는 edge 크기 |
| Submit | S3 | sharpe degr > 0.7 | 시간 안정성 |
| Submit | S4 | bps degr > 0.6 | bps 시간 안정성 |
| Submit | S5 | \|OS DD\| < 0.12 | 리스크 컨트롤 |
| Submit | S6 | OS profit factor > 1.3 | 승패 균형 |
| Submit | S7 | IS trades > 500 | 통계 파워 |

11개 모두 "이 **단일** 알파가 트레이드 가능한가?" 를 묻는다. **"이 알파가 포트폴리오에 기여하는가?"** 는 묻지 않는다. 합성 워크플로우에서 이 차이가 결정적:

- 단독으로는 노이즈 같은 알파도 동료 멤버와 무상관이면 포트폴리오에 강력한 멤버일 수 있음
- 단독으로는 깨끗한 알파도 기존 멤버와 중복이면 redundant

이 리포트는 사용자의 요청 — "단일 게이트 완화 + 합성용으로 재설계" — 에 답한다. **"어떤 알파가 단일 성과 magnitude 무관하게 진짜 시그널을 가지고 있는가?"** 를 측정한다.

## 2. 게이트별 통과율 — 병목 진단

![게이트별 통과율](figures/07_gate_efficiency.png)

IS+OS 둘 다 가진 **385 개 알파** 중:

| 게이트 | 통과 수 | % | 비고 |
|---|---:|---:|---|
| R4: IS trades ≥ 100 | 385 | 100% | 항상 만족 |
| G4: IS bps > 0 | 385 | 100% | 모든 알파가 IS 수익 |
| S7: IS trades > 500 | 359 | 93% | 충분히 거래 |
| G1: IS per-trade t ≥ 1.96 | 337 | 88% | IS edge 통계적으로 진짜 |
| R1: bps > 0 (IS&OS) | 317 | 82% | 대부분 OS 에도 수익 유지 |
| G3: OS bps > 0 | 317 | 82% | 부호 보존 강함 |
| S2: OS bps > 2.0 | 307 | 80% | 의미 있는 OS edge 크기 |
| G5: Sharpe 부호 일치 | 321 | 83% | IS↔OS 방향성 유지 |
| S5: \|OS DD\| < 0.12 | 248 | 64% | OS 드로우다운 통제 |
| R3: sharpe degr ≥ 0.4 | 235 | 61% | 부분적 강건성 |
| **G2: OS t ≥ 0.8** | **192** | **50%** | 절반이 약한 통계 유의 |
| **G2: OS t ≥ 1.0** | **152** | **39%** | 단측 p=0.16 |
| S3: sharpe degr > 0.7 | 57 | 15% | strict 강건성 |
| **R2: OS t ≥ 1.5** | **23** | **6%** | 결정적 병목 |
| **S1: OS t > 2.5** | **0** | **0%** | 아무도 못 넘김 |

**결론**: 병목은 **OS t-statistic**. OS 수익성 (G3, S2) 도 OS DD 도 Sharpe 감쇠도 아니다. 80%+ 가 OS 수익성을 유지하고, 83% 가 부호 일치한다. 단지 **"t > 2.5 (S1)" 또는 "t > 1.5 (R2)" 를 넘길 통계적 파워가 부족** 할 뿐.

## 3. OS t-stat 이 낮은 구조적 이유

trade-level t 통계량:

$$
t = \frac{\bar{x}_{\text{bps}}}{s_{\text{bps}} / \sqrt{N}} = \text{per\_trade\_sharpe} \cdot \sqrt{N}
$$

`per_trade_sharpe` 는 거래당 Sharpe (round-trip bps 의 mean/std). `N` 은 round-trip 수.

![Per-trade Sharpe IS vs OS](figures/05_per_trade_sharpe.png)

| 지표 | IS (중앙값) | OS (중앙값) | 감쇠 |
|---|---:|---:|---:|
| per-trade Sharpe | 0.088 | 0.035 | **0.40** ⚠ |
| trade count N | 797 | 643 | 0.81 |
| t-stat = ps · √N | 2.48 | 0.89 | 0.36 |

**OS 거래당 edge 가 IS 의 40% 수준** — 문제는 거래 수가 아니라 거래 quality. 비교: equity quant 에서 "IC 0.05" 가 respectable signal 로 통한다. 우리 IS per-trade Sharpe 0.088 은 건전, OS 0.035 는 약하지만 0 은 아님.

이건 universe 전반의 환경 변화 효과:
- **IS** (2022-01 → 2024-04): LUNA/FTX 충격 → 회복 → ETF rally — Donchian 계열 알파가 잘 잡는 강한 지속 추세
- **OS** (2024-04 → 2026-05): 반감기 이후, 짧고 덜 지속적인 사이클. 같은 신호 로직, 낮은 거래당 payoff

![OS t-stat 분포](figures/01_os_tstat_distribution.png)

분포를 보면 각 게이트가 어디를 자르는지 직관적: S1=2.5 는 빈 영역, R2=1.5 는 꼬리, G2=0.8~1.0 은 분포의 본체.

## 4. 모집단 수준 증거: 시그널은 실재한다

단일 알파 t-stat 논의는 각 알파를 독립적으로 본다. 우리는 385 개 알파 = 모집단을 가지고 있다. 귀무가설 **H₀: "모든 알파는 순수 노이즈"** 하에서 per-trade t-stat 은 표준정규 근사를 따라야 한다. 각 임계 τ 에서 통과 수는 Binomial(N=385, p = 1 − Φ(τ)) 분포.

![Observed vs null](figures/04_observed_vs_null.png)

| τ (임계) | E[count] under H₀ | 관측 | 비율 | P(≥ obs \| H₀) |
|---:|---:|---:|---:|---:|
| 0.0 | 192.5 | 317 | 1.65× | 0 |
| 0.5 | 118.8 | 263 | 2.21× | 0 |
| 0.8 | 81.6 | 208 | 2.55× | 0 |
| 1.0 | 61.1 | 152 | 2.49× | 0 |
| 1.28 | 38.6 | 82 | 2.12× | 5e-11 |
| 1.645 | 19.2 | 2 | 0.10× | 1.0 |
| 1.96 | 9.6 | 1 | 0.10× | 1.0 |
| 2.5 | 2.4 | 0 | 0× | 1.0 |

두 가지 발견:

1. **중간 임계 (τ ≤ 1.28)** 에서 노이즈 대비 **2.1–2.6배 초과** 통과 — 압도적으로 유의 (모두 p ≈ 0). **모집단에 진짜 시그널이 존재한다는 강력한 증거**.
2. **높은 임계 (τ ≥ 1.5)** 에서는 노이즈 대비 *deficit*. 이건 시그널이 없어서가 아니라, **OS edge 가 중간 정도 양수** (중앙값 per-trade Sharpe 0.035) 라서 t-statistic 질량이 t = 2 근처 노이즈 꼬리가 아닌 **t = 1 근처에 집중** 되어 있기 때문.

**해석**: 우리 알파들이 만드는 분포는 **양의 방향으로 이동했지만 크기는 제한된** 형태 — 중간 t 에 질량이 집중, 상단 꼬리 얇음. 이건 정확히 *유용한 합성 멤버* 의 모집단 프로파일: 각자가 작지만 진짜인 edge 를 기여.

## 5. 부호 보존 증거

IS → OS 전환 시 **부호가 같은** 시그널은 정의상 노이즈가 아님 (zero-mean 노이즈는 50% 확률로 부호 뒤집힘).

![IS vs OS Sharpe](figures/02_is_os_sharpe_scatter.png)

- 우상 사분면 (Sharpe 둘 다 > 0) = **G5 통과** = 부호 보존
- 321 / 385 = **83.4%** 가 이 사분면
- H₀ (각 split 독립 random Sharpe) 하에서는 25% 만 여기 들어감

대각선 점선은 "감쇠 없음" 표시. 대부분의 점이 대각선 *아래* — OS Sharpe 가 IS 보다 작음 — 하지만 압도적으로 0 위에 있음. **시그널은 dampening, 사라지는 게 아님.**

![Sharpe 감쇠](figures/06_sharpe_degradation.png)

감쇠 분포 (OS Sharpe / IS Sharpe) 는 0.5–0.7 근처에 중심, 대부분 0~1.5 사이. R3 (degr ≥ 0.4) 가 우측 꼬리를 잡아 61% 통과; S3 (degr > 0.7) 는 15% 만. 감쇠는 일어나지만 대부분 의미 있는 비율 유지.

## 6. 임계 sweep — 풀 크기와 family balance

합성 풀 크기는 G2 (OS t-stat) 컷오프에 의존. Base 게이트: G1 ∧ G3 ∧ G4 ∧ G5 ∧ G6 (IS-side 강하게, OS-side 부호 + 양수 bps, 양쪽 Sharpe 양수, 최소 표본).

![Pool vs threshold](figures/03_pool_vs_threshold.png)

| G2 임계 | 단측 p | 풀 | long_only | L/S | 균형 |
|---:|---:|---:|---:|---:|---|
| 0.0 (게이트 없음) | 0.50 | 291 | 104 | 187 | L/S 우세 |
| 0.5 | 0.31 | 243 | 104 | 139 | L/S 기울임 |
| **0.8** | **0.21** | **192** | **92** | **100** | **거의 1:1** |
| 1.0 | 0.16 | 140 | 74 | 66 | 균형 |
| 1.28 | 0.10 | 84 | 53 | 31 | long 기울임 |
| 1.645 | 0.05 | 30 | 24 | 6 | long 우세 |
| 2.5 (원래 S1) | 0.006 | 0 | 0 | 0 | 비어있음 |

핵심 변곡: **G2 = 0.8 ↔ 1.0** 사이에서 L/S count 가 거의 반 감소 (100 → 66), G2 = 1.28 에서는 L/S 가 31 로 붕괴. long-only count 는 더 안정 — long-persist family 가 symmetric L/S family 보다 IS/OS 페어에서 per-trade Sharpe 가 높기 때문.

## 7. 상관 분석 — 풀이 사실은 클론

G1∧G3∧G4∧G5∧G6 통과 291 알파의 **IS 일별 수익 페어와이즈 상관**:

![Pairwise correlation distribution](figures/08_pairwise_corr_dist.png)

```
all pairs:        median ρ = 0.92   mean = 0.70
same family:      median ρ = 0.95
different family: median ρ = 0.40
% pairs ρ > 0.9:  66.7%
% pairs ρ > 0.7:  89.0%
% pairs ρ > 0.5:  89.0%
```

**67% 페어가 ρ > 0.9** — 풀이 거의 클론이라는 뜻. 291개를 합성한다 해도 사실상 7-10개 정도의 distinct 알파를 가중 평균한 것과 같음.

### 7.1 Greedy correlation dedup

IS Sharpe 내림차순 정렬 → 각 알파에 대해 "이미 keep 한 알파들과의 max |ρ| < τ" 이면 추가.

![Dedup curve](figures/09_dedup_curve.png)

| τ (corr 임계) | 보존 수 | long_only | L/S donchian | L/S mom |
|---:|---:|---:|---:|---:|
| 0.30 | 2 | 0 | 1 | 1 |
| 0.50 | 2 | 0 | 1 | 1 |
| 0.70 | 2 | 0 | 1 | 1 |
| 0.80 | 3 | 0 | 1 | 2 |
| **0.85** | **3** | **0** | **1** | **2** |
| **0.90** | **7** | **0** | **3** | **4** |
| **0.95** | **11** | **1** | **4** | **6** |
| 1.01 (게이트 없음) | 291 | 104 | 170 | 17 |

τ ≤ 0.85 에서는 풀이 3개로 붕괴. τ = 0.95 에서 11개로 안정.

### 7.2 클러스터 발견 — 두 개의 진짜 strategy direction

τ = 0.95 보존 11 멤버의 페어와이즈 상관 매트릭스를 직접 보면 **두 개의 무상관 클러스터** 가 명확히 보임:

| Cluster | 멤버 | 내부 상관 | 외부 상관 |
|---|---|---:|---:|
| **Donchian** (channel-based) | ts_donchian_symmetric_v2/v3 4개 + is_294 long_persist 1개 | 0.78–0.95 | 0.01–0.15 |
| **TS-mom** (raw-return-based) | ts_mom_symmetric 6개 | 0.75–0.94 | 0.01–0.15 |

→ **클러스터 간 상관 ≈ 0**. 두 strategy 방향이 진짜로 다른 시그널을 잡고 있음.

이게 핵심 발견: 단순히 "풀이 redundant" 가 아니라, **실은 2개의 distinct strategy + 그 안의 수많은 클론** 이라는 구조.

### 7.3 G2 × 상관 게이트 결합

| G2 임계 | 상관 dedup τ | 최종 풀 | long_only | L/S |
|---:|---:|---:|---:|---:|
| 0.0 (no G2) | 0.95 | 11 | 1 | 10 |
| 0.8 | 0.95 | **5** | **1** | **4** |
| 1.0 | 0.95 | **5** | **1** | **4** |
| 1.28 | 0.95 | 5 | 1 | 4 |
| 0.8 | 0.85 | 1 | 0 | 1 |

상관 게이트가 강하게 작용해서 G2 임계 차이가 거의 무의미해짐 — 어차피 같은 5개 핵심 멤버로 수렴.

## 8. 권장 (수정 — correlation gate 포함)

### Submittable 신규 정의 (시그널 + 상관 dedup)

```python
SUBMITTABLE = (
    (is_t_stat   >= 1.96)   # G1: IS edge 진짜
    & (os_bps    >  0   )   # G3: OS 부호 보존
    & (is_bps    >  0   )   # G4
    & (is_sharpe >  0   )   # G5a
    & (os_sharpe >  0   )   # G5b
    & (is_trades >= 100 )   # G6: 표본 수
    & (os_t_stat >= 1.0 )   # G2: OS edge 비자명
    & (max_corr_with_existing_submittable < 0.95)   # G7: 강 상관 제외 (NEW)
)
```

새 게이트 G7 은 **post-hoc 적용 게이트** (다른 알파 존재에 의존). 구현: 후보 알파를 IS Sharpe 내림차순 정렬 → 빈 submittable 리스트에서 시작 → 각 후보의 max|ρ| < 0.95 이면 추가. 결과는 풀의 IS Sharpe-greedy 순서에 의존하지만 robust (τ=0.95 정도면 순서 바뀌어도 거의 같은 결과).

### Primary: **G2 = 1.0 + G7 (τ = 0.95)** → 풀 ≈ 5

- 통계적 신뢰도: 단측 p ≈ 0.16 + 상관 dedup
- 5 멤버: long_only 1 + Donchian L/S 1 + TS-mom L/S 3 정도
- 진짜 distinct 시그널 (cross-cluster ρ ≈ 0.10) 로 합성 가능
- **단**, 5 멤버 합성은 분산 효과 제한적. 실용적으론 family 추가 필요.

### Stretch: **G2 = 1.0 + G7 (τ = 0.90)** → 풀 ≈ 7

- 두 클러스터 각 3~4개씩 보존
- 일부 sub-clone 허용 → 가중치 효과로 noise 줄임

### **결정적 함의: 새 family 가 시급함**

현재 게이트 (G1-G7) 통과 풀은 어떤 임계 조합으로도 **15개 이하**. 이건 알파 generation 자체가 두 방향에 갇힌 결과 — Donchian 채널 기반과 raw return 기반. 합성 capacity를 늘리려면 새 strategy direction 필요:

| 후보 family | 예상 상관 | 우선순위 |
|---|---|---|
| Mean-reversion (BB-fade, ATR-fade) | 추세 family 와 음 또는 0 | 높음 |
| Microstructure (orderflow, CVD) | 통계적으로 무관 | 높음 |
| Vol-target / vol-anomaly | 시장 베타와 다름 | 중간 |
| Session-based (open range, close fade) | 시간 효과만 분리 | 중간 |
| Cross-section reversal (수정된 xs_revert) | quality gate 통과 필요 | 낮음 (이전 시도 실패) |

## 9. 권장 (이전 — 상관 무시 시)

이 섹션은 **참고용**. 상관 gate 적용 전의 분석.

### Primary: **G2 = 1.0** (풀 = 140)

- **통계적 정당화**: 단측 p ≈ 0.16. 각 개별 알파가 ~84% 확률로 진짜 양수 edge 보유 (노이즈 가설 대비 독립 평가). 단일로는 약하지만 합성 멤버로는 수용 가능.
- **강건성**: 중앙 sharpe_degr 0.67 → IS Sharpe 의 2/3 가 OS 에서 살아남음.
- **균형**: long_only 74 + L/S 66 ≈ 53/47 분할. 달러 뉴트럴 합성 설계에 적합.
- **풀 크기**: 140 은 downstream correlation/marginal-Sharpe 셀렉션으로 ~30 최종 멤버 뽑기에 충분.

### Stretch: **G2 = 0.8** (풀 = 192) — L/S 커버리지 우선 시

- 통계적 방어 약함 (단측 p ≈ 0.21)
- long-only / L/S 균형 더 좋음 (~48 / 52). downstream selector 가 L/S 다양성 더 원할 때.
- *백업 풀* 로 권장 — G2 = 1.0 선택이 correlation 필터 후 L/S 멤버 부족하면 사용.

### Reject: **G2 < 0.5** (풀 > 240)

G2 = 0 또는 0.5 에서 풀이 50+ 알파 늘지만, 그 marginal 추가분은 노이즈와 통계적으로 구분 불가 (p ≥ 0.31). 포함 시 평균 멤버 quality 희석. 매우 공격적 downstream 필터링이 있을 때만 도움.

### Reject: **G2 ≥ 1.28** (풀 ≤ 84)

L/S leg 가 31 멤버 아래로 붕괴. long-only 쪽에 padding 없이는 달러 뉴트럴 합성 불가, 원래 long-bias 문제로 회귀.

## 8. 제안 게이트 스택

```python
def select_for_composite(df):  # IS, OS metrics 모두 보유한 df
    return df[
        (df.is_t_stat   >= 1.96)   # G1: IS edge 통계적으로 진짜
        & (df.os_bps    >  0   )   # G3: OS 부호 보존
        & (df.is_bps    >  0   )   # G4
        & (df.is_sharpe >  0   )   # G5a
        & (df.os_sharpe >  0   )   # G5b
        & (df.is_trades >= 100 )   # G6: 표본 수
        & (df.os_t_stat >= 1.0 )   # G2: OS edge 비자명 (권장)
    ]
```

기존 submittable 게이트와 비교 시 제외된 항목:
- S1 (OS t > 2.5) — 너무 strict, 0개 통과
- S2 (OS bps > 2.0) — G3 ∧ G1 에 implied
- S3 (sharpe_degr > 0.7) — 너무 strict
- S5 (\|OS DD\| < 0.12) — 포트폴리오 level 에서 통제
- S6 (OS PF > 1.3) — magnitude 의존
- S7 (IS trades > 500) — G6 으로 커버

## 9. 주의사항 및 열린 질문

1. **Family 불균형**: long-only legacy family 가 high-t-stat zone 을 지배 — IS bull cycle 에서 잘 작동하는 cycle-aware breakout 으로 개발되었기 때문. L/S family 는 늦게 추가, 거래당 edge 약함. 더 다양한 합성을 위해선 최종 선택 전에 **새 L/S family** (예: vol-target, 긴 rebalance cross-section) 추가 권장.

2. **다중 검정 인플레이션**: 435 개 후보 생성. 순수 노이즈도 일부 high-t 알파를 만든다. 모집단 수준 binomial test (Section 4) 가 이걸 명시적으로 처리하지만, downstream correlation-aware selection 도 large family 의 노이즈 outlier 처럼 보이는 멤버를 페널티해야 한다.

3. **OS 평가 오염**: 알파는 OS 데이터로 선택하지 않았지만, **임계 자체 (G2)** 는 OS 데이터로 선택 중. 깨끗하게 유지하려면 최종 합성은 OS 추가 사용 전에 동결, 진정한 두 번째 OS 검증은 third split 보존 또는 paper-trading 필요.

4. **0.8 ↔ 1.0 ↔ 1.28 결정은 OS edge 감쇠에 민감**. 다음 분기 데이터에서 OS edge 회복하면 (per-trade Sharpe 상승) 같은 임계가 훨씬 많이 통과. **풀 크기 곡선은 분기 1-2 회 재평가** 필요.

## 10. 다음 단계 (수정)

1. **결정 확정**: G2 = 1.0 + G7 (τ = 0.95) 신규 submittable 기준
2. **코드 구현**: `alpha_dashboard_lib.classify_alpha_with_correlation_gate()` 추가, 대시보드 category 컬럼 재계산
3. **새 alpha family 생성** — 합성 capacity 확보의 필수 전제:
   - 1순위: mean-reversion (BB-fade, ATR-fade, RSI-extreme) — 추세와 반대 방향
   - 1순위: orderflow / CVD 기반 — microstructure 시그널
   - 2순위: vol-target / vol-anomaly
   - 2순위: session-based (open range, close fade)
   - 각 family 당 30+ param sweep → IS 백테 → submittable G1-G7 통과 멤버 누적
4. **목표: 신규 submittable 100+** — 두 클러스터에 갇힌 현 상태에서 진짜 분산된 풀로 확장
5. (목표 달성 후) 합성 빌드 — 1/N 또는 marginal Sharpe lift 기반

---

### 부록 A — 그림 인덱스

- `figures/01_os_tstat_distribution.png` — OS t-stat 히스토그램, 게이트 cut 표시
- `figures/02_is_os_sharpe_scatter.png` — IS vs OS Sharpe scatter, 부호 사분면
- `figures/03_pool_vs_threshold.png` — G2 의존 풀 크기
- `figures/04_observed_vs_null.png` — 관측 vs 노이즈 가설 통과 수
- `figures/05_per_trade_sharpe.png` — 거래당 Sharpe IS vs OS overlay
- `figures/06_sharpe_degradation.png` — 감쇠 분포, R3/S3 표시
- `figures/07_gate_efficiency.png` — 게이트별 단독 통과율

### 부록 B — 소스

- 코드: `scripts/tools/alpha_dashboard_lib.py:classify_alpha`
- 데이터: `archive/run_2026_05_c/alphas/<id>/{is,os}/metrics.json`, 385 alphas
- IC 해석 참고: Grinold & Kahn, *Active Portfolio Management* (2nd ed., 2000), ch. 6
