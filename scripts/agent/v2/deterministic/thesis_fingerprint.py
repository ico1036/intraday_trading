"""Canonical fingerprint for a thesis.

Two theses with identical canonical form share a fingerprint even if their
English prose differs. The fingerprint is stored in:

    - ``archive/<run_id>/theses/<thesis_id>/thesis.md`` frontmatter, and
    - ``wiki/cross_run/refuted_theses.md`` for duplicate detection across
      runs.

Determinism is critical: same inputs on any machine on any day must yield
the same fingerprint. We therefore hash a JSON dump with sorted keys, no
whitespace, and an explicit pre-hash normalisation pass.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml


_FEATURE_VOCAB_PATH = (
    Path(__file__).resolve().parents[4] / "config" / "feature_vocab.yaml"
)
_FRONTMATTER_RE = re.compile(
    r"^---\s*\n(?P<body>.*?)\n---\s*(?:\n|$)", re.DOTALL
)


class ThesisValidationError(ValueError):
    """Raised when thesis inputs are missing or malformed."""


def _load_vocab() -> frozenset[str]:
    data = yaml.safe_load(_FEATURE_VOCAB_PATH.read_text())
    return frozenset(data["features"].keys())


FEATURE_VOCAB: frozenset[str] = _load_vocab()


def _normalise_features(features: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    materialised = list(features)
    if not materialised:
        raise ThesisValidationError("features must be a non-empty list")
    for name in materialised:
        if not isinstance(name, str):
            raise ThesisValidationError(
                f"feature must be a string, got {type(name).__name__}: {name!r}"
            )
        key = name.strip().lower()
        if key not in FEATURE_VOCAB:
            raise ThesisValidationError(
                f"feature {key!r} not in feature_vocab.yaml"
            )
        if key not in seen:
            seen.add(key)
            ordered.append(key)
    return sorted(ordered)


def _normalise_direction(direction: str) -> str:
    if not isinstance(direction, str) or not direction.strip():
        raise ThesisValidationError("direction must be non-empty string")
    return direction.strip().lower()


def _normalise_trigger_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(schema, Mapping) or not schema:
        raise ThesisValidationError("trigger_schema must be non-empty mapping")
    # Recursively sort dict keys and stringify leaves for hash stability.
    return json.loads(json.dumps(schema, sort_keys=True, default=str))


def fingerprint(
    *,
    direction: str,
    features: Iterable[str],
    trigger_schema: Mapping[str, Any],
) -> str:
    """Return ``sha256:<64 hex chars>`` for a canonicalised thesis."""
    canonical = {
        "direction": _normalise_direction(direction),
        "features": _normalise_features(features),
        "trigger_schema": _normalise_trigger_schema(trigger_schema),
    }
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def fingerprint_from_markdown(text: str) -> str:
    """Parse YAML frontmatter from ``thesis.md`` and compute the fingerprint."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise ThesisValidationError("thesis markdown missing YAML frontmatter")

    try:
        data = yaml.safe_load(match.group("body")) or {}
    except yaml.YAMLError as exc:
        raise ThesisValidationError(f"invalid YAML frontmatter: {exc}") from exc

    for key in ("direction", "features", "trigger_schema"):
        if key not in data:
            raise ThesisValidationError(
                f"thesis markdown frontmatter missing {key!r}"
            )

    return fingerprint(
        direction=data["direction"],
        features=data["features"],
        trigger_schema=data["trigger_schema"],
    )
