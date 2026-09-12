"""Rebuild ``archive/<run_id>/alpha_index.csv`` from each alpha's metrics.json.

Handles both layouts: a flat ``alphas/<id>/metrics.json`` with ``is``/``os``
sub-dicts (written by ``backtest.py --is-end``) and the split layout
``alphas/<id>/{is,os}/metrics.json``. ``status`` is carried over from the
existing index (it is a quality-gate verdict, not recomputed here).

    uv run python scripts/governance/build_alpha_index.py --run-id run_2026_08_pit641
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

COLS = ["run_id", "alpha_id", "is_sharpe", "is_return", "is_drawdown", "is_trades",
        "os_sharpe", "os_return", "os_drawdown", "os_trades", "status", "annualization_days"]


def _split(alpha_dir: Path, name: str) -> dict:
    flat = alpha_dir / "metrics.json"
    if flat.exists():
        m = json.loads(flat.read_text())
        if isinstance(m.get(name), dict):
            d = dict(m[name])
            d.setdefault("annualization_days", m.get("annualization_days"))
            return d
    nested = alpha_dir / name / "metrics.json"
    if nested.exists():
        return json.loads(nested.read_text())
    return {}


def build(run_id: str, root: Path = Path("archive")) -> pd.DataFrame:
    run_dir = root / run_id
    old = {}
    idx_path = run_dir / "alpha_index.csv"
    if idx_path.exists():
        prev = pd.read_csv(idx_path)
        if "status" in prev.columns:
            old = dict(zip(prev["alpha_id"], prev["status"]))
    rows = []
    for d in sorted(p for p in (run_dir / "alphas").iterdir() if p.is_dir()):
        is_m, os_m = _split(d, "is"), _split(d, "os")
        if not is_m:
            continue
        rows.append({
            "run_id": run_id, "alpha_id": d.name,
            "is_sharpe": is_m.get("sharpe"), "is_return": is_m.get("total_return"),
            "is_drawdown": is_m.get("max_drawdown"), "is_trades": is_m.get("total_trades"),
            "os_sharpe": os_m.get("sharpe"), "os_return": os_m.get("total_return"),
            "os_drawdown": os_m.get("max_drawdown"), "os_trades": os_m.get("total_trades"),
            "status": old.get(d.name, ""),
            "annualization_days": is_m.get("annualization_days") or os_m.get("annualization_days"),
        })
    return pd.DataFrame(rows, columns=COLS)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    df = build(a.run_id)
    print(df.to_string(index=False))
    if not a.dry_run:
        df.to_csv(Path("archive") / a.run_id / "alpha_index.csv", index=False)


if __name__ == "__main__":
    main()
