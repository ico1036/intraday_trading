"""Rerun every archived alpha through the current engine (funding + slippage).

Reconstructs each alpha's command from what the archive stores:
strategy class, symbols, bar type and size from ``is/summary.json``
(artifact v1) or ``metrics.json`` (v2); strategy params from the run's
``queue.json`` variant or a ``## <alpha_id>`` JSON block in ``LOG.md``;
IS/OS windows from ``splits.json``. Runs IS into ``is/`` and, when an ``os/``
directory exists, OS into ``os/``, then ``validate_is_os.py`` and the
alpha index. Old composites (``archive/composites/<id>/inputs``) are replayed
with ``PrecomputedWeightsStrategy``.

Resumable: an alpha whose ``is/metrics.json`` already carries ``costs`` is
skipped unless ``--force``. Failures are logged and do not stop the run.

    uv run python scripts/governance/rerun_archive_with_costs.py --run-id tv_100_20260505 --workers 4
    uv run python scripts/governance/rerun_archive_with_costs.py --composites
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ARCHIVE = REPO / "archive"
BACKTEST = REPO / "scripts" / "tools" / "backtest.py"
VALIDATE = REPO / "scripts" / "tools" / "validate_is_os.py"
DEFAULT_DATA_PATH = "data/futures_klines"
DEFAULT_SYMBOLS = ["ADAUSDT", "BNBUSDT", "BTCUSDT", "DOGEUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]


def _load(p: Path) -> dict:
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _queue_params(run_dir: Path) -> dict[str, dict]:
    q = _load(run_dir / "queue.json")
    out = {}
    for v in q.get("variants", []) if isinstance(q, dict) else []:
        if isinstance(v, dict) and "alpha_id" in v:
            out[v["alpha_id"]] = dict(v.get("params") or {})
    return out


def _log_params(run_dir: Path) -> dict[str, dict]:
    """``## <alpha_id>`` followed by a ```json block with a "params" key."""
    p = run_dir / "LOG.md"
    if not p.exists():
        return {}
    out = {}
    text = p.read_text()
    for m in re.finditer(r"^## (\S+)\s*\n+```json\n(.*?)\n```", text, re.S | re.M):
        try:
            d = json.loads(m.group(2))
        except Exception:
            continue
        if isinstance(d, dict) and isinstance(d.get("params"), dict):
            out[m.group(1)] = dict(d["params"])
    return out


def _describe(alpha_dir: Path, split: str) -> dict:
    """strategy, symbols, bar_type, bar_size for one split."""
    for cand in (alpha_dir / split / "summary.json", alpha_dir / split / "metrics.json", alpha_dir / "metrics.json"):
        m = _load(cand)
        if not m:
            continue
        strat = m.get("strategy_name") or m.get("strategy_class")
        if strat:
            return {
                "strategy": strat,
                "symbols": m.get("symbols") or _load(alpha_dir / split / "manifest.json").get("symbols") or DEFAULT_SYMBOLS,
                "bar_type": str(m.get("bar_type") or "time").upper(),
                "bar_size": float(m.get("bar_size") or 60.0),
                "initial_capital": float(m.get("initial_capital") or 10000.0),
            }
    return {}


def _cmd(desc: dict, params: dict | None, start: str, end: str, out_dir: Path, data_path: str, extra: list[str]) -> list[str]:
    cmd = [sys.executable, str(BACKTEST), "--strategy", desc["strategy"], "--symbols", *desc["symbols"],
           "--data-type", "bars", "--data-path", data_path, "--start", start, "--end", end,
           "--bar-type", desc["bar_type"], "--bar-size", str(desc["bar_size"]),
           "--initial-capital", str(desc["initial_capital"]),
           "--output-dir", str(out_dir), "--no-enforce-quality", "--no-enforce-governance", "--json", *extra]
    if params:
        cmd += ["--strategy-params", json.dumps(params)]
    return cmd


def _run(cmd: list[str], timeout: int) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=timeout,
                           env={**__import__("os").environ, "SEAL_OPEN": "1"})
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    tail = (p.stdout or "")[-4000:]
    m = re.search(r'"error": "([^"]{0,200})', tail)
    return p.returncode, (m.group(1) if m else (p.stderr or "")[-300:])


def _refresh_summary(split_dir: Path) -> None:
    """Keep the v1 summary.json honest after a rerun."""
    s = _load(split_dir / "summary.json")
    m = _load(split_dir / "metrics.json")
    if not s or not m:
        return
    for k in ("initial_capital", "final_capital", "total_return", "generated_at", "started_at", "ended_at",
              "tick_counts", "bar_counts"):
        if k in m:
            s[k] = m[k]
    s["costs"] = m.get("costs")
    s["annualization_days"] = m.get("annualization_days")
    s["rerun_with_costs"] = datetime.now().isoformat(timespec="seconds")
    (split_dir / "summary.json").write_text(json.dumps(s, indent=2, default=str))


