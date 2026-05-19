#!/usr/bin/env python3
"""Backport IC fields from ic_distribution.csv into each alpha's metrics.json.

Existing alphas were generated before backtest.py learned how to write
ic_mean / ic_ir / ic_z. classify_alpha then sees a blank IC slot and
falls back to NORMAL — even when the alpha's IC is actually strong.

This one-shot script reads ic_scan.py's CSV output and merges the IC
columns into the canonical metrics.json that dashboard's classifier
reads from (forward/ when present, otherwise is/, otherwise flat).

After running, restart the dashboard to drop the in-memory index cache.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd


REPO = Path(__file__).resolve().parents[2]
CSV = Path("/tmp/ic_distribution.csv")
ARCHIVE = REPO / "archive"


def _target_metrics(run_id: str, alpha_id: str) -> Path | None:
    ad = ARCHIVE / run_id / "alphas" / alpha_id
    # The classifier prefers forward > flat > is in load_index.
    for candidate in (
        ad / "forward" / "metrics.json",
        ad / "metrics.json",
        ad / "is" / "metrics.json",
    ):
        if candidate.exists():
            return candidate
    return None


def main() -> int:
    if not CSV.exists():
        print(f"missing {CSV}; run scripts/tools/ic_scan.py first", file=sys.stderr)
        return 1
    df = pd.read_csv(CSV)
    fields = ["ic_mean", "ic_std", "ic_ir", "ic_hit_rate", "ic_bars",
              "ic_mean_is", "ic_std_is", "ic_bars_is",
              "ic_mean_os", "ic_std_os", "ic_bars_os",
              "ic_z"]
    present = [f for f in fields if f in df.columns]
    print(f"[backport] merging {present} into per-alpha metrics.json")

    n_ok = 0
    n_skip = 0
    n_miss = 0
    for _, row in df.iterrows():
        target = _target_metrics(row["run_id"], row["alpha_id"])
        if target is None:
            n_miss += 1
            continue
        try:
            payload = json.loads(target.read_text())
        except Exception:
            n_skip += 1
            continue
        def _cast(field: str, raw):
            if pd.isna(raw):
                return None
            if field in ("ic_bars", "ic_bars_is", "ic_bars_os"):
                try:
                    return int(raw)
                except Exception:
                    return None
            try:
                return float(raw)
            except Exception:
                return None

        for f in present:
            payload[f] = _cast(f, row.get(f))
        # Flat layout: the classifier reads the "is" sub-block. Mirror IC
        # fields into it so SUBMITTABLE/NORMAL evaluation works without
        # the classifier needing a separate codepath for top-level IC.
        if isinstance(payload.get("is"), dict):
            for f in present:
                payload["is"][f] = _cast(f, row.get(f))
        try:
            target.write_text(json.dumps(payload, indent=2, default=str))
            n_ok += 1
        except Exception:
            n_skip += 1

    print(f"[backport] ok={n_ok} skip={n_skip} missing_metrics={n_miss}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
