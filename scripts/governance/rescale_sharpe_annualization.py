"""Rescale archived Sharpe values from the 252-day to the 365-day convention.

The engine annualized daily Sharpe with sqrt(252) until 2026-09-12. Perpetual
futures trade every calendar day, so the daily series has ~365 observations a
year and the correct factor is sqrt(365). Every archived ``metrics.json`` was
produced by ``sharpe_daily_annualized`` (daily resample, then multiply), so the
fix is an exact scalar: multiply by sqrt(365/252).

Idempotent: a file that already carries ``annualization_days`` is skipped, and
each rescaled file records what was done under ``sharpe_rescaled``.

    uv run python scripts/governance/rescale_sharpe_annualization.py --dry-run
    uv run python scripts/governance/rescale_sharpe_annualization.py
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import date
from pathlib import Path

import pandas as pd

FROM_DAYS = 252
TO_DAYS = 365
FACTOR = math.sqrt(TO_DAYS / FROM_DAYS)
SHARPE_KEYS = {"sharpe", "sharpe_daily_annualized", "active_sharpe_daily"}
CSV_COLS = ("is_sharpe", "os_sharpe")
LOG_NOTE = (
    f"> Sharpe convention: values recorded before 2026-09-12 were annualized with "
    f"sqrt({FROM_DAYS}). The framework now uses sqrt({TO_DAYS}) (crypto trades every "
    f"day). metrics.json and alpha_index.csv in this archive have been rescaled "
    f"(x{FACTOR:.4f}); Sharpe numbers written in the text below are still on the "
    f"old scale.\n"
)


def _rescale(obj):
    n = 0
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in SHARPE_KEYS and isinstance(v, (int, float)) and not isinstance(v, bool):
                obj[k] = float(v) * FACTOR
                n += 1
            else:
                n += _rescale(v)
    elif isinstance(obj, list):
        for v in obj:
            n += _rescale(v)
    return n


def rescale_metrics(path: Path, apply: bool) -> int:
    try:
        m = json.loads(path.read_text())
    except Exception:
        return 0
    if not isinstance(m, dict) or "annualization_days" in m:
        return 0
    n = _rescale(m)
    if n == 0:
        return 0
    m["annualization_days"] = TO_DAYS
    m["sharpe_rescaled"] = {
        "from_days": FROM_DAYS, "to_days": TO_DAYS,
        "factor": FACTOR, "fields": n, "at": date.today().isoformat(),
    }
    if apply:
        path.write_text(json.dumps(m, indent=2, default=str))
    return n


def rescale_index(path: Path, apply: bool) -> int:
    df = pd.read_csv(path)
    if "annualization_days" in df.columns:
        return 0
    n = 0
    for c in CSV_COLS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce") * FACTOR
            n += 1
    if n == 0:
        return 0
    df["annualization_days"] = TO_DAYS
    if apply:
        df.to_csv(path, index=False)
    return n


def note_log(path: Path, apply: bool) -> bool:
    s = path.read_text()
    if "Sharpe convention:" in s:
        return False
    lines = s.split("\n")
    i = next((k for k, l in enumerate(lines) if l.startswith("# ")), -1)
    lines.insert(i + 1, "\n" + LOG_NOTE)
    if apply:
        path.write_text("\n".join(lines))
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="archive")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    apply = not a.dry_run
    root = Path(a.root)
    files = fields = 0
    for p in sorted(root.rglob("metrics.json")):
        n = rescale_metrics(p, apply)
        if n:
            files += 1
            fields += n
    idx = sum(1 for p in sorted(root.rglob("alpha_index.csv")) if rescale_index(p, apply))
    logs = sum(1 for p in sorted(root.rglob("LOG.md")) if note_log(p, apply))
    print(json.dumps({
        "dry_run": a.dry_run, "factor": round(FACTOR, 6),
        "metrics_files": files, "sharpe_fields": fields,
        "alpha_index_files": idx, "log_notes": logs,
    }))


if __name__ == "__main__":
    main()
