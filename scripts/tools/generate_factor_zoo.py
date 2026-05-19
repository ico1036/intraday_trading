#!/usr/bin/env python3
"""Generate a large grid of XS / TS factor alpha modules.

Each generated file is a tiny shim that subclasses
``intraday.strategies._xs_factor_base.XsFactorBase`` and overrides
``_compute_score`` with one of the signals defined in SIGNAL_LIBRARY.
Pairs with ``scripts/run_batch_backtests.py`` to drive backtests over
the produced grid.

Writes into ``src/intraday/strategies/multi/zoo/<file>.py`` so the
zoo folder is easy to clean up wholesale (and excluded from the rest
of the strategies/multi listing for sanity).

Run:
    uv run python scripts/tools/generate_factor_zoo.py
"""
from __future__ import annotations

import shutil
import sys
import textwrap
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
ZOO_DIR = REPO / "src" / "intraday" / "strategies" / "multi"
ZOO_PREFIX = "xs_factor_"


# Each entry: name → (history_fields_tuple, body_expr, min_hist_len)
# `body_expr` is the python expression for _compute_score's return value
# given `hist` (dict[str, list[float]]). `min_hist_len` is the minimum
# length of hist[fields[0]] required before the expression makes sense.
SIGNALS: dict[str, tuple[tuple[str, ...], str, int]] = {
    # --- liquidity / size ---
    "volume":            (("quote_volume",), "hist['quote_volume'][-1]", 1),
    "log_volume":        (("quote_volume",), "math.log(max(hist['quote_volume'][-1], 1e-12))", 1),
    "dollar_volume":     (("quote_volume", "close"),
                          "hist['quote_volume'][-1]", 1),
    "vol_zscore_5d":     (("quote_volume",),
                          "((hist['quote_volume'][-1] - (sum(hist['quote_volume'][-5:])/5)) / "
                          "(((sum((v - sum(hist['quote_volume'][-5:])/5)**2 for v in hist['quote_volume'][-5:]))/4)**0.5 or 1e-9))", 5),
    "vol_zscore_20d":    (("quote_volume",),
                          "((hist['quote_volume'][-1] - (sum(hist['quote_volume'][-20:])/20)) / "
                          "(((sum((v - sum(hist['quote_volume'][-20:])/20)**2 for v in hist['quote_volume'][-20:]))/19)**0.5 or 1e-9))", 20),
    # --- returns / momentum ---
    "return_1d":         (("close",), "hist['close'][-1]/hist['close'][-2] - 1.0", 2),
    "return_3d":         (("close",), "hist['close'][-1]/hist['close'][-4] - 1.0", 4),
    "return_5d":         (("close",), "hist['close'][-1]/hist['close'][-6] - 1.0", 6),
    "return_7d":         (("close",), "hist['close'][-1]/hist['close'][-8] - 1.0", 8),
    "return_14d":        (("close",), "hist['close'][-1]/hist['close'][-15] - 1.0", 15),
    "return_21d":        (("close",), "hist['close'][-1]/hist['close'][-22] - 1.0", 22),
    "return_28d":        (("close",), "hist['close'][-1]/hist['close'][-29] - 1.0", 29),
    "return_60d":        (("close",), "hist['close'][-1]/hist['close'][-61] - 1.0", 61),
    # --- volatility / realised vol ---
    "vol_real_10d":      (("close",),
                          "((sum((hist['close'][-i]/hist['close'][-i-1]-1.0)**2 for i in range(1,11))/9)**0.5)", 11),
    "vol_real_20d":      (("close",),
                          "((sum((hist['close'][-i]/hist['close'][-i-1]-1.0)**2 for i in range(1,21))/19)**0.5)", 21),
    "vol_real_40d":      (("close",),
                          "((sum((hist['close'][-i]/hist['close'][-i-1]-1.0)**2 for i in range(1,41))/39)**0.5)", 41),
    # --- mean reversion (last bar vs short MA) ---
    "rev_to_ma5":        (("close",), "hist['close'][-1]/(sum(hist['close'][-5:])/5) - 1.0", 5),
    "rev_to_ma20":       (("close",), "hist['close'][-1]/(sum(hist['close'][-20:])/20) - 1.0", 20),
    "rev_to_ma60":       (("close",), "hist['close'][-1]/(sum(hist['close'][-60:])/60) - 1.0", 60),
    # --- range / breakout ---
    "close_to_high_20d": (("close", "high"),
                          "(hist['close'][-1] - min(hist['close'][-20:])) / (max(hist['close'][-20:]) - min(hist['close'][-20:]) or 1e-9)", 20),
    "close_to_high_60d": (("close",),
                          "(hist['close'][-1] - min(hist['close'][-60:])) / (max(hist['close'][-60:]) - min(hist['close'][-60:]) or 1e-9)", 60),
    # --- skew / kurt (distribution shape over 20d returns) ---
    "ret_skew_20d":      (("close",),
                          "(lambda r=[hist['close'][-i]/hist['close'][-i-1]-1.0 for i in range(1,21)]: "
                          "(sum((x - sum(r)/20)**3 for x in r)/20) / ((sum((x - sum(r)/20)**2 for x in r)/20)**1.5 or 1e-9))()", 21),
    "ret_kurt_20d":      (("close",),
                          "(lambda r=[hist['close'][-i]/hist['close'][-i-1]-1.0 for i in range(1,21)]: "
                          "(sum((x - sum(r)/20)**4 for x in r)/20) / ((sum((x - sum(r)/20)**2 for x in r)/20)**2 or 1e-9))()", 21),
    # --- max-lottery (largest daily ret over window) ---
    "max_lottery_10d":   (("close",),
                          "max(hist['close'][-i]/hist['close'][-i-1]-1.0 for i in range(1,11))", 11),
    "max_lottery_20d":   (("close",),
                          "max(hist['close'][-i]/hist['close'][-i-1]-1.0 for i in range(1,21))", 21),
    # --- amihud illiquidity = |ret| / dollar_volume ---
    "illiq_amihud_5d":   (("close", "quote_volume"),
                          "sum(abs(hist['close'][-i]/hist['close'][-i-1]-1.0) / (hist['quote_volume'][-i] or 1e-9) for i in range(1,6))/5", 6),
    "illiq_amihud_20d":  (("close", "quote_volume"),
                          "sum(abs(hist['close'][-i]/hist['close'][-i-1]-1.0) / (hist['quote_volume'][-i] or 1e-9) for i in range(1,21))/20", 21),
    # --- price acceleration (2nd derivative proxy) ---
    "accel_5d":          (("close",),
                          "(hist['close'][-1] - 2*hist['close'][-3] + hist['close'][-5]) / (hist['close'][-3] or 1e-9)", 5),
    # --- momentum 12-1 (classic — return over 12 weeks ex last week) ---
    "mom_12_1":          (("close",),
                          "hist['close'][-8]/hist['close'][-85] - 1.0", 85),
    # === expanded signals (batch 2) ===
    # --- momentum at additional lookbacks ---
    "return_2d":         (("close",), "hist['close'][-1]/hist['close'][-3] - 1.0", 3),
    "return_10d":        (("close",), "hist['close'][-1]/hist['close'][-11] - 1.0", 11),
    "return_42d":        (("close",), "hist['close'][-1]/hist['close'][-43] - 1.0", 43),
    "return_84d":        (("close",), "hist['close'][-1]/hist['close'][-85] - 1.0", 85),
    # --- excluding-most-recent-week momentum (classic mom_n_m) ---
    "mom_10_1":          (("close",), "hist['close'][-2]/hist['close'][-11] - 1.0", 11),
    "mom_20_1":          (("close",), "hist['close'][-2]/hist['close'][-21] - 1.0", 21),
    "mom_60_5":          (("close",), "hist['close'][-6]/hist['close'][-61] - 1.0", 61),
    # --- momentum minus reversal (12m return minus 1m return) ---
    "mom_minus_rev_60_5":(("close",),
                          "(hist['close'][-1]/hist['close'][-61] - 1.0) - "
                          "(hist['close'][-1]/hist['close'][-6] - 1.0)", 61),
    "mom_minus_rev_84_7":(("close",),
                          "(hist['close'][-1]/hist['close'][-85] - 1.0) - "
                          "(hist['close'][-1]/hist['close'][-8] - 1.0)", 85),
    # --- mean reversion at more horizons ---
    "rev_to_ma3":        (("close",), "hist['close'][-1]/(sum(hist['close'][-3:])/3) - 1.0", 3),
    "rev_to_ma10":       (("close",), "hist['close'][-1]/(sum(hist['close'][-10:])/10) - 1.0", 10),
    "rev_to_ma40":       (("close",), "hist['close'][-1]/(sum(hist['close'][-40:])/40) - 1.0", 40),
    # --- z-score of close vs window ---
    "close_zscore_10d":  (("close",),
                          "(hist['close'][-1] - sum(hist['close'][-10:])/10) / "
                          "(((sum((c - sum(hist['close'][-10:])/10)**2 for c in hist['close'][-10:]))/9)**0.5 or 1e-9)", 10),
    "close_zscore_20d":  (("close",),
                          "(hist['close'][-1] - sum(hist['close'][-20:])/20) / "
                          "(((sum((c - sum(hist['close'][-20:])/20)**2 for c in hist['close'][-20:]))/19)**0.5 or 1e-9)", 20),
    "close_zscore_60d":  (("close",),
                          "(hist['close'][-1] - sum(hist['close'][-60:])/60) / "
                          "(((sum((c - sum(hist['close'][-60:])/60)**2 for c in hist['close'][-60:]))/59)**0.5 or 1e-9)", 60),
    # --- realized vol at extra windows ---
    "vol_real_5d":       (("close",),
                          "((sum((hist['close'][-i]/hist['close'][-i-1]-1.0)**2 for i in range(1,6))/4)**0.5)", 6),
    "vol_real_60d":      (("close",),
                          "((sum((hist['close'][-i]/hist['close'][-i-1]-1.0)**2 for i in range(1,61))/59)**0.5)", 61),
    # --- vol-of-vol (vol_20d / vol_60d ratio) ---
    "vol_ratio_20_60":   (("close",),
                          "(((sum((hist['close'][-i]/hist['close'][-i-1]-1.0)**2 for i in range(1,21))/19)**0.5)) / "
                          "(((sum((hist['close'][-i]/hist['close'][-i-1]-1.0)**2 for i in range(1,61))/59)**0.5) or 1e-9)", 61),
    "vol_ratio_5_20":    (("close",),
                          "(((sum((hist['close'][-i]/hist['close'][-i-1]-1.0)**2 for i in range(1,6))/4)**0.5)) / "
                          "(((sum((hist['close'][-i]/hist['close'][-i-1]-1.0)**2 for i in range(1,21))/19)**0.5) or 1e-9)", 21),
    # --- close-to-high at more windows ---
    "close_to_high_5d":  (("close",),
                          "(hist['close'][-1] - min(hist['close'][-5:])) / (max(hist['close'][-5:]) - min(hist['close'][-5:]) or 1e-9)", 5),
    "close_to_high_10d": (("close",),
                          "(hist['close'][-1] - min(hist['close'][-10:])) / (max(hist['close'][-10:]) - min(hist['close'][-10:]) or 1e-9)", 10),
    # --- price relative to N-day high / low ---
    "dist_from_high_20d":(("close",),
                          "hist['close'][-1] / max(hist['close'][-20:]) - 1.0", 20),
    "dist_from_low_20d": (("close",),
                          "hist['close'][-1] / min(hist['close'][-20:]) - 1.0", 20),
    "dist_from_high_60d":(("close",),
                          "hist['close'][-1] / max(hist['close'][-60:]) - 1.0", 60),
    "dist_from_low_60d": (("close",),
                          "hist['close'][-1] / min(hist['close'][-60:]) - 1.0", 60),
    # --- range / volatility breakout ---
    "range_zscore_20d":  (("close",),
                          "((max(hist['close'][-5:]) - min(hist['close'][-5:])) - "
                          "(sum(max(hist['close'][i:i+5]) - min(hist['close'][i:i+5]) for i in range(-20,-5))/15)) / "
                          "((sum((max(hist['close'][i:i+5]) - min(hist['close'][i:i+5]))**2 for i in range(-20,-5))/15)**0.5 or 1e-9)", 25),
    # --- volume-weighted return ---
    "ret_weighted_vol_5d":(("close", "quote_volume"),
                          "sum((hist['close'][-i]/hist['close'][-i-1]-1.0)*hist['quote_volume'][-i] for i in range(1,6)) / "
                          "(sum(hist['quote_volume'][-i] for i in range(1,6)) or 1e-9)", 6),
    "ret_weighted_vol_20d":(("close", "quote_volume"),
                          "sum((hist['close'][-i]/hist['close'][-i-1]-1.0)*hist['quote_volume'][-i] for i in range(1,21)) / "
                          "(sum(hist['quote_volume'][-i] for i in range(1,21)) or 1e-9)", 21),
    # --- absolute return mean (turnover proxy) ---
    "abs_ret_5d":        (("close",),
                          "sum(abs(hist['close'][-i]/hist['close'][-i-1]-1.0) for i in range(1,6))/5", 6),
    "abs_ret_20d":       (("close",),
                          "sum(abs(hist['close'][-i]/hist['close'][-i-1]-1.0) for i in range(1,21))/20", 21),
    # --- max lottery at more windows ---
    "max_lottery_5d":    (("close",),
                          "max(hist['close'][-i]/hist['close'][-i-1]-1.0 for i in range(1,6))", 6),
    "max_lottery_60d":   (("close",),
                          "max(hist['close'][-i]/hist['close'][-i-1]-1.0 for i in range(1,61))", 61),
    # --- min daily return (negative lottery) ---
    "min_lottery_20d":   (("close",),
                          "min(hist['close'][-i]/hist['close'][-i-1]-1.0 for i in range(1,21))", 21),
    "min_lottery_60d":   (("close",),
                          "min(hist['close'][-i]/hist['close'][-i-1]-1.0 for i in range(1,61))", 61),
    # --- skew at additional windows ---
    "ret_skew_60d":      (("close",),
                          "(lambda r=[hist['close'][-i]/hist['close'][-i-1]-1.0 for i in range(1,61)]: "
                          "(sum((x - sum(r)/60)**3 for x in r)/60) / ((sum((x - sum(r)/60)**2 for x in r)/60)**1.5 or 1e-9))()", 61),
    # --- amihud at extra horizon ---
    "illiq_amihud_60d":  (("close", "quote_volume"),
                          "sum(abs(hist['close'][-i]/hist['close'][-i-1]-1.0) / (hist['quote_volume'][-i] or 1e-9) for i in range(1,61))/60", 61),
    # --- log dollar volume ---
    "log_dollar_volume": (("quote_volume",),
                          "math.log(max(hist['quote_volume'][-1], 1e-12))", 1),
    # --- volume growth (today / mean last 5d) ---
    "vol_growth_5d":     (("quote_volume",),
                          "hist['quote_volume'][-1] / (sum(hist['quote_volume'][-6:-1])/5 or 1e-9) - 1.0", 6),
    "vol_growth_20d":    (("quote_volume",),
                          "hist['quote_volume'][-1] / (sum(hist['quote_volume'][-21:-1])/20 or 1e-9) - 1.0", 21),
    # --- return × volume (signed) ---
    "ret_times_vol_1d":  (("close", "quote_volume"),
                          "(hist['close'][-1]/hist['close'][-2]-1.0) * hist['quote_volume'][-1]", 2),
    "ret_times_vol_5d":  (("close", "quote_volume"),
                          "sum((hist['close'][-i]/hist['close'][-i-1]-1.0)*hist['quote_volume'][-i] for i in range(1,6))", 6),
    # --- sign of return (binary directional) ---
    "ret_sign_1d":       (("close",),
                          "(1.0 if hist['close'][-1] > hist['close'][-2] else -1.0)", 2),
    "ret_sign_streak_5d":(("close",),
                          "sum((1.0 if hist['close'][-i] > hist['close'][-i-1] else -1.0) for i in range(1,6))", 6),
    # --- second derivative of price (acceleration at different horizons) ---
    "accel_10d":         (("close",),
                          "(hist['close'][-1] - 2*hist['close'][-6] + hist['close'][-11]) / (hist['close'][-6] or 1e-9)", 11),
    "accel_20d":         (("close",),
                          "(hist['close'][-1] - 2*hist['close'][-11] + hist['close'][-21]) / (hist['close'][-11] or 1e-9)", 21),
    # --- relative position between mean and last (mean reversion strength) ---
    "rev_strength_5d":   (("close",),
                          "(hist['close'][-1] - sum(hist['close'][-5:])/5) / (hist['close'][-1] or 1e-9)", 5),
    "rev_strength_20d":  (("close",),
                          "(hist['close'][-1] - sum(hist['close'][-20:])/20) / (hist['close'][-1] or 1e-9)", 20),
    # --- 10d-over-60d momentum ratio ---
    "mom_ratio_10_60":   (("close",),
                          "(hist['close'][-1]/hist['close'][-11] - 1.0) - (hist['close'][-1]/hist['close'][-61] - 1.0)", 61),
    # --- volume × abs return (Amihud-inverse, signal of informed trade) ---
    "vol_x_absret_5d":   (("close", "quote_volume"),
                          "sum(abs(hist['close'][-i]/hist['close'][-i-1]-1.0) * hist['quote_volume'][-i] for i in range(1,6))/5", 6),
    # --- downside vol (semivariance of negative returns 20d) ---
    "downside_vol_20d":  (("close",),
                          "((sum(min(hist['close'][-i]/hist['close'][-i-1]-1.0, 0.0)**2 for i in range(1,21))/19)**0.5)", 21),
    # --- upside vol ---
    "upside_vol_20d":    (("close",),
                          "((sum(max(hist['close'][-i]/hist['close'][-i-1]-1.0, 0.0)**2 for i in range(1,21))/19)**0.5)", 21),
    # --- upside-downside vol ratio ---
    "ud_vol_ratio_20d":  (("close",),
                          "((sum(max(hist['close'][-i]/hist['close'][-i-1]-1.0, 0.0)**2 for i in range(1,21))/19)**0.5) / "
                          "(((sum(min(hist['close'][-i]/hist['close'][-i-1]-1.0, 0.0)**2 for i in range(1,21))/19)**0.5) or 1e-9)", 21),
    # --- average true range proxy (no high/low — use close range) ---
    "atr_proxy_14d":     (("close",),
                          "sum(abs(hist['close'][-i] - hist['close'][-i-1]) for i in range(1,15))/14", 15),
    # --- mean abs return / vol (signal of inefficiency) ---
    "mar_efficiency_20d":(("close",),
                          "abs(hist['close'][-1]/hist['close'][-21]-1.0) / "
                          "(sum(abs(hist['close'][-i]/hist['close'][-i-1]-1.0) for i in range(1,21)) or 1e-9)", 21),
    # --- streak: number of consecutive same-sign days ---
    "streak_5d_signed":  (("close",),
                          "(1.0 if hist['close'][-1] > hist['close'][-2] else -1.0) * "
                          "sum(1 for i in range(1,6) if (hist['close'][-i] > hist['close'][-i-1]) == (hist['close'][-1] > hist['close'][-2]))", 6),
}


