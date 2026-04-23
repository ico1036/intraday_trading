"""Parse and render v2 ``algorithm_prompt.txt`` files.

A v2 prompt has YAML frontmatter (required fields) and free-form markdown
body. Validation uses the same enums as :mod:`expression_log` so both
writers agree on what a well-formed prompt looks like.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from scripts.agent.v2 import expression_log as _elog


class AlgorithmPromptError(ValueError):
    """Raised when a prompt cannot be parsed or fails schema validation."""


_FRONTMATTER_RE = re.compile(
    r"^---\s*\n(?P<fm>.*?)\n---\s*\n(?P<body>.*)$",
    re.DOTALL,
)

_REQUIRED_FIELDS = ("thesis_id", "expression_id", "expression_spec", "features_used")


# ---------------------------------------------------------------------------
# Struct.
# ---------------------------------------------------------------------------


@dataclass
class AlgorithmPrompt:
    thesis_id: str
    expression_id: str
    expression_spec: dict[str, str]
    features_used: list[str]
    addresses: str | None
    body: str


# ---------------------------------------------------------------------------
# Validation.
# ---------------------------------------------------------------------------


def _validate(
    thesis_id: str,
    expression_id: str,
    expression_spec: dict[str, str],
    features_used: list[str],
) -> None:
    if not _elog._THESIS_ID_RE.match(thesis_id):
        raise AlgorithmPromptError(
            f"thesis_id {thesis_id!r} must match r'{_elog._THESIS_ID_RE.pattern}'"
        )
    if not _elog._EXPRESSION_ID_RE.match(expression_id):
        raise AlgorithmPromptError(
            f"expression_id {expression_id!r} must match r'{_elog._EXPRESSION_ID_RE.pattern}'"
        )
    for axis, value in expression_spec.items():
        if axis not in _elog.AXIS_KEYS:
            raise AlgorithmPromptError(f"unknown axis {axis!r}")
        if value not in _elog.AXIS_VALUES[axis]:
            raise AlgorithmPromptError(
                f"axis {axis!r} value {value!r} not in enum"
            )
    for feat in features_used:
        if feat not in _elog._FEATURES:
            raise AlgorithmPromptError(
                f"feature {feat!r} not in feature_vocab.yaml"
            )


# ---------------------------------------------------------------------------
# Parse.
# ---------------------------------------------------------------------------


def parse(text: str) -> AlgorithmPrompt:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise AlgorithmPromptError("algorithm_prompt missing YAML frontmatter")

    try:
        data = yaml.safe_load(m.group("fm")) or {}
    except yaml.YAMLError as exc:
        raise AlgorithmPromptError(f"invalid YAML frontmatter: {exc}") from exc

    if not isinstance(data, dict):
        raise AlgorithmPromptError("frontmatter must be a mapping")

    for key in _REQUIRED_FIELDS:
        if key not in data:
            raise AlgorithmPromptError(
                f"algorithm_prompt frontmatter missing {key!r}"
            )

    expression_spec = dict(data["expression_spec"] or {})
    features_used = list(data["features_used"] or [])

    _validate(
        thesis_id=data["thesis_id"],
        expression_id=data["expression_id"],
        expression_spec=expression_spec,
        features_used=features_used,
    )

    return AlgorithmPrompt(
        thesis_id=data["thesis_id"],
        expression_id=data["expression_id"],
        expression_spec=expression_spec,
        features_used=features_used,
        addresses=data.get("addresses"),
        body=m.group("body"),
    )


def parse_file(path: Path | str) -> AlgorithmPrompt:
    return parse(Path(path).read_text())


# ---------------------------------------------------------------------------
# Build / write.
# ---------------------------------------------------------------------------


def build(
    *,
    thesis_id: str,
    expression_id: str,
    expression_spec: dict[str, str],
    features_used: list[str],
    addresses: str | None,
    body: str,
) -> str:
    _validate(thesis_id, expression_id, expression_spec, features_used)

    # Produce a deterministic frontmatter: sorted keys, preserving enum order
    # for expression_spec per the YAML axes file.
    fm_data: dict[str, Any] = {
        "thesis_id": thesis_id,
        "expression_id": expression_id,
        "expression_spec": {
            k: expression_spec[k] for k in sorted(expression_spec.keys())
        },
        "features_used": list(features_used),
    }
    if addresses is not None:
        fm_data["addresses"] = addresses

    fm_yaml = yaml.safe_dump(
        fm_data,
        sort_keys=False,
        default_flow_style=False,
    ).rstrip()

    body_out = body if body.endswith("\n") else body + "\n"
    return f"---\n{fm_yaml}\n---\n\n{body_out}"


def write_file(
    path: Path | str,
    *,
    thesis_id: str,
    expression_id: str,
    expression_spec: dict[str, str],
    features_used: list[str],
    addresses: str | None,
    body: str,
) -> Path:
    text = build(
        thesis_id=thesis_id,
        expression_id=expression_id,
        expression_spec=expression_spec,
        features_used=features_used,
        addresses=addresses,
        body=body,
    )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path
