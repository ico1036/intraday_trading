"""Append-only writer for ``archive/<run_id>/expression_log.jsonl``.

Validates every entry against the YAML enums before writing so that
downstream digests, gates, and wiki builds can trust the log without
re-parsing the configs.

Also fans out the failure_mode + spec to
``theses/<thesis_id>/seen_failure_modes.jsonl`` which is the scoped input
to ``thesis_gate.decide``.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# Config loading — once, at import time. YAMLs are small.
# ---------------------------------------------------------------------------


_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


def _load_yaml(name: str) -> dict[str, Any]:
    return yaml.safe_load((_CONFIG_DIR / name).read_text())


_AXES = _load_yaml("expression_axes.yaml")["axes"]
_FEATURES = frozenset(_load_yaml("feature_vocab.yaml")["features"].keys())
_FAILURE_MODES = frozenset(_load_yaml("failure_modes.yaml")["modes"].keys())

AXIS_KEYS: frozenset[str] = frozenset(_AXES.keys())
AXIS_VALUES: dict[str, frozenset[str]] = {
    k: frozenset(spec["values"]) for k, spec in _AXES.items()
}

# APPROVED is not a failure, but is a valid terminal tag written to the log.
_VALID_FAILURE_TAGS = _FAILURE_MODES | {"APPROVED"}
_VALID_VERDICTS = frozenset(
    ["ACTIVE", "EXHAUSTED", "REFUTED", "SCOPE_RESTRICTED", "APPROVED"]
)

_THESIS_ID_RE = re.compile(r"^th_\d{3,}$")
_EXPRESSION_ID_RE = re.compile(r"^exp_\d{3,}$")


# ---------------------------------------------------------------------------
# Errors.
# ---------------------------------------------------------------------------


class ExpressionLogError(ValueError):
    """Raised when an entry fails validation or I/O cannot proceed."""


# ---------------------------------------------------------------------------
# Entry struct.
# ---------------------------------------------------------------------------


@dataclass
class ExpressionLogEntry:
    run_id: str
    thesis_id: str
    expression_id: str
    expression_spec: dict[str, str]
    features_used: list[str]
    failure_mode: str
    verdict_after: str
    artifact_path: str
    result: dict[str, Any] | None = None
    addresses: str | None = None
    ts: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    def to_json_dict(self) -> dict[str, Any]:
        out = asdict(self)
        # Normalise: drop None-valued optional keys for leaner lines.
        for optional in ("result", "addresses"):
            if out.get(optional) is None:
                out.pop(optional)
        return out


# ---------------------------------------------------------------------------
# Validation.
# ---------------------------------------------------------------------------


def _validate(entry: ExpressionLogEntry) -> None:
    if not _THESIS_ID_RE.match(entry.thesis_id):
        raise ExpressionLogError(
            f"thesis_id {entry.thesis_id!r} must match r'{_THESIS_ID_RE.pattern}'"
        )
    if not _EXPRESSION_ID_RE.match(entry.expression_id):
        raise ExpressionLogError(
            f"expression_id {entry.expression_id!r} must match r'{_EXPRESSION_ID_RE.pattern}'"
        )

    for axis, value in entry.expression_spec.items():
        if axis not in AXIS_KEYS:
            raise ExpressionLogError(
                f"unknown axis {axis!r}; allowed: {sorted(AXIS_KEYS)}"
            )
        if value not in AXIS_VALUES[axis]:
            raise ExpressionLogError(
                f"axis {axis!r} value {value!r} not in "
                f"{sorted(AXIS_VALUES[axis])}"
            )

    for feat in entry.features_used:
        if feat not in _FEATURES:
            raise ExpressionLogError(
                f"feature {feat!r} not in feature_vocab.yaml"
            )

    if entry.failure_mode not in _VALID_FAILURE_TAGS:
        raise ExpressionLogError(
            f"failure_mode {entry.failure_mode!r} not in "
            f"{sorted(_VALID_FAILURE_TAGS)}"
        )

    if entry.verdict_after not in _VALID_VERDICTS:
        raise ExpressionLogError(
            f"verdict_after {entry.verdict_after!r} not in "
            f"{sorted(_VALID_VERDICTS)}"
        )


# ---------------------------------------------------------------------------
# Append.
# ---------------------------------------------------------------------------


def _append_line(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n")


def append(run_dir: Path | str, entry: ExpressionLogEntry) -> None:
    """Validate, then atomically append to the run log and the thesis log.

    Validation failures must not leave partial on-disk state.
    """
    _validate(entry)  # raises before we touch disk

    run_dir = Path(run_dir)
    log_path = run_dir / "expression_log.jsonl"
    seen_path = run_dir / "theses" / entry.thesis_id / "seen_failure_modes.jsonl"

    payload = entry.to_json_dict()
    _append_line(log_path, payload)
    _append_line(
        seen_path,
        {
            "expression_id": entry.expression_id,
            "failure_mode": entry.failure_mode,
            "expression_spec": entry.expression_spec,
        },
    )
