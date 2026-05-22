# Idea backlog — theme balance

쏠리지 않게 시도. 새 theme 자유 추가.

## Attempts by theme

```
xs_factor_zoo            1917  ████████████████████████████████████████  70%
ts_donchian               383  ████████                                 14%
xs_reg_zoo                324  ███████                                  12%
ts_momentum                92  ██
xs_volume_rank              7  █
(other 1-shots: ts_weekend, ts_vwap_dev, ts_lead_lag, ts_mtf_trend,
 ts_tbuy_share, ts_skew, ts_vol_spike, rsi_fade_symmetric)
```

다음 attempt: *0-shot 또는 1-shot* theme 에서 골라야.

## Success criteria

- `abs(pnl_bps_simple) > 0`  (fee 이긴 raw edge, flip-aware)
- `total_trades > 100`
- `|MDD| < 0.60`

## Per-attempt protocol

1. Theme + 1줄 hypothesis
2. 1줄 devil's advocate
3. Alpha 작성 → IS backtest
4. PASS/FAIL → LOG.md
5. Refine 금지. 새 theme 로 이동.
