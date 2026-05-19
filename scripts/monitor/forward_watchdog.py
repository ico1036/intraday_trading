#!/usr/bin/env python3
"""Forward-runner staleness watchdog.

Polls every forward/ dir under ``archive/<run>/alphas/<aid>/forward/``,
reads the most recent ``weights.parquet`` timestamp, and alerts via
Telegram if the gap to wall-clock exceeds ``candle_size × multiplier``.

Daily alphas should emit at least every 24h (multiplier 1.5 → alerts
after ~36h of silence). The xs_volume_rank 4-day stuck would have
fired ~3 alerts before going unnoticed.

Bot token comes from ``~/.claude/channels/telegram/.env`` (the same one
the Claude Code telegram plugin uses). The owner's chat id is read
from ``~/.claude/channels/telegram/access.json`` (``allowFrom[0]``) —
no separate config to drift.

Run:
    SEAL_OPEN=1 uv run python scripts/monitor/forward_watchdog.py \\
        --archive-root archive \\
        --poll-interval-sec 600 \\
        --threshold-multiplier 1.5

For one-shot health check: ``--once``.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import pandas as pd


def _load_telegram_creds() -> tuple[str, str] | None:
    """Return (bot_token, chat_id) or None if either is missing."""
    env_path = Path.home() / ".claude" / "channels" / "telegram" / ".env"
    access_path = Path.home() / ".claude" / "channels" / "telegram" / "access.json"
    token = None
    if env_path.exists():
        for raw in env_path.read_text().splitlines():
            line = raw.strip()
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                token = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
    chat_id = None
    if access_path.exists():
        try:
            allow = json.loads(access_path.read_text()).get("allowFrom") or []
            if allow:
                chat_id = str(allow[0])
        except Exception:
            chat_id = None
    if not token or not chat_id:
        return None
    return token, chat_id


def send_telegram(message: str) -> bool:
    creds = _load_telegram_creds()
    if not creds:
        print("[watchdog] no telegram creds; printing to stderr instead", file=sys.stderr)
        print(message, file=sys.stderr)
        return False
    token, chat_id = creds
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
    }).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return 200 <= resp.status < 300
    except Exception as exc:  # noqa: BLE001
        print(f"[watchdog] telegram send failed: {exc}", file=sys.stderr)
        return False


def _last_weight_emit(fwd_dir: Path) -> _dt.datetime | None:
    """Most recent emit timestamp in weights.parquet, or None if missing."""
    p = fwd_dir / "weights.parquet"
    if not p.exists():
        return None
    try:
        df = pd.read_parquet(p, columns=["timestamp"])
    except Exception:
        return None
    if df.empty or "timestamp" not in df.columns:
        return None
    ts = pd.to_datetime(df["timestamp"]).max()
    if pd.isna(ts):
        return None
    val = ts.to_pydatetime()
    if val.tzinfo is None:
        val = val.replace(tzinfo=_dt.timezone.utc)
    return val


def _candle_size_sec(fwd_dir: Path) -> float | None:
    """Best-effort candle period inference.

    1. ``manifest.json`` / ``summary.json`` ``bar_size`` (backtest schema).
    2. Median spacing between unique emit timestamps in weights.parquet —
       a daily strategy emits ~86400s apart, a 1-min strategy ~60s.
    Falls back to None when neither source is usable.
    """
    for name in ("manifest.json", "summary.json"):
        m = fwd_dir / name
        if not m.exists():
            continue
        try:
            info = json.loads(m.read_text())
        except Exception:
            continue
        val = info.get("bar_size")
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass

    p = fwd_dir / "weights.parquet"
    if not p.exists():
        return None
    try:
        df = pd.read_parquet(p, columns=["timestamp"])
    except Exception:
        return None
    if df.empty or "timestamp" not in df.columns:
        return None
    ts = pd.to_datetime(df["timestamp"]).drop_duplicates().sort_values()
    if len(ts) < 2:
        return None
    diffs = ts.diff().dt.total_seconds().dropna()
    if diffs.empty:
        return None
    val = float(diffs.median())
    return val if val > 0 else None


def _pid_alive(fwd_dir: Path) -> bool | None:
    """Return True/False/None — None if no pid file."""
    pid_path = fwd_dir / "pid.txt"
    if not pid_path.exists():
        return None
    try:
        pid = int(pid_path.read_text().strip())
    except (ValueError, OSError):
        return None
    if pid <= 0:
        return None
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def scan_once(
    archive_root: Path,
    threshold_multiplier: float,
    alert_state: dict[str, _dt.datetime],
    cooldown_sec: float,
) -> list[str]:
    """Inspect every forward/ dir under archive/<run>/alphas/. Return
    alert messages sent (after cooldown filter)."""
    sent: list[str] = []
    now = _dt.datetime.now(_dt.timezone.utc)
    for fwd_dir in archive_root.glob("*/alphas/*/forward"):
        alpha_id = fwd_dir.parent.name
        run_id = fwd_dir.parents[2].name
        key = f"{run_id}/{alpha_id}"
        pid_alive = _pid_alive(fwd_dir)
        last_ts = _last_weight_emit(fwd_dir)
        candle_sec = _candle_size_sec(fwd_dir)
        if candle_sec is None or candle_sec <= 0 or last_ts is None:
            continue
        gap_sec = (now - last_ts).total_seconds()
        threshold = candle_sec * threshold_multiplier
        if gap_sec <= threshold:
            # Healthy — clear any prior alert state so a future stall re-alerts.
            alert_state.pop(key, None)
            continue
        prev_alert = alert_state.get(key)
        if prev_alert is not None and (now - prev_alert).total_seconds() < cooldown_sec:
            continue  # within cooldown
        alert_state[key] = now
        gap_hours = gap_sec / 3600
        threshold_hours = threshold / 3600
        msg = (
            f"⚠️ <b>forward stall</b>\n"
            f"alpha: <code>{key}</code>\n"
            f"last emit: <code>{last_ts.isoformat()}</code>\n"
            f"gap: <b>{gap_hours:.1f}h</b> (threshold {threshold_hours:.1f}h)\n"
            f"pid alive: {pid_alive}\n"
            f"dir: <code>{fwd_dir}</code>"
        )
        send_telegram(msg)
        sent.append(key)
    return sent


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive-root", default="archive", type=Path)
    p.add_argument("--poll-interval-sec", default=600, type=float)
    p.add_argument("--threshold-multiplier", default=1.5, type=float,
                   help="Alert when (now - last_emit) > candle_size_sec × this.")
    p.add_argument("--cooldown-sec", default=21600.0, type=float,
                   help="Per-alpha alert cooldown to avoid spam (default 6h).")
    p.add_argument("--once", action="store_true",
                   help="Run a single scan and exit (for testing / cron).")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    alert_state: dict[str, _dt.datetime] = {}
    archive_root = args.archive_root.resolve()
    if not archive_root.exists():
        print(f"[watchdog] archive root not found: {archive_root}", file=sys.stderr)
        return 1
    print(f"[watchdog] poll every {args.poll_interval_sec}s; "
          f"threshold = {args.threshold_multiplier}× candle_size",
          flush=True)
    while True:
        try:
            sent = scan_once(archive_root, args.threshold_multiplier,
                             alert_state, args.cooldown_sec)
            if sent:
                print(f"[watchdog] alerted: {sent}", flush=True)
            else:
                print(f"[watchdog] {_dt.datetime.now().isoformat(timespec='seconds')} "
                      f"healthy", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[watchdog] scan error: {exc}", file=sys.stderr, flush=True)
        if args.once:
            return 0
        time.sleep(args.poll_interval_sec)


if __name__ == "__main__":
    sys.exit(main())
