#!/usr/bin/env python3
"""
Semantic Enrichment Script - Claude Code 직접 분석 결과 반영

이 스크립트는 Claude Code (Opus 4.5)가 직접 전략 코드와 memory.md를 분석한 결과를
strategies_ontology.json에 _semantic 필드로 추가합니다.

Usage:
    python scripts/add_semantic_fields.py
"""

import json
from pathlib import Path
from datetime import datetime

# Claude Code가 직접 분석한 시멘틱 결과
SEMANTIC_ANALYSIS = {
    "bb_squeeze": {
        "core_logic": "BB bandwidth percentile로 squeeze 감지 → 상단 돌파 시 LONG, 하단 돌파 시 SHORT 진입. 4분봉 기반으로 5분봉 트레이더보다 1분 선점.",
        "implicit_assumptions": [
            "변동성은 mean-reverting 특성을 가짐",
            "4분봉이 5분봉보다 1분 먼저 squeeze 감지 가능",
            "Squeeze 후 breakout 방향으로 추세 지속",
            "Long-only가 Short 포함보다 안정적"
        ],
        "failure_nuance": "Iteration 1-2에서 PF 3.57이었으나 Total Return 0.37%에 불과. 원인은 position sizing (quantity=0.01). Iteration 3에서 quantity=0.5로 50배 증가하여 해결.",
        "similar_patterns": ["volatility_breakout", "squeeze_play", "keltner_channel_breakout", "expansion_after_contraction"],
        "hidden_risks": [
            "IS-OS degradation 심함 (PF 3.57→1.27, WR 56%→32%)",
            "Short 포함 시 성과 하락 (use_short=false가 최적)",
            "Squeeze percentile 파라미터에 민감",
            "Market regime에 따라 성과 변동 큼"
        ],
        "state_machine": "WARMUP(100 bars) → IDLE → HOLDING_LONG/SHORT → COOLDOWN(15 bars)",
        "key_parameters": {
            "bb_period": 20,
            "bb_std_mult": 2.0,
            "squeeze_percentile": 10,
            "bandwidth_lookback": 100,
            "take_profit_pct": 0.6,
            "stop_loss_pct": 0.3
        },
        "code_quality": "Clean implementation with proper state machine. Uses deque for rolling calculations."
    },

    "vpin_contrarian": {
        "core_logic": "VPIN > threshold (informed trading detected) + RSI 확인 → OFI 방향 반대로 fade 진입. Mean reversion 가설.",
        "implicit_assumptions": [
            "VPIN spike = 정보거래자 진입 = 곧 가격 조정",
            "RSI oversold/overbought와 VPIN spike 조합이 반전 신호",
            "OFI 방향의 반대가 수익 방향"
        ],
        "failure_nuance": "6번의 iteration 동안 실패. 핵심 문제: Win Rate 58.8%이나 Avg Win($0.73) < Avg Loss($1.00)로 Risk-Reward Inversion 발생. PF 0.94로 fee까지 고려하면 적자.",
        "similar_patterns": ["mean_reversion", "ofi_fade", "informed_trading_detection", "toxicity_fade"],
        "hidden_risks": [
            "VPIN threshold 0.7은 너무 낮아 noise 포함",
            "RSI 신호와 VPIN 신호 timing mismatch",
            "Fee-dominated loss 패턴 (WR 높으나 손실)",
            "가설 자체가 invalidated - VPIN spike가 반전이 아닌 추세 지속 신호일 수 있음"
        ],
        "state_machine": "WARMUP(50 buckets) → IDLE → HOLDING_LONG/SHORT → COOLDOWN(10 bars)",
        "key_parameters": {
            "vpin_threshold": 0.7,
            "vpin_bucket_size": 1000,
            "rsi_period": 14,
            "rsi_oversold": 30,
            "rsi_overbought": 70
        },
        "lessons_learned": [
            "L001: Risk-Reward Inversion - WR만 보면 안됨",
            "VPIN contrarian 가설 자체 검증 필요",
            "OFI 방향 fade가 항상 정답은 아님"
        ],
        "code_quality": "Complex implementation with volume bucket management. VPIN calculation follows academic definition."
    },

    "dual_vpin": {
        "core_logic": "Fast VPIN(50 buckets, 단기 독성)과 Slow VPIN(200 buckets, 구조적 정보) 비교. Fast > Slow + OFI 방향 일치 시 breakout 진입.",
        "implicit_assumptions": [
            "Fast VPIN - Slow VPIN divergence가 정보 비대칭 신호",
            "두 VPIN이 모두 높을 때 volatility 폭발",
            "OFI 방향이 breakout 방향 예측"
        ],
        "failure_nuance": "5 iterations 후 rejected. Dual VPIN 개념은 valid하나 parameter 조합 찾기 어려움. IS에서도 PF < 1.3 달성 못함.",
        "similar_patterns": ["multi_timeframe_analysis", "volatility_regime", "information_asymmetry"],
        "hidden_risks": [
            "Fast/Slow bucket size 조합이 exponential search space",
            "VPIN calculation overhead가 큼",
            "CDF 변환 없이 raw VPIN 사용 시 정규화 문제"
        ],
        "state_machine": "WARMUP(200 buckets) → IDLE → HOLDING_LONG/SHORT → COOLDOWN",
        "key_parameters": {
            "fast_bucket_size": 500,
            "slow_bucket_size": 2000,
            "fast_bucket_count": 50,
            "slow_bucket_count": 200,
            "vpin_threshold": 0.6
        },
        "evolution": "dual_vpin → dual_vpin_cdf (CDF 추가) → dual_vpin_rsi (RSI 필터 추가)",
        "code_quality": "Well-structured with separate VPINCalculator class. Trailing stop implementation included."
    },

    "ofi_vpin_explosion": {
        "core_logic": "OFI extreme (|normalized_ofi| > 2σ) + VPIN spike (> 0.7) 감지 시 OFI 반대 방향 fade. Mean reversion 가설.",
        "implicit_assumptions": [
            "Extreme OFI는 exhaustion 신호",
            "VPIN spike와 OFI extreme 동시 발생 = 반전 임박",
            "Fade 전략이 momentum보다 edge 있음"
        ],
        "failure_nuance": "V3까지 iteration. OFI-VPIN 조합 자체는 신호 생성하나 timing이 문제. Entry 직후 adverse move가 잦음.",
        "similar_patterns": ["exhaustion_fade", "vpin_contrarian", "ofi_mean_reversion"],
        "hidden_risks": [
            "OFI normalization 방식에 따라 결과 크게 달라짐",
            "VPIN threshold와 OFI threshold 동시 최적화 어려움",
            "Fade 진입 후 추세 지속 시 큰 손실"
        ],
        "state_machine": "WARMUP(100 bars) → IDLE → HOLDING_LONG/SHORT → COOLDOWN",
        "key_parameters": {
            "ofi_lookback": 100,
            "ofi_threshold": 2.0,
            "vpin_threshold": 0.7,
            "take_profit_pct": 0.3,
            "stop_loss_pct": 0.2
        },
        "versions": ["V1 (basic)", "V2 (parameter tuning)", "V3 (OFI normalization)", "V4-V7 (continued iterations)"],
        "code_quality": "Clean with configurable parameters. Uses numpy for OFI normalization."
    },

    "vpin_breakout_filter": {
        "core_logic": "LOW VPIN CDF(<0.3) + Breakout 감지 → 진입. 역발상: 낮은 VPIN = MM이 flow 흡수 안함 = clean breakout.",
        "implicit_assumptions": [
            "HIGH VPIN = MM absorption zone = 반전 가능성 높음",
            "LOW VPIN = MM이 비켜섬 = breakout 지속",
            "v1 (HIGH VPIN entry)이 16.4% WR로 실패 → 가설 반전"
        ],
        "failure_nuance": "v1에서 HIGH VPIN entry가 실패. MM이 fade하고 있었음. v2에서 가설 반전하여 LOW VPIN entry로 수정.",
        "similar_patterns": ["breakout_momentum", "mm_withdrawal_detection", "clean_breakout"],
        "hidden_risks": [
            "LOW VPIN threshold (0.3)가 너무 restrictive하면 signal 부족",
            "MM absorption filter (>0.6)와 entry filter (<0.3) 사이의 gap이 넓음",
            "Breakout false positive 시 손실"
        ],
        "state_machine": "WARMUP(200 bars) → IDLE → HOLDING_LONG/SHORT → COOLDOWN(10 bars)",
        "key_parameters": {
            "lookback_bars": 20,
            "vpin_entry_cdf": 0.3,
            "vpin_ignore_cdf": 0.6,
            "vpin_exit_cdf": 0.7,
            "stop_loss_pct": 0.8,
            "take_profit_pct": 1.2
        },
        "market_microstructure": "BVC (Bulk Volume Classification)로 buy/sell volume 분류. Normal CDF 기반.",
        "code_quality": "Well-documented with clear v1→v2 hypothesis evolution. Proper MM absorption filter."
    },

    "fast_vpin_scalping": {
        "core_logic": "Fast VPIN CDF > 90% (극단적 독성) + OFI 방향 일치 + spread proxy 확인 → OFI 방향으로 scalping.",
        "implicit_assumptions": [
            "VPIN CDF > 90 = informed traders aggressive",
            "MM withdrawal creates temporary price impact amplification",
            "Exit quickly before mean reversion"
        ],
        "failure_nuance": "Scalping 특성상 tight SL(0.25%)과 short hold(15 bars). VPIN normalization (CDF < 70) 시 exit.",
        "similar_patterns": ["toxicity_momentum", "informed_flow_piggybacking", "mm_withdrawal_scalping"],
        "hidden_risks": [
            "OFI reversal exit가 너무 빠를 수 있음",
            "Spread proxy threshold (10bps)가 시장 상황에 따라 부적절",
            "Tight SL (0.25%)로 인한 높은 stop-out rate"
        ],
        "state_machine": "WARMUP(200 bars) → IDLE → HOLDING_LONG/SHORT → COOLDOWN(5 bars)",
        "key_parameters": {
            "fast_vpin_buckets": 30,
            "vpin_entry_percentile": 90,
            "vpin_exit_percentile": 70,
            "ofi_threshold": 0.3,
            "spread_proxy_threshold_bps": 10,
            "stop_loss_pct": 0.25,
            "take_profit_pct": 0.5
        },
        "differentiators_from_dual_vpin": [
            "Shorter VPIN window (30 vs 50)",
            "Higher entry threshold (90th vs 70th percentile)",
            "OFI filter for direction",
            "Spread proxy filter for MM withdrawal",
            "Tighter stops (0.25% vs 0.5%)"
        ],
        "code_quality": "Clean scalping implementation. OFI calculated from BVC. Spread proxy as MM withdrawal indicator."
    },

    "absorption": {
        "core_logic": "Absorption bar (|imbalance| > 0.35 + body_ratio < 0.34) 감지 → 다음 봉에서 confirmation breakout 시 진입.",
        "implicit_assumptions": [
            "Doji + high imbalance = institutional accumulation",
            "가격이 안 움직였지만 volume imbalance = 큰손이 흡수 중",
            "Confirmation bar breakout이 방향 확정"
        ],
        "failure_nuance": "Absorption 감지는 잘 되나 confirmation 조건이 까다로움. False absorption도 많음.",
        "similar_patterns": ["doji_breakout", "institutional_accumulation", "absorption_exhaustion"],
        "hidden_risks": [
            "body_ratio threshold (0.34)가 시장별로 다를 수 있음",
            "Confirmation breakout이 fakeout일 가능성",
            "Max hold (20 bars)가 너무 길거나 짧을 수 있음"
        ],
        "state_machine": "IDLE → ABSORPTION_DETECTED → HOLDING_LONG/SHORT → COOLDOWN",
        "key_parameters": {
            "imbalance_threshold": 0.35,
            "body_ratio_threshold": 0.34,
            "stop_loss_pct": 0.5,
            "take_profit_pct": 1.0,
            "reversal_threshold": 0.30,
            "max_hold_bars": 20
        },
        "order_type": "LIMIT (maker fee 0.02%)",
        "code_quality": "Uses dataclass for CandleData. Clean state machine with ABSORPTION_DETECTED intermediate state."
    },

    # === Batch 2: Additional strategies analyzed ===

    "breakout_frontrun": {
        "core_logic": "4분봉에서 high/low breakout 감지 → 5분봉 트레이더보다 1분 먼저 진입. Momentum following.",
        "implicit_assumptions": [
            "4분봉이 5분봉보다 1분 먼저 breakout 감지",
            "Breakout 후 momentum 지속",
            "Early entry = better fill price"
        ],
        "failure_nuance": "Frontrun 가설은 valid하나 false breakout이 많음. Filter 추가 필요.",
        "similar_patterns": ["breakout_momentum", "early_entry", "timeframe_arbitrage"],
        "hidden_risks": [
            "False breakout으로 인한 whipsaw",
            "Late entry 시 이미 움직임 끝",
            "4분봉과 5분봉의 phase 차이가 일정하지 않음"
        ],
        "state_machine": "WARMUP → IDLE → HOLDING_LONG/SHORT → COOLDOWN",
        "key_parameters": {
            "lookback_bars": 20,
            "breakout_threshold_pct": 0.1,
            "stop_loss_pct": 0.3,
            "take_profit_pct": 0.5
        },
        "code_quality": "Standard tick strategy implementation with rolling high/low tracking."
    },

    "dual_vpin_cdf": {
        "core_logic": "Fast/Slow VPIN을 CDF로 정규화 후 divergence 감지. Fast CDF > Slow CDF + threshold → breakout 진입.",
        "implicit_assumptions": [
            "CDF 정규화로 VPIN 값 비교 용이",
            "Fast VPIN이 Slow VPIN보다 높으면 단기 정보 유입",
            "Divergence가 breakout 예고"
        ],
        "failure_nuance": "dual_vpin에서 CDF 변환 추가. 정규화는 도움이 되나 여전히 parameter 조합 문제.",
        "similar_patterns": ["dual_vpin", "vpin_divergence", "cdf_normalization"],
        "hidden_risks": [
            "CDF lookback 기간 선택이 어려움",
            "Historical CDF가 regime 변화에 적응 못함",
            "Fast/Slow CDF threshold 동시 최적화 어려움"
        ],
        "evolution_from": "dual_vpin",
        "key_parameters": {
            "fast_cdf_lookback": 200,
            "slow_cdf_lookback": 500,
            "cdf_divergence_threshold": 0.2
        },
        "code_quality": "Extends dual_vpin with CDF calculation. scipy.stats for normal CDF."
    },

    "dual_vpin_rsi": {
        "core_logic": "Dual VPIN + RSI 필터. VPIN divergence + RSI oversold/overbought 조합으로 진입.",
        "implicit_assumptions": [
            "RSI가 추가적인 confirmation 제공",
            "VPIN과 RSI 조합이 단일 지표보다 정확",
            "Oversold + VPIN divergence = stronger signal"
        ],
        "failure_nuance": "RSI 필터 추가로 신호 품질 향상 시도. 하지만 신호 빈도 감소로 trade count 부족.",
        "similar_patterns": ["dual_vpin", "rsi_filter", "multi_indicator"],
        "hidden_risks": [
            "RSI와 VPIN 신호 timing mismatch",
            "Filter 추가로 신호 감소 → 통계적 유의성 부족",
            "RSI period와 VPIN bucket size 조합 최적화 어려움"
        ],
        "evolution_from": "dual_vpin_cdf",
        "key_parameters": {
            "rsi_period": 14,
            "rsi_oversold": 30,
            "rsi_overbought": 70,
            "vpin_divergence_threshold": 0.2
        },
        "code_quality": "Clean RSI implementation added to dual_vpin_cdf base."
    },

    "footprint_pseudoobi": {
        "core_logic": "Footprint chart 스타일 volume profile 분석. Tick 데이터로 pseudo-OBI 계산하여 imbalance 감지.",
        "implicit_assumptions": [
            "Tick-level volume 분포가 institutional activity 노출",
            "Pseudo-OBI가 실제 orderbook imbalance proxy",
            "Imbalance 방향으로 가격 움직임"
        ],
        "failure_nuance": "Orderbook 데이터 없이 tick으로 approximation. 정확도 한계.",
        "similar_patterns": ["volume_profile", "orderbook_imbalance", "footprint_analysis"],
        "hidden_risks": [
            "Tick 데이터만으로는 실제 depth 정보 부족",
            "Pseudo-OBI가 실제 OBI와 괴리",
            "계산 overhead 높음"
        ],
        "state_machine": "WARMUP → IDLE → HOLDING_LONG/SHORT → COOLDOWN",
        "key_parameters": {
            "price_bucket_size": 10,
            "volume_lookback": 50,
            "imbalance_threshold": 0.6
        },
        "code_quality": "Complex volume bucketing implementation. Memory-intensive."
    },

    "funding_divergence": {
        "core_logic": "Funding rate와 가격 방향 divergence 감지. Positive funding + price down = LONG (carry + reversal).",
        "implicit_assumptions": [
            "Funding rate는 market positioning proxy",
            "Divergence는 mean reversion 신호",
            "Carry cost가 positioning에 영향"
        ],
        "failure_nuance": "Funding rate 데이터 8시간마다만 업데이트. Tick 전략과 timeframe mismatch.",
        "similar_patterns": ["carry_trade", "funding_arbitrage", "sentiment_divergence"],
        "hidden_risks": [
            "Funding 업데이트 주기가 너무 느림",
            "Extreme funding 상황에서 역방향 지속",
            "Funding rate 자체가 lagging indicator"
        ],
        "key_parameters": {
            "funding_threshold": 0.0003,
            "divergence_lookback": 20,
            "stop_loss_pct": 0.5
        },
        "code_quality": "Requires FundingLoader integration. Clean but limited by data frequency."
    },

    "iceberg_breakout": {
        "core_logic": "V3: Iceberg 감지 (high volume + compressed range) 후 breakout FADE. Mean reversion 가설.",
        "implicit_assumptions": [
            "Iceberg order = large hidden order absorbing flow",
            "V2 follow breakout 실패 (35% WR) → V3 fade breakout",
            "Breakout 후 compression range로 회귀"
        ],
        "failure_nuance": "V2에서 breakout follow가 35% WR로 실패. V3에서 fade로 가설 반전.",
        "similar_patterns": ["absorption_fade", "compression_breakout", "iceberg_detection"],
        "hidden_risks": [
            "Iceberg 감지 false positive",
            "Fade 진입 후 진짜 breakout 지속 시 큰 손실",
            "Symmetric stop/target (0.12%) 너무 tight"
        ],
        "state_machine": "WARMUP → IDLE → ICEBERG_DETECTED → HOLDING_LONG/SHORT → COOLDOWN",
        "key_parameters": {
            "detection_window": 4,
            "volume_multiplier": 1.5,
            "range_threshold": 0.0015,
            "stop_loss_pct": 0.12,
            "take_profit_pct": 0.12
        },
        "evolution": "V1 (basic) → V2 (follow breakout, failed) → V3 (fade breakout)",
        "code_quality": "Clean state machine with ICEBERG_DETECTED intermediate state. Uses LIMIT orders."
    },

    "ofi_momentum": {
        "core_logic": "OFI (Order Flow Imbalance) percentile 기반. 극단적 OFI 감지 시 FADE (contrarian).",
        "implicit_assumptions": [
            "Extreme OFI = exhaustion signal",
            "High OFI (90th percentile) → fade selling",
            "Low OFI (10th percentile) → fade buying"
        ],
        "failure_nuance": "원래 momentum 전략이 18.3% WR로 실패 → contrarian으로 전환. 이름과 로직 불일치.",
        "similar_patterns": ["ofi_contrarian", "exhaustion_fade", "flow_reversal"],
        "hidden_risks": [
            "OFI percentile lookback 기간 선택 중요",
            "Extreme OFI가 반전 아닌 acceleration일 수 있음",
            "Time exit (3 bars)이 너무 짧을 수 있음"
        ],
        "state_machine": "WARMUP(100 bars) → IDLE → HOLDING_LONG/SHORT → COOLDOWN(5 bars)",
        "key_parameters": {
            "ofi_lookback": 4,
            "percentile_threshold": 90,
            "percentile_lookback": 200,
            "stop_loss_pct": 1.0,
            "take_profit_pct": 0.6,
            "time_exit_bars": 3
        },
        "name_vs_logic": "클래스명 OfiContrarianStrategy와 파일명 ofi_momentum.py 불일치 - backward compatibility alias 존재",
        "code_quality": "Clean implementation with proper percentile calculation. LIMIT orders for maker fee."
    },

    "stacked_imbalance": {
        "core_logic": "N개 연속 high-imbalance bar (institutional sweep) 감지 + breakout confirmation → momentum entry.",
        "implicit_assumptions": [
            "Stacked imbalance = algorithmic sweeping",
            "연속 high-imbalance = aggressive informed trading",
            "Breakout filter로 price impact 확인"
        ],
        "failure_nuance": "Stacked imbalance 개념은 valid하나 consecutive count와 threshold 조합 어려움.",
        "similar_patterns": ["sweep_detection", "institutional_flow", "consecutive_imbalance"],
        "hidden_risks": [
            "min_consecutive가 높으면 signal 희소",
            "imbalance_threshold (0.5)가 market regime에 따라 부적절",
            "Reversal threshold (0.3)로 인한 early exit"
        ],
        "state_machine": "WARMUP → IDLE → HOLDING_LONG/SHORT → COOLDOWN",
        "key_parameters": {
            "imbalance_threshold": 0.5,
            "min_consecutive": 2,
            "lookback_bars": 5,
            "stop_loss_pct": 0.5,
            "take_profit_pct": 1.0,
            "reversal_threshold": 0.3,
            "max_hold_bars": 10
        },
        "code_quality": "Uses hash-based bar detection. Clean imbalance history tracking."
    },

    "td9": {
        "core_logic": "TD Sequential 9-count 완성 시 mean reversion 진입. 10분봉 기반 내부 aggregation.",
        "implicit_assumptions": [
            "TD9 = trend exhaustion 신호",
            "Green 9 → SHORT (uptrend 고갈)",
            "Red 9 → LONG (downtrend 고갈)"
        ],
        "failure_nuance": "V1-V4 volume imbalance filter 시도 후 plateau. V5에서 RSI filter로 전환.",
        "similar_patterns": ["td_sequential", "count_based", "exhaustion_count"],
        "hidden_risks": [
            "TD9 자체가 lagging indicator",
            "RSI와 TD9 timing mismatch",
            "10분봉 내부 aggregation으로 tick data 장점 상실"
        ],
        "state_machine": "WARMUP(14 bars) → IDLE → HOLDING_LONG/SHORT → COOLDOWN(1 bar)",
        "key_parameters": {
            "td9_lookback": 4,
            "td9_count": 9,
            "stop_loss_pct": 0.2,
            "take_profit_pct": 0.4,
            "max_hold_bars": 5,
            "rsi_period": 14,
            "rsi_overbought": 70,
            "rsi_oversold": 30
        },
        "evolution": "V1 (basic) → V2-V4 (volume imbalance filter) → V5 (RSI filter, final)",
        "code_quality": "Clean TD9 counting logic. RSI calculation implemented inline."
    },

    "volume_climax": {
        "core_logic": "Volume climax (5x avg) + reversal wick 감지 → FADE. V5에서 regime filter 추가.",
        "implicit_assumptions": [
            "Volume climax = exhaustion",
            "Reversal wick (>50% body) = rejection",
            "Bullish climax만 fade (SHORT-only)"
        ],
        "failure_nuance": "EDA 결과 SHORT-only가 유효 (58.8% WR). LONG은 35.5% WR. V5에서 MA deviation으로 regime filter.",
        "similar_patterns": ["climax_fade", "exhaustion_reversal", "wick_rejection"],
        "hidden_risks": [
            "Volume multiplier (5x)가 market에 따라 부적절",
            "Bull trending market에서 SHORT fade 위험",
            "MA deviation filter가 너무 restrictive"
        ],
        "state_machine": "WARMUP(50 bars) → IDLE → HOLDING_SHORT → COOLDOWN(2 bars)",
        "key_parameters": {
            "volume_lookback": 20,
            "volume_multiplier": 5.0,
            "wick_ratio": 0.5,
            "min_body_pct": 0.05,
            "ma_period": 50,
            "max_ma_deviation": 0.0075,
            "stop_buffer_pct": 0.1,
            "take_profit_ratio": 1.0
        },
        "direction_filter": "short_only (default)",
        "evolution": "V1-V3 (bidirectional) → V4 (short-only) → V5 (regime filter)",
        "code_quality": "Clean regime filter implementation. Climax-based exit levels."
    },

    "vwap_reversion": {
        "core_logic": "VWAP deviation > 2σ 감지 시 mean reversion 진입. V2에서 MA50 regime filter 추가.",
        "implicit_assumptions": [
            "기관 알고리즘은 VWAP 벤치마크 추종",
            "VWAP에서 크게 벗어나면 회귀 압력",
            "Regime filter로 trending market 제외"
        ],
        "failure_nuance": "V1에서 trending market에서 손실. V2에서 MA50 filter: LONG은 bullish regime만, SHORT은 bearish regime만.",
        "similar_patterns": ["mean_reversion", "vwap_bands", "institutional_benchmark"],
        "hidden_risks": [
            "Intraday VWAP reset으로 overnight gap 문제",
            "deviation std 계산 기간 선택 중요",
            "Regime filter가 오히려 좋은 기회 필터링"
        ],
        "state_machine": "WARMUP(50 bars) → IDLE → HOLDING_LONG/SHORT → COOLDOWN(3 bars)",
        "key_parameters": {
            "ma_period": 50,
            "vwap_sigma": 2.0,
            "dev_lookback": 20,
            "stop_loss_pct": 0.5,
            "max_hold_bars": 5
        },
        "evolution": "V1 (basic) → V2 (MA50 regime filter)",
        "code_quality": "Clean VWAP calculation with daily reset. MA regime filter integrated."
    },

    "vpin_ofi_scalping": {
        "core_logic": "VPIN CDF > 90 (exhaustion) + recent price move > 0.5% → FADE. Price move 방향 반대로 진입.",
        "implicit_assumptions": [
            "VPIN > 90 = informed trading completed",
            "Price move + high VPIN = information priced in",
            "Late chasers create mean reversion opportunity"
        ],
        "failure_nuance": "V4에서 0.3% price move threshold → V5에서 0.5%로 상향 (signal quality 개선).",
        "similar_patterns": ["exhaustion_fade", "vpin_timing", "price_move_filter"],
        "hidden_risks": [
            "Trailing stop trigger (0.2%)가 너무 tight",
            "VPIN normalization exit (CDF < 70)이 premature",
            "Price move threshold가 regime에 따라 다를 수 있음"
        ],
        "state_machine": "WARMUP(200 bars) → IDLE → HOLDING_LONG/SHORT → COOLDOWN(5 bars)",
        "key_parameters": {
            "fast_vpin_buckets": 30,
            "vpin_entry_percentile": 90,
            "vpin_exit_percentile": 70,
            "price_move_lookback": 5,
            "price_move_threshold": 0.005,
            "stop_loss_pct": 0.30,
            "take_profit_pct": 0.50,
            "trailing_trigger_pct": 0.20,
            "min_hold_bars": 2,
            "max_hold_bars": 15
        },
        "evolution": "V1-V3 → V4 (0.3% threshold) → V5 (0.5% threshold, faster exits)",
        "code_quality": "Clean BVC-based VPIN calculation. Trailing stop implementation."
    },

    "vpin_rsi_mean_reversion": {
        "core_logic": "Range Regime (Safe Zone + ADX < 25) + BB touch → mean reversion 진입. VPIN spike 시 emergency exit.",
        "implicit_assumptions": [
            "Low VPIN = safe zone (no informed trading)",
            "Low ADX = no trend (oscillatory)",
            "BB touch in ranging market = mean reversion opportunity"
        ],
        "failure_nuance": "V1 실패 원인: Low VPIN이 trending을 필터링 못함. V2에서 ADX filter 추가.",
        "similar_patterns": ["range_trading", "bollinger_reversion", "regime_filter"],
        "hidden_risks": [
            "ADX threshold (25)가 너무 낮거나 높을 수 있음",
            "VPIN spike emergency exit이 정상 변동에도 trigger",
            "Asymmetric TP/SL (0.8%/0.3%)가 실제로 효과적인지 검증 필요"
        ],
        "state_machine": "WARMUP(400 bars) → IDLE → HOLDING_LONG/SHORT → COOLDOWN(5 bars)",
        "key_parameters": {
            "safe_zone_threshold": 0.4,
            "adx_period": 14,
            "adx_threshold": 25,
            "bb_period": 20,
            "bb_std_mult": 2.0,
            "vpin_spike_threshold": 0.7,
            "take_profit_pct": 0.8,
            "stop_loss_pct": 0.3,
            "max_hold_bars": 30
        },
        "evolution": "V1 (Safe Zone only, failed) → V2 (ADX + BB, redesigned)",
        "code_quality": "Complex with Dual VPIN, ADX, BB calculations. Wilder's smoothing for ADX."
    },

    # === Batch 3: Remaining strategies (concept-stage or no code) ===

    "btc_eth_catchup": {
        "core_logic": "BTC 양봉 + ETH 음봉/도지 상황에서 ETH 롱 진입. Cross-asset momentum lag 활용.",
        "implicit_assumptions": [
            "ETH가 BTC를 따라가는 지연 현상 존재",
            "4분봉이 5분봉 봇의 사각지대",
            "대장주(BTC) 움직임이 알트(ETH) 방향 예측"
        ],
        "failure_nuance": "CONCEPT_INVALID - 프레임워크 제약으로 구현 불가. ETH 데이터 없음, 단일 심볼 프레임워크.",
        "similar_patterns": ["cross_asset_momentum", "lead_lag", "btc_dominance"],
        "hidden_risks": [
            "Multi-symbol 데이터 필요",
            "Cross-asset 상태 동기화 복잡",
            "Lead-lag 관계가 일정하지 않음"
        ],
        "status": "CONCEPT_INVALID",
        "required_infrastructure": [
            "ETH 틱 데이터 수집",
            "MultiSymbolTickBacktestRunner 개발",
            "Cross-asset 상태 동기화"
        ],
        "code_quality": "No implementation - concept only"
    },

    "gap_retracement": {
        "core_logic": "Long candle (2x avg body) 감지 후 78.6% Fib retracement에서 LIMIT 진입. Trend filter (20-SMA) 적용.",
        "implicit_assumptions": [
            "Impulse move 후 retracement 발생",
            "78.6% level이 optimal R:R (2.58:1) 제공",
            "Trend-aligned entry가 win rate 개선"
        ],
        "failure_nuance": "V1 (50% retracement) 실패. EDA 결과 50% 패턴 미존재 (win 41.6% vs loss 49.9%). V2에서 78.6%로 깊은 진입 + trend filter로 재설계.",
        "similar_patterns": ["fibonacci_retracement", "pullback_entry", "trend_continuation"],
        "hidden_risks": [
            "34% 저승률로 심리적 부담",
            "LIMIT-only exit으로 fast move 시 손절 실패 가능",
            "15분봉 사용으로 trade 빈도 감소"
        ],
        "state_machine": "IDLE → PENDING_ORDER → ACTIVE_POSITION → COOLDOWN",
        "key_parameters": {
            "long_candle_multiplier": 2.0,
            "retracement_level": 0.786,
            "entry_window": 4,
            "exit_timeout": 4,
            "ma_period": 20
        },
        "evolution": "V1 (50% retracement, failed) → V2 (78.6% + trend filter + 15min bars)",
        "code_quality": "Implemented. Uses dataclass for PendingOrder/ActivePosition."
    },

    "orderbook_depth_support": {
        "core_logic": "호가창 Depth 기반 지지선 터치 후 반등 매매. VWAP/Volume Profile을 proxy로 사용 시도.",
        "implicit_assumptions": [
            "호가창 잔량(Depth)이 진짜 지지선",
            "매물대 두꺼운 가격대에서 반등",
            "4분봉 마감 시점에 지지 확인하면 신뢰도 높음"
        ],
        "failure_nuance": "CONCEPT_INVALID - Tick 데이터로는 orderbook depth 테스트 불가. Volume Profile, VWAP proxy 모두 실패 (OS에서 ~0% return).",
        "similar_patterns": ["orderbook_imbalance", "support_resistance", "depth_analysis"],
        "hidden_risks": [
            "Tick 데이터는 executed trades만 제공 (resting orders 정보 없음)",
            "모든 tick-based proxy가 depth 개념 캡처 못함",
            "L2 orderbook 데이터 필요"
        ],
        "status": "CONCEPT_INVALID",
        "required_infrastructure": [
            "L2 Orderbook Snapshots",
            "Weighted Mid Price 계산",
            "Historical Depth Time Series"
        ],
        "proxy_attempts": {
            "Volume Profile (POC/VAL)": "PF 1.25 IS → 0.87 OS (FAILED)",
            "VWAP Deviation + MA50": "PF 10.10 IS → 1.00 OS (FAILED)"
        },
        "code_quality": "No implementation - concept invalid due to data limitation"
    },

    "tip_exhaustion": {
        "core_logic": "신규 고점에서 Top Node Volume < Bottom Node Volume * 0.1 감지 → 매수세 고갈 → Short 진입.",
        "implicit_assumptions": [
            "고점에서 거래량 급감 = 매수세 고갈",
            "Top Node 거래량이 Bottom의 10% 미만이면 exhaustion",
            "적은 매도세로도 급락 가능"
        ],
        "failure_nuance": "아직 iteration 없음. Volume Profile 기반 Tip Exhaustion 로직 설계만 완료.",
        "similar_patterns": ["volume_profile", "exhaustion_detection", "delta_reversal"],
        "hidden_risks": [
            "Volume Profile 계산 복잡성",
            "Top/Bottom Node 정의가 arbitrary",
            "Exhaustion signal이 continuation일 수 있음"
        ],
        "status": "CONCEPT_ONLY",
        "implementation_approach": [
            "Volume Profile: 가격대별 거래량 분포",
            "Delta: 순매수 - 순매도",
            "Tip Exhaustion: Top Volume < Bottom * 0.1"
        ],
        "code_quality": "No implementation yet"
    },

    "vpin_rsi_meanreversion": {
        "core_logic": "Fast/Slow VPIN이 모두 Low Toxicity (Safe Zone, CDF < 0.3)일 때 RSI 역매매. VPIN spike 시 emergency exit.",
        "implicit_assumptions": [
            "Low VPIN = Noise Trading 구간",
            "Noise 구간에서 RSI 역매매 유효",
            "VPIN spike = 정보 거래자 유입 → 즉시 탈출"
        ],
        "failure_nuance": "Previous RSI strategies failed in High VPIN zones. This strategy filters to Low VPIN only.",
        "similar_patterns": ["vpin_rsi_mean_reversion", "safe_zone_trading", "noise_trading"],
        "hidden_risks": [
            "Safe Zone 조건이 너무 restrictive (CDF < 0.3)",
            "RSI와 VPIN timing mismatch",
            "Emergency exit이 정상 변동에도 trigger"
        ],
        "relationship": "vpin_rsi_mean_reversion의 초기 버전 (V1) - 이후 V2로 redesign됨",
        "key_parameters": {
            "safe_zone_threshold": 0.3,
            "rsi_overbought": 70,
            "rsi_oversold": 30,
            "vpin_spike_threshold": 0.7,
            "stop_loss_pct": 0.5,
            "take_profit_pct": 0.5
        },
        "code_quality": "Concept precursor to vpin_rsi_mean_reversion V2 implementation"
    },

    "vpin_strategy": {
        "core_logic": "VPIN 급등 시 변동성 증가 예측. VPIN + 가격 방향 조합으로 진입.",
        "implicit_assumptions": [
            "Informed traders는 대량 주문 → VPIN 상승",
            "VPIN은 정보 비대칭 측정 지표",
            "VPIN spike는 변동성 증가 예고"
        ],
        "failure_nuance": "Iteration 1에서 catastrophic failure. 1294 trades/day (vs 예상 5-15), WR 3.2%, PF 0.01. Excessive trading과 VPIN threshold 문제.",
        "similar_patterns": ["vpin_momentum", "informed_trading", "volatility_prediction"],
        "hidden_risks": [
            "VPIN threshold (0.4)가 너무 자주 trigger",
            "Exit threshold (0.25)로 premature exit",
            "Flip-flopping between positions"
        ],
        "key_parameters": {
            "n_buckets": 50,
            "vpin_threshold": 0.4,
            "vpin_exit_threshold": 0.25,
            "momentum_lookback": 10,
            "n_sigma_lookback": 50
        },
        "root_cause": "VPIN이 대부분의 시간 threshold 이상 유지 → 과도한 재진입",
        "code_quality": "Initial VPIN implementation. BVC (Bulk Volume Classification) based."
    }
}