def rerun_alpha(run_dir: Path, alpha_dir: Path, splits: dict, params: dict | None, data_path: str,
                timeout: int, force: bool, extra: list[str]) -> dict:
    t0 = time.time()
    res = {"alpha": alpha_dir.name, "splits": {}, "ok": True}
    for split in ("is", "os"):
        sdir = alpha_dir / split
        if not sdir.is_dir() or split not in splits:
            continue
        if not force and "costs" in _load(sdir / "metrics.json"):
            res["splits"][split] = "skip"
            continue
        desc = _describe(alpha_dir, split)
        if not desc:
            res["splits"][split] = "no description"
            res["ok"] = False
            continue
        rc, err = _run(_cmd(desc, params, splits[split]["start"], splits[split]["end"], sdir, data_path, extra), timeout)
        # backtest.py exits 2 on a quality-gate reject even with enforcement
        # off; the artefacts are written, so only a missing costs block fails.
        if rc not in (0, 2) or not (sdir / "metrics.json").exists() or "costs" not in _load(sdir / "metrics.json"):
            res["splits"][split] = f"FAIL rc={rc} {err[:160]}"
            res["ok"] = False
            break
        _refresh_summary(sdir)
        res["splits"][split] = "ok"
    if res["ok"] and (alpha_dir / "os").is_dir() and (alpha_dir / "is").is_dir() and "os" in splits:
        rc, _ = _run([sys.executable, str(VALIDATE), "--alpha-dir", str(alpha_dir), "--json"], 300)
        res["validated"] = rc == 0
    res["seconds"] = round(time.time() - t0, 1)
    return res


def rerun_run(run_id: str, workers: int, timeout: int, force: bool, limit: int, data_path: str, extra: list[str]) -> None:
    run_dir = ARCHIVE / run_id
    splits = _load(run_dir / "splits.json")
    if not splits.get("is"):
        print(f"{run_id}: no splits.json with an IS window", file=sys.stderr)
        return
    params = _queue_params(run_dir)
    params.update({k: v for k, v in _log_params(run_dir).items() if k not in params})
    alphas = sorted(p for p in (run_dir / "alphas").iterdir() if p.is_dir() and ((p / "is").is_dir() or (p / "metrics.json").exists()))
    if limit:
        alphas = alphas[:limit]
    log = run_dir / f"rerun_costs_{datetime.now():%Y%m%d}.log"
    print(f"{run_id}: {len(alphas)} alphas, {len(params)} with params, workers={workers}", file=sys.stderr, flush=True)
    done = fail = 0
    with ThreadPoolExecutor(max_workers=workers) as ex, log.open("a") as fh:
        futs = {ex.submit(rerun_alpha, run_dir, a, splits, (dict(params[a.name], alpha_id=a.name) if a.name in params else None),
                          data_path, timeout, force, extra): a for a in alphas}
        for f in as_completed(futs):
            r = f.result()
            done += 1
            fail += 0 if r["ok"] else 1
            line = json.dumps(r)
            fh.write(line + "\n"); fh.flush()
            print(f"[{done}/{len(alphas)}] {r['alpha']} {r['splits']} {r.get('seconds','')}s", file=sys.stderr, flush=True)
    print(f"{run_id}: done {done}, failed {fail}", file=sys.stderr, flush=True)
    subprocess.run([sys.executable, str(REPO / "scripts" / "governance" / "build_alpha_index.py"), "--run-id", run_id],
                   cwd=REPO, capture_output=True)


def rerun_composites(timeout: int, force: bool, data_path: str) -> None:
    for c in sorted(p for p in (ARCHIVE / "composites").iterdir() if p.is_dir()):
        w = c / "inputs" / "combined_weights.parquet"
        sdir = c / "is"
        if not w.exists() or not sdir.is_dir():
            continue
        if not force and "costs" in _load(sdir / "metrics.json"):
            print(f"composite {c.name}: skip", file=sys.stderr); continue
        desc = _describe(c, "is")
        s = _load(sdir / "summary.json")
        start, end = str(s.get("started_at", "2026-03-04 00:00:00")).replace("T", " "), str(s.get("ended_at", "2026-04-17 23:59:00")).replace("T", " ")
        desc["strategy"] = "PrecomputedWeightsStrategy"
        rc, err = _run(_cmd(desc, {"weights_path": str(w), "alpha_id": c.name}, start, end, sdir, data_path, []), timeout)
        ok = rc in (0, 2) and "costs" in _load(sdir / "metrics.json")
        print(f"composite {c.name}: {'ok' if ok else 'FAIL ' + err[:120]}", file=sys.stderr, flush=True)
        if ok:
            _refresh_summary(sdir)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", action="append", default=[])
    ap.add_argument("--composites", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--timeout", type=int, default=1800, help="seconds per backtest")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--data-path", default=DEFAULT_DATA_PATH)
    ap.add_argument("--extra", default="", help="extra backtest.py args, space separated")
    a = ap.parse_args()
    extra = a.extra.split() if a.extra else []
    for run_id in a.run_id:
        rerun_run(run_id, a.workers, a.timeout, a.force, a.limit, a.data_path, extra)
    if a.composites:
        rerun_composites(a.timeout, a.force, a.data_path)


if __name__ == "__main__":
    main()
