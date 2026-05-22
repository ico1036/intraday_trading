#!/usr/bin/env python3
"""Generate ridge cross-sectional regression alpha modules.

Each module subclasses ``intraday.strategies._xs_regression_base.XsRegressionBase``
with a fixed list of feature extractors. Variants differ on:
  - feature set (momentum-only, vol-only, full kitchen-sink, ...)
  - ridge regularisation α
  - training window (days)
  - concentration_pct (top/bottom slice size)

Output: ``src/intraday/strategies/multi/xs_reg_*.py``
"""
from __future__ import annotations

import shutil
import sys
import textwrap
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
ZOO_DIR = REPO / "src" / "intraday" / "strategies" / "multi"
PREFIX = "xs_reg_"


# Pre-built feature library. Each feature is a name + python expression
# operating on ``hist`` (dict[str, list[float]] of HISTORY_LEN-deep
# rolling readings). Expressions return None on insufficient history;
# the base class drops symbols whose features are incomplete.
FEATURE_LIBRARY = {
    "ret1d":     "(hist['close'][-1]/hist['close'][-2]-1.0) if len(hist['close'])>=2 else None",
    "ret5d":     "(hist['close'][-1]/hist['close'][-6]-1.0) if len(hist['close'])>=6 else None",
    "ret20d":    "(hist['close'][-1]/hist['close'][-21]-1.0) if len(hist['close'])>=21 else None",
    "ret60d":    "(hist['close'][-1]/hist['close'][-61]-1.0) if len(hist['close'])>=61 else None",
    "logvol":    "math.log(max(hist['quote_volume'][-1], 1e-12)) if hist['quote_volume'] else None",
    "vol20d":    "(((sum((hist['close'][-i]/hist['close'][-i-1]-1.0)**2 for i in range(1,21))/19)**0.5) if len(hist['close'])>=21 else None)",
    "rev_ma20":  "(hist['close'][-1]/(sum(hist['close'][-20:])/20)-1.0) if len(hist['close'])>=20 else None",
    "dist_hi20": "(hist['close'][-1]/max(hist['close'][-20:])-1.0) if len(hist['close'])>=20 else None",
    "maxlot20":  "(max(hist['close'][-i]/hist['close'][-i-1]-1.0 for i in range(1,21)) if len(hist['close'])>=21 else None)",
    "absret20":  "(sum(abs(hist['close'][-i]/hist['close'][-i-1]-1.0) for i in range(1,21))/20 if len(hist['close'])>=21 else None)",
}

# Feature set variants
FEATURE_SETS = {
    "mom":     ["ret1d", "ret5d", "ret20d", "ret60d"],
    "vol":     ["vol20d", "logvol", "absret20"],
    "revert":  ["rev_ma20", "dist_hi20", "ret1d"],
    "mix4":    ["ret5d", "vol20d", "rev_ma20", "logvol"],
    "mix6":    ["ret1d", "ret5d", "ret20d", "vol20d", "rev_ma20", "logvol"],
    "kitchen": list(FEATURE_LIBRARY.keys()),
}
ALPHAS = [0.1, 1.0, 10.0]              # ridge α
TRAIN_WINDOWS = [30, 60, 120]          # rolling days
CONCENTRATIONS = [0.1, 0.2, 0.3]
DIRECTIONS = [("fwd", False), ("rev", True)]


def _class_name(feat: str, a: float, tw: int, dir_label: str, conc_str: str) -> str:
    a_s = str(a).replace(".", "p")
    return f"XsReg{feat.capitalize()}A{a_s}T{tw}{dir_label.capitalize()}C{conc_str}"


def _module_name(feat: str, a: float, tw: int, dir_label: str, conc_str: str) -> str:
    a_s = str(a).replace(".", "p")
    return f"xs_reg_{feat}_a{a_s}_t{tw}_{dir_label}_c{conc_str}"


def _render(feat: str, feature_keys: list[str], a: float, tw: int,
            dir_label: str, reverse: bool, conc: float) -> tuple[str, str]:
    conc_str = f"{int(conc * 100):02d}"
    class_name = _class_name(feat, a, tw, dir_label, conc_str)
    module_name = _module_name(feat, a, tw, dir_label, conc_str)
    feature_lines = ",\n        ".join(
        f"lambda hist: {FEATURE_LIBRARY[k]}" for k in feature_keys
    )
    idea_family = f"xs_reg_{feat}_a{str(a).replace('.', 'p')}_t{tw}_{dir_label}_c{conc_str}"
    body = textwrap.dedent(f'''
        """{module_name} — auto-generated ridge cross-sectional regression alpha.

        Features: {feature_keys}  ridge α={a}  train window={tw}d
        direction={dir_label}  concentration={conc}
        """
        from __future__ import annotations

        import math
        from typing import Any

        from intraday.strategies._xs_regression_base import XsRegressionBase


        ALPHA_CELL = {{
            "bar": "TIME",
            "transform": "ewma_residual",
            "horizon": "multi_day",
            "universe": "basket_full",
            "exit": "signal_flip",
            "idea_family": "{idea_family}",
        }}
        SOURCE_NOTES: list[str] = ["research/notes/xs_regression_zoo.md"]


        class {class_name}(XsRegressionBase):
            HISTORY_FIELDS = ("close", "quote_volume")
            HISTORY_LEN = 130
            RIDGE_ALPHA = {a}
            TRAIN_WINDOW = {tw}
            FEATURE_FNS = (
        {feature_lines},
            )

            def __init__(self, symbols: list[str], **kwargs: Any):
                kwargs.setdefault("concentration_pct", {conc})
                kwargs.setdefault("reverse", {reverse})
                super().__init__(symbols=symbols, **kwargs)
    ''').lstrip()
    return body, module_name


def main() -> int:
    written = existing = 0
    skipped: list[str] = []
    for feat, keys in FEATURE_SETS.items():
        for a in ALPHAS:
            for tw in TRAIN_WINDOWS:
                for dir_label, rev in DIRECTIONS:
                    for conc in CONCENTRATIONS:
                        body, module_name = _render(feat, keys, a, tw, dir_label, rev, conc)
                        out = ZOO_DIR / f"{module_name}.py"
                        if out.exists():
                            existing += 1
                            continue
                        try:
                            out.write_text(body)
                            written += 1
                        except Exception as exc:
                            skipped.append(f"{module_name}: {exc}")
    # Research note (governance requires SOURCE_NOTES pointing to existing file)
    notes = REPO / "research" / "notes" / "xs_regression_zoo.md"
    if not notes.exists():
        notes.write_text(
            "# xs_regression_zoo — auto-generated ridge XS alphas\n\n"
            "Each alpha module subclasses XsRegressionBase, fits a per-day\n"
            "ridge regression of next-bar return on a small feature vector\n"
            "(momentum / vol / mean-reversion / volume), and emits an\n"
            "equal-weight long-short basket on the predicted scores.\n"
        )
    print(f"[reg-zoo] kept {existing} existing, wrote {written} new")
    if skipped:
        for s in skipped[:10]:
            print(f"  skip: {s}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
