"""Overlapping-window integrity check for tick strategies.

Strategy adapted from ``vectest/integrity.py`` (stock harness): run the
backtester over N overlapping windows, and for each pair compare trades
produced on the shared sub-window. Any divergence after warmup indicates
look-ahead bias or path-dependent state.

This module exposes the pure algorithm. A thin runner adapter (``run_suite``)
wires it to ``TickBacktestRunner`` — tested separately.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Sequence


# ---------------------------------------------------------------------------
# Errors & value types.
# ---------------------------------------------------------------------------


class IntegrityError(ValueError):
    """Raised when inputs cannot be compared coherently."""


@dataclass(frozen=True)
class TradeEvent:
    ts: datetime
    side: str
    qty: float
    price: float

    def canonical(self) -> tuple[str, str, float, float]:
        """Hashable tuple for set comparison. Rounds to sane precision."""
        return (
            self.ts.isoformat(),
            self.side.upper(),
            round(self.qty, 8),
            round(self.price, 4),
        )


@dataclass
class Divergence:
    run_a: int
    run_b: int
    shared_window: tuple[date, date]
    missing_in_b: list[TradeEvent] = field(default_factory=list)
    extra_in_b: list[TradeEvent] = field(default_factory=list)


@dataclass
class IntegrityReport:
    clean: bool
    divergences: list[Divergence]
    shared_windows: list[tuple[date, date]]
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Algorithm.
# ---------------------------------------------------------------------------


def _window_overlap(
    a: tuple[date, date], b: tuple[date, date]
) -> tuple[date, date] | None:
    start = max(a[0], b[0])
    end = min(a[1], b[1])
    return (start, end) if start <= end else None


def _filter_to_window(
    trades: Sequence[TradeEvent],
    window: tuple[date, date],
    warmup: timedelta,
    window_starts: tuple[date, date],
) -> list[TradeEvent]:
    """Keep trades inside ``window`` AND outside the per-run warmup zones.

    ``window_starts`` is the (run_a_start, run_b_start). A trade is excluded
    if it falls within ``warmup`` of EITHER run's start, since each run's
    early ticks can carry different initialisation state.
    """
    wa_start, wb_start = window_starts
    cutoff_a = datetime.combine(wa_start, datetime.min.time()) + warmup
    cutoff_b = datetime.combine(wb_start, datetime.min.time()) + warmup
    warmup_floor = max(cutoff_a, cutoff_b)

    start_ts = datetime.combine(window[0], datetime.min.time())
    end_ts = datetime.combine(window[1], datetime.max.time())
    effective_start = max(start_ts, warmup_floor)

    # If warmup pushes past the window, treat as tz-aware against naive:
    # trades carry tzinfo → compare with aware timestamps.
    def _aware(dt: datetime, ref: datetime) -> datetime:
        if ref.tzinfo is None:
            return dt
        return dt.replace(tzinfo=ref.tzinfo) if dt.tzinfo is None else dt

    kept: list[TradeEvent] = []
    for t in trades:
        tstart = _aware(effective_start, t.ts)
        tend = _aware(end_ts, t.ts)
        if tstart <= t.ts <= tend:
            kept.append(t)
    return kept


def check(
    *,
    trade_sets: Sequence[Sequence[TradeEvent]],
    windows: Sequence[tuple[date, date]],
    warmup: timedelta = timedelta(0),
) -> IntegrityReport:
    """Compare trade sets pairwise on shared windows."""
    if len(trade_sets) != len(windows):
        raise IntegrityError(
            f"trade_sets and windows length mismatch: "
            f"{len(trade_sets)} vs {len(windows)}"
        )
    if len(trade_sets) < 2:
        raise IntegrityError("need at least 2 runs to compare")

    divergences: list[Divergence] = []
    shared: list[tuple[date, date]] = []

    for i in range(len(trade_sets)):
        for j in range(i + 1, len(trade_sets)):
            overlap = _window_overlap(windows[i], windows[j])
            if overlap is None:
                continue
            shared.append(overlap)

            a_filtered = _filter_to_window(
                trade_sets[i],
                overlap,
                warmup,
                (windows[i][0], windows[j][0]),
            )
            b_filtered = _filter_to_window(
                trade_sets[j],
                overlap,
                warmup,
                (windows[i][0], windows[j][0]),
            )

            set_a = {t.canonical(): t for t in a_filtered}
            set_b = {t.canonical(): t for t in b_filtered}

            missing_in_b = [t for k, t in set_a.items() if k not in set_b]
            extra_in_b = [t for k, t in set_b.items() if k not in set_a]

            if missing_in_b or extra_in_b:
                divergences.append(
                    Divergence(
                        run_a=i,
                        run_b=j,
                        shared_window=overlap,
                        missing_in_b=missing_in_b,
                        extra_in_b=extra_in_b,
                    )
                )

    notes: list[str] = []
    if not shared:
        notes.append("no_overlap")

    return IntegrityReport(
        clean=not divergences,
        divergences=divergences,
        shared_windows=shared,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Report rendering.
# ---------------------------------------------------------------------------


def render_markdown(report: IntegrityReport) -> str:
    lines = ["# Integrity Report", ""]
    if report.clean:
        lines.append("**Status: CLEAN** — no divergences across shared windows.")
    else:
        lines.append(
            f"**Status: DIVERGENT** — "
            f"{len(report.divergences)} pair(s) disagree on shared windows."
        )
    lines.append("")

    if report.shared_windows:
        lines.append("## Shared windows")
        for w in report.shared_windows:
            lines.append(f"- {w[0]} → {w[1]}")
    else:
        lines.append("## Shared windows")
        lines.append("- _none_")
    lines.append("")

    if report.divergences:
        lines.append("## Divergences")
        for d in report.divergences:
            lines.append(
                f"- runs {d.run_a} vs {d.run_b} on "
                f"[{d.shared_window[0]} → {d.shared_window[1]}]"
            )
            if d.missing_in_b:
                lines.append(
                    f"  - trades present in {d.run_a} but missing in {d.run_b}: "
                    f"{len(d.missing_in_b)}"
                )
            if d.extra_in_b:
                lines.append(
                    f"  - extra trades in {d.run_b}: {len(d.extra_in_b)}"
                )

    if report.notes:
        lines.append("")
        lines.append("## Notes")
        for n in report.notes:
            lines.append(f"- {n}")

    return "\n".join(lines) + "\n"
