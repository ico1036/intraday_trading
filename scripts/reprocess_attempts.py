#!/usr/bin/env python3
"""Re-compute display metrics + re-split + re-classify for an existing run.

For each alpha under ``archive/<run>/alphas/`` that has a flat
``metrics.json``, re-run ``compute_trade_stats`` and ``compute_ic`` on
the existing parquet artifacts (no backtest re-execution), promote the
top-level IC sub-keys into ``is/``/``os/`` metrics.json, and rewrite the
``alpha_index.csv`` summary line with the new classification.

Safe to re-run; idempotent.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts" / "tools"))
sys.path.insert(0, str(REPO / "scripts"))
from alpha_dashboard_lib import classify_alpha, compute_trade_stats, compute_ic  # noqa: E402
from attempt_loop import _split_flat_to_is_os  # noqa: E402


def _refresh_flat_metrics(alpha_dir: Path, is_end: str) -> None:
    """Re-run trade-stats + IC and merge into flat metrics.json."""
    import pandas as pd
    mfp = alpha_dir / "metrics.json"
    if not mfp.exists():
        return
    m = json.loads(mfp.read_text())

    tp = alpha_dir / "trades.parquet"
    if tp.exists():
        try:
            trades = pd.read_parquet(tp)
            stats = compute_trade_stats(trades)
            for k, v in stats.items():
                if k == "n_round_trips":
                    m["round_trips"] = v
                elif k == "mean_bps":
                    m["pnl_bps_simple"] = v
                elif k == "mean_bps_notional_weighted":
                    m["pnl_bps_notional_weighted"] = v
                elif k == "std_bps":
                    m["pnl_bps_std"] = v
                elif k == "win_rate":
                    m["trade_win_rate"] = v
                elif k == "profit_factor":
                    m["profit_factor_trades"] = v
                else:
                    m[k] = v
        except Exception as e:
            print(f"  trade stats failed for {alpha_dir.name}: {e}")

    wp = alpha_dir / "weights.parquet"
    if wp.exists():
        try:
            weights = pd.read_parquet(wp)
            ic = compute_ic(weights, is_end=is_end)
            for k, v in ic.items():
                m[k] = v
        except Exception as e:
            print(f"  IC failed for {alpha_dir.name}: {e}")

    mfp.write_text(json.dumps(m, indent=2, default=str))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-id", required=True)
    args = ap.parse_args()

    sp = json.loads((REPO / "archive" / args.run_id / "splits.json").read_text())
    is_end = sp["is"]["end"]

    run_dir = REPO / "archive" / args.run_id
    alphas_dir = run_dir / "alphas"
    index_path = run_dir / "alpha_index.csv"

    # Rewrite alpha_index header
    new_rows = ["alpha_id,strategy,is_sharpe,is_return,is_trades,os_sharpe,os_return,os_trades,ic_mean_is,ic_ir_is,label_is,label_full\n"]

    counts = {"is_sub": 0, "full_sub": 0, "total": 0}
    for d in sorted(alphas_dir.iterdir()):
        if not d.is_dir():
            continue
        if not (d / "metrics.json").exists():
            continue
        counts["total"] += 1

        _refresh_flat_metrics(d, is_end)
        _split_flat_to_is_os(d, is_end)

        is_m = json.loads((d / "is" / "metrics.json").read_text()) if (d / "is" / "metrics.json").exists() else None
        os_m = json.loads((d / "os" / "metrics.json").read_text()) if (d / "os" / "metrics.json").exists() else None
        label_is, _ = classify_alpha(is_m, os_m=None) if is_m else ("NO_IS", "")
        label_full, _ = classify_alpha(is_m, os_m=os_m) if is_m else ("NO_IS", "")
        if label_is == "SUBMITTABLE":
            counts["is_sub"] += 1
        if label_full == "SUBMITTABLE":
            counts["full_sub"] += 1

        is_sharpe = (is_m or {}).get("sharpe")
        os_sharpe = (os_m or {}).get("sharpe")
        ic_mean_is = (is_m or {}).get("ic_mean")
        ic_ir_is = (is_m or {}).get("ic_ir")
        # Try to read strategy class from manifest
        strategy = ""
        mp = d / "manifest.json"
        if mp.exists():
            try:
                strategy = json.loads(mp.read_text()).get("strategy_name", "")
            except Exception:
                pass

        new_rows.append(
            f"{d.name},{strategy},{is_sharpe},"
            f"{(is_m or {}).get('total_return')},{(is_m or {}).get('total_trades')},"
            f"{os_sharpe},{(os_m or {}).get('total_return')},{(os_m or {}).get('total_trades')},"
            f"{ic_mean_is},{ic_ir_is},{label_is},{label_full}\n"
        )

    index_path.write_text("".join(new_rows))
    print(f"reprocessed {counts['total']} alphas: "
          f"IS-only SUBMITTABLE = {counts['is_sub']}  "
          f"IS+OS SUBMITTABLE = {counts['full_sub']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