CONCENTRATIONS = [0.1, 0.2, 0.3]
DIRECTIONS = [("fwd", False), ("rev", True)]


def _class_name(sig: str, dir_label: str, conc_str: str) -> str:
    # Collapse the signal's underscores so the camelcase class name has
    # exactly three "words" (signal / direction / concentration) that
    # backtest._class_to_module_name can reverse-map deterministically.
    sig_collapsed = sig.replace("_", "")
    return f"XsFactor{sig_collapsed.capitalize()}{dir_label.capitalize()}C{conc_str}"


def _module_name(sig: str, dir_label: str, conc_str: str) -> str:
    sig_collapsed = sig.replace("_", "")
    return f"xs_factor_{sig_collapsed}_{dir_label}_c{conc_str}"


def _render(sig: str, fields: tuple[str, ...], expr: str, min_len: int,
            dir_label: str, reverse: bool, conc: float) -> str:
    conc_str = f"{int(conc * 100):02d}"  # 0.10 -> "10"
    class_name = _class_name(sig, dir_label, conc_str)
    module_name = _module_name(sig, dir_label, conc_str)
    history_len = max(min_len + 1, 80)
    idea_family = f"xs_factor_{sig}_{dir_label}_c{conc_str}"
    fields_repr = repr(fields)
    body = textwrap.dedent(f'''
        """{module_name} — auto-generated XS factor.

        Signal: {sig}  direction={dir_label}  concentration={conc}
        Cross-sectional rank of ``_compute_score`` over the eligible
        universe each emit bar, top/bottom concentration_pct legs.
        """
        from __future__ import annotations

        import math
        from typing import Any

        from intraday.strategies._xs_factor_base import XsFactorBase


        ALPHA_CELL = {{
            "bar": "TIME",
            "transform": "rolling_rank",
            "horizon": "multi_day",
            "universe": "basket_full",
            "exit": "signal_flip",
            "idea_family": "{idea_family}",
        }}
        SOURCE_NOTES: list[str] = ["research/notes/xs_factor_zoo.md"]


        class {class_name}(XsFactorBase):
            HISTORY_FIELDS = {fields_repr}
            HISTORY_LEN = {history_len}

            def __init__(self, symbols: list[str], **kwargs: Any):
                kwargs.setdefault("concentration_pct", {conc})
                kwargs.setdefault("reverse", {reverse})
                super().__init__(symbols=symbols, **kwargs)

            def _compute_score(self, hist: dict[str, list[float]]) -> float | None:
                if len(hist[{fields[0]!r}]) < {min_len}:
                    return None
                try:
                    return {expr}
                except Exception:
                    return None
    ''').lstrip()
    return body, module_name