def add_semantic_fields():
    """Add _semantic fields to strategies_ontology.json"""
    ontology_path = Path("strategies_ontology.json")

    with open(ontology_path) as f:
        ontology = json.load(f)

    # Add semantic fields to analyzed strategies
    enriched_count = 0
    for strategy_key, semantic_data in SEMANTIC_ANALYSIS.items():
        if strategy_key in ontology["strategies"]:
            ontology["strategies"][strategy_key]["_semantic"] = semantic_data
            enriched_count += 1
            print(f"✓ Added _semantic to: {strategy_key}")
        else:
            print(f"✗ Strategy not found: {strategy_key}")

    # Update metadata
    ontology["semantic_enrichment"] = {
        "enriched_at": datetime.now().isoformat(),
        "enriched_count": enriched_count,
        "total_strategies": len(ontology["strategies"]),
        "method": "claude_code_direct_analysis",
        "model": "claude-opus-4-5-20251101"
    }

    # Save updated ontology
    with open(ontology_path, "w") as f:
        json.dump(ontology, f, indent=2, ensure_ascii=False)

    print(f"\n✓ Enriched {enriched_count}/{len(ontology['strategies'])} strategies")
    print(f"✓ Saved to {ontology_path}")


if __name__ == "__main__":
    add_semantic_fields()
