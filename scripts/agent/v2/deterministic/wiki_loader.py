"""Load the archive tree into a typed :class:`WikiInput` bundle.

Read-only. Never mutates the archive. Gracefully tolerates scaffolded-but-
unused runs and partially-written theses.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


_FRONTMATTER_RE = re.compile(r"^---\s*\n(?P<body>.*?)\n---\s*(?:\n|$)", re.DOTALL)


# ---------------------------------------------------------------------------
# Value types.
# ---------------------------------------------------------------------------


@dataclass
class ThesisRecord:
    run_id: str
    thesis_id: str
    fingerprint: str | None = None
    direction: str | None = None
    features: list[str] = field(default_factory=list)
    verdict_status: str | None = None


@dataclass
class WikiInput:
    expressions: list[dict]
    theses: list[ThesisRecord]


# ---------------------------------------------------------------------------
# Frontmatter parsing (lightweight — no yaml dependency for these small blocks).
# ---------------------------------------------------------------------------


def _parse_frontmatter(text: str) -> dict:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    body = m.group("body")
    # Use yaml for safety.
    import yaml

    try:
        data = yaml.safe_load(body) or {}
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _read_thesis(thesis_dir: Path, run_id: str) -> ThesisRecord | None:
    thesis_md = thesis_dir / "thesis.md"
    if not thesis_md.is_file():
        return None
    fm = _parse_frontmatter(thesis_md.read_text())
    record = ThesisRecord(
        run_id=run_id,
        thesis_id=thesis_dir.name,
        fingerprint=fm.get("fingerprint"),
        direction=fm.get("direction"),
        features=list(fm.get("features") or []),
    )
    verdict_md = thesis_dir / "verdict.md"
    if verdict_md.is_file():
        v_fm = _parse_frontmatter(verdict_md.read_text())
        record.verdict_status = v_fm.get("verdict")
    return record


def _read_expression_log(run_dir: Path) -> list[dict]:
    path = run_dir / "expression_log.jsonl"
    if not path.is_file():
        return []
    entries: list[dict] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # skip corrupt lines; loader is tolerant
    return entries


def _is_run_dir(candidate: Path) -> bool:
    if not candidate.is_dir():
        return False
    # A run dir has either expression_log.jsonl or theses/ inside.
    return (candidate / "expression_log.jsonl").exists() or (
        candidate / "theses"
    ).is_dir()


# ---------------------------------------------------------------------------
# Top-level load.
# ---------------------------------------------------------------------------


def load(archive_root: Path | str) -> WikiInput:
    archive = Path(archive_root)
    expressions: list[dict] = []
    theses: list[ThesisRecord] = []

    if not archive.is_dir():
        return WikiInput(expressions=[], theses=[])

    for entry in sorted(archive.iterdir()):
        if not _is_run_dir(entry):
            continue
        run_id = entry.name
        expressions.extend(_read_expression_log(entry))
        theses_dir = entry / "theses"
        if theses_dir.is_dir():
            for tdir in sorted(theses_dir.iterdir()):
                if not tdir.is_dir():
                    continue
                rec = _read_thesis(tdir, run_id)
                if rec is not None:
                    theses.append(rec)

    return WikiInput(expressions=expressions, theses=theses)


# ---------------------------------------------------------------------------
# Convenience accessors — keep loader thin, let builders use these helpers.
# ---------------------------------------------------------------------------


def refuted_fingerprints(wi: WikiInput) -> list[str]:
    out: list[str] = []
    for t in wi.theses:
        if t.verdict_status == "REFUTED" and t.fingerprint:
            out.append(t.fingerprint)
    return out


def expressions_by_feature(wi: WikiInput) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for e in wi.expressions:
        for f in e.get("features_used") or []:
            out[f].append(e)
    return dict(out)


def expressions_by_failure_mode(wi: WikiInput) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for e in wi.expressions:
        mode = e.get("failure_mode")
        if mode:
            out[mode].append(e)
    return dict(out)


def expressions_by_run(wi: WikiInput) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for e in wi.expressions:
        run_id = e.get("run_id")
        if run_id:
            out[run_id].append(e)
    return dict(out)