def main() -> int:
    # Idempotent: write only missing modules. Safe to invoke while a
    # batch backtest is running over the existing zoo files because we
    # never overwrite or delete an existing module.
    pass  # no-op; preserve existing files

    notes_path = REPO / "research" / "notes" / "xs_factor_zoo.md"
    if not notes_path.exists():
        notes_path.write_text(
            "# xs_factor_zoo — auto-generated XS factor sweep\n\n"
            "Each alpha module ranks the cross-section by a single factor,\n"
            "takes the top/bottom concentration_pct legs, and equal-weights\n"
            "within each leg. Generated by scripts/tools/generate_factor_zoo.py.\n"
        )

    written = 0
    existing = 0
    skipped: list[str] = []
    for sig, (fields, expr, min_len) in SIGNALS.items():
        for dir_label, reverse in DIRECTIONS:
            for conc in CONCENTRATIONS:
                body, module_name = _render(sig, fields, expr, min_len,
                                            dir_label, reverse, conc)
                out = ZOO_DIR / f"{module_name}.py"
                if out.exists():
                    existing += 1
                    continue
                try:
                    out.write_text(body)
                    written += 1
                except Exception as exc:
                    skipped.append(f"{module_name}: {exc}")
    print(f"[zoo] kept {existing} existing, wrote {written} new")

    print(f"[zoo] wrote {written} alpha modules into {ZOO_DIR}")
    if skipped:
        for s in skipped[:10]:
            print(f"  skip: {s}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
