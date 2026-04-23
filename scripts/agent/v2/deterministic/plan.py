"""Parse PLAN.md into a typed config struct.

PLAN.md is the user's source of intent. The parser is permissive about
prose but strict about data:

    - The ``Targets``, ``Universe``, and ``IS / OS periods`` sections are
      required.
    - Key/value lines take the form ``<key>: <value>`` (whitespace tolerated).
    - Lines starting with ``#`` are comments and ignored.
    - User-supplied target values override defaults from
      ``config/targets.yaml``; missing keys fall back to defaults.

Invariants enforced at parse time:

    - IS window must end strictly before OS window starts.
    - IS window must be non-empty; OS window must be non-empty.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml


_TARGETS_DEFAULTS_PATH = (
    Path(__file__).resolve().parents[4] / "config" / "targets.yaml"
)


class PlanError(ValueError):
    """Raised when PLAN.md fails to parse or violates invariants."""


# ---------------------------------------------------------------------------
# Data class.
# ---------------------------------------------------------------------------


@dataclass
class PlanConfig:
    targets: dict[str, Any]
    symbols: list[str]
    is_start: date
    is_end: date
    os_start: date
    os_end: date
    strategy_request: str = ""
    notes: str = ""
    raw: str = field(default="", repr=False)


# ---------------------------------------------------------------------------
# Defaults loading.
# ---------------------------------------------------------------------------


def _load_default_targets() -> dict[str, Any]:
    data = yaml.safe_load(_TARGETS_DEFAULTS_PATH.read_text())
    return copy.deepcopy(data["defaults"])


# ---------------------------------------------------------------------------
# Section splitting.
# ---------------------------------------------------------------------------


_SECTION_RE = re.compile(r"^##\s+(?P<name>.+?)\s*$", re.MULTILINE)


def _split_sections(text: str) -> dict[str, str]:
    """Return ``{section_name: body}`` keyed by the ``##`` heading."""
    sections: dict[str, str] = {}
    matches = list(_SECTION_RE.finditer(text))
    for i, m in enumerate(matches):
        name = m.group("name").strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[name] = text[start:end].strip("\n")
    return sections


# ---------------------------------------------------------------------------
# Line parsing.
# ---------------------------------------------------------------------------


_KV_RE = re.compile(r"^\s*(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*:\s*(?P<value>.+?)\s*$")


def _parse_kv_lines(body: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        m = _KV_RE.match(line)
        if not m:
            continue
        out[m.group("key")] = m.group("value")
    return out


def _coerce_number(s: str) -> float | int:
    try:
        if "." in s or "e" in s or "E" in s:
            return float(s)
        return int(s)
    except ValueError as exc:
        raise PlanError(f"cannot parse numeric value {s!r}") from exc


def _parse_symbols(raw: str) -> list[str]:
    # Accept "[A, B, C]" or "A, B, C"
    s = raw.strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    parts = [p.strip() for p in s.split(",") if p.strip()]
    if not parts:
        raise PlanError("Universe.symbols is empty")
    return parts


def _parse_date(s: str) -> date:
    try:
        return date.fromisoformat(s.strip())
    except ValueError as exc:
        raise PlanError(f"invalid date {s!r} (expected YYYY-MM-DD)") from exc


# ---------------------------------------------------------------------------
# Targets merging.
# ---------------------------------------------------------------------------


# Map user-supplied keys to the ``(section, metric)`` location in the
# defaults tree. Keys not listed here are treated as budget overrides.
_TARGET_KEY_MAP = {
    "profit_factor": ("primary", "profit_factor"),
    "max_drawdown": ("primary", "max_drawdown"),
    "total_return": ("primary", "total_return"),
    "total_trades": ("primary", "total_trades"),
    "win_rate": ("secondary", "win_rate"),
    "sharpe": ("secondary", "sharpe"),
}

_BUDGET_KEYS = {"max_trials", "max_expressions_per_thesis", "max_theses_per_run"}


def _merge_targets(overrides: dict[str, str]) -> dict[str, Any]:
    merged = _load_default_targets()
    for key, raw_value in overrides.items():
        value = _coerce_number(raw_value)
        if key in _TARGET_KEY_MAP:
            section, metric = _TARGET_KEY_MAP[key]
            merged[section][metric]["value"] = value
        elif key in _BUDGET_KEYS:
            merged["budget"][key] = value
        else:
            # Unknown keys are tolerated but stashed under ``user_extras`` so
            # nothing is lost silently.
            merged.setdefault("user_extras", {})[key] = value
    return merged


# ---------------------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------------------


def parse(text: str) -> PlanConfig:
    sections = _split_sections(text)

    required = {"Targets", "Universe", "IS / OS periods"}
    missing = required - set(sections.keys())
    if missing:
        raise PlanError(f"PLAN.md missing required section(s): {sorted(missing)}")

    targets = _merge_targets(_parse_kv_lines(sections["Targets"]))
    symbols_raw = _parse_kv_lines(sections["Universe"]).get("symbols")
    if not symbols_raw:
        raise PlanError("Universe section missing `symbols:` line")
    symbols = _parse_symbols(symbols_raw)

    periods_kv = _parse_kv_lines(sections["IS / OS periods"])
    for key in ("is_start", "is_end", "os_start", "os_end"):
        if key not in periods_kv:
            raise PlanError(f"IS / OS periods missing `{key}`")

    is_start = _parse_date(periods_kv["is_start"])
    is_end = _parse_date(periods_kv["is_end"])
    os_start = _parse_date(periods_kv["os_start"])
    os_end = _parse_date(periods_kv["os_end"])

    if is_start >= is_end:
        raise PlanError("is_start must be strictly before is_end")
    if os_start >= os_end:
        raise PlanError("os_start must be strictly before os_end")
    if is_end >= os_start:
        raise PlanError(
            "IS window must end strictly before OS window starts — "
            f"is_end={is_end} vs os_start={os_start}"
        )

    strategy_request = sections.get("Strategy request", "").strip()
    notes = sections.get("Notes", "").strip()

    return PlanConfig(
        targets=targets,
        symbols=symbols,
        is_start=is_start,
        is_end=is_end,
        os_start=os_start,
        os_end=os_end,
        strategy_request=strategy_request,
        notes=notes,
        raw=text,
    )


def parse_file(path: Path) -> PlanConfig:
    return parse(Path(path).read_text())
