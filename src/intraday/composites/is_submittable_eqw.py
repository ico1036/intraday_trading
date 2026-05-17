"""is_submittable_eqw — equal-weight composite of IS-submittable alphas.

Selection: every archived alpha whose ``is/metrics.json`` passes the IS-only
mirror of S1-S7 / R1-R4 (label ``"SUBMITTABLE"`` from
``classify_alpha(is_m, os_m=None)``):

    R1-IS  IS bps > 0
    R2-IS  IS t-stat ≥ 1.5
    R4     IS trades ≥ 100
    S1     IS t-stat > 2.5
    S2     IS bps > 2.0
    S3     |IS Max DD| < 0.12
    S5     IS profit factor > 1.3
    S7     IS trades > 500

Weighting: 1/N equal across selected members.

Look-ahead safeguards:

* Selection enumerates each alpha's ``is/metrics.json`` directly — never
  ``os/metrics.json``. ``classify_alpha`` is invoked with ``os_m=None`` to
  force the IS-only path; the OS-aware path checks degradation ratios that
  would leak OS information.
* The (member_ids, coefficients) decision is computed once and frozen in
  ``manifest.json`` by the runner.
* ``alpha_index.csv`` is bypassed for selection because it is currently
  stale relative to the on-disk archive; falling back to per-alpha IS
  metrics keeps the rule deterministic and reproducible.

Run::

    uv run python -m intraday.composites.is_submittable_eqw \\
        --run-id run_2026_05_c --no-os
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from intraday.composites._runner import ARCHIVE_ROOT, build_and_backtest

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "scripts" / "tools"))
from alpha_dashboard_lib import classify_alpha  # noqa: E402


COMPOSITE_ID = "is_submittable_eqw"
COMPOSITION_NOTE = "equal_weight_is_submittable"


def _select_is_submittable(run_id: str) -> list[str]:
    out: list[str] = []
    alphas_dir = ARCHIVE_ROOT / run_id / "alphas"
    for d in sorted(alphas_dir.iterdir()):
        if not d.is_dir():
            continue
        p = d / "is" / "metrics.json"
        if not p.exists():
            continue
        is_m = json.loads(p.read_text())
        label, _why = classify_alpha(is_m, os_m=None)
        if label == "SUBMITTABLE":
            out.append(d.name)
    if not out:
        raise RuntimeError(
            f"No IS-submittable alphas found under {alphas_dir}"
        )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=f"Build composite {COMPOSITE_ID}")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--no-os", action="store_true", help="skip OS backtest")
    args = parser.parse_args()
    run_id = args.run_id

    def select_members(_alpha_index: pd.DataFrame) -> list[str]:
        return _select_is_submittable(run_id)

    def equal_weight(ids: list[str], _idx: pd.DataFrame) -> dict[str, float]:
        n = len(ids)
        return {a: 1.0 / n for a in ids}

    build_and_backtest(
        composite_id=COMPOSITE_ID,
        run_id=run_id,
        select_members=select_members,
        member_weights=equal_weight,
        composition_note=COMPOSITION_NOTE,
        include_os=not args.no_os,
    )


if __name__ == "__main__":
    main()
