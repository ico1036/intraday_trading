"""Page renderers for ``wiki/facts/``.

Each function is a pure (WikiInput, key) → markdown transform. Output
must be deterministic: sort every iteration by (run_id, thesis_id,
expression_id) before rendering.

Confidence rule (sim2-compatible):
    n >= 5  → high
    n >= 2  → medium
    n == 1  → low
    n == 0  → skip (return empty string)
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Mapping

import yaml

from scripts.agent.v2.deterministic import wiki_loader as wl


_FAILURE_MODES_PATH = (
    Path(__file__).resolve().parents[4] / "config" / "failure_modes.yaml"
)


def _mode_implications() -> dict[str, str]:
    data = yaml.safe_load(_FAILURE_MODES_PATH.read_text())
    return {
        key: spec.get("implication", "unknown") for key, spec in data["modes"].items()
    }


_MODE_IMPLICATION = _mode_implications()


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _confidence(n: int) -> str:
    if n >= 5:
        return "high"
    if n >= 2:
        return "medium"
    if n == 1:
        return "low"
    return "none"


def _sort_key(e: Mapping) -> tuple:
    return (e.get("run_id", ""), e.get("thesis_id", ""), e.get("expression_id", ""))


def _sorted(expressions):
    return sorted(expressions, key=_sort_key)


def _pf(e: Mapping) -> float | None:
    return (e.get("result") or {}).get("profit_factor")


def _fmt_float(x, digits=2):
    return "null" if x is None else f"{x:.{digits}f}"


def _evidence_row(e: Mapping) -> str:
    r = e.get("result") or {}
    path = f"{e.get('run_id', '?')}/{e.get('thesis_id', '?')}/{e.get('expression_id', '?')}"
    return (
        f"| {path} | {e.get('failure_mode', '?')} | "
        f"{_fmt_float(r.get('profit_factor'))} | "
        f"{_fmt_float(r.get('win_rate'))} | "
        f"{r.get('total_trades', 'null')} |"
    )


def _evidence_table(expressions, limit=10) -> list[str]:
    # Newest-first by run_id/thesis_id/expression_id (lexical proxy).
    rows = _sorted(expressions)[-limit:]
    header = [
        "| Run/Thesis/Exp | failure_mode | profit_factor | win_rate | trades |",
        "|---|---|---|---|---|",
    ]
    body = [_evidence_row(e) for e in rows]
    return header + body


# ---------------------------------------------------------------------------
# Feature page.
# ---------------------------------------------------------------------------


def render_feature_page(*, feature: str, wi: wl.WikiInput) -> str:
    evidence = _sorted(
        e for e in wi.expressions if feature in (e.get("features_used") or [])
    )
    if not evidence:
        return ""

    n = len(evidence)
    approved = [e for e in evidence if e.get("failure_mode") == "APPROVED"]
    pfs = [_pf(e) for e in evidence if _pf(e) is not None]
    approved_pfs = [_pf(e) for e in approved if _pf(e) is not None]
    theses_seen = len({e.get("thesis_id") for e in evidence})

    best_pf_value = max(approved_pfs) if approved_pfs else (max(pfs) if pfs else None)
    best_expression = None
    if approved_pfs:
        best_expression = max(approved, key=lambda e: _pf(e) or float("-inf"))
    elif pfs:
        best_expression = max(evidence, key=lambda e: _pf(e) or float("-inf"))

    frontmatter = {
        "feature": feature,
        "evidence_count": n,
        "approved_count": len(approved),
        "theses_seen": theses_seen,
        "confidence": _confidence(len(approved) or n),
    }
    if best_pf_value is not None:
        frontmatter["best_profit_factor"] = round(best_pf_value, 4)
    if pfs:
        frontmatter["mean_profit_factor"] = round(sum(pfs) / len(pfs), 4)

    fm_yaml = yaml.safe_dump(frontmatter, sort_keys=False).rstrip()
    lines = [f"---\n{fm_yaml}\n---", "", f"# {feature}"]

    if best_expression:
        path = (
            f"{best_expression['run_id']}/"
            f"{best_expression['thesis_id']}/"
            f"{best_expression['expression_id']}"
        )
        lines.append(
            f"**Best observed**: {path} — profit_factor "
            f"{_fmt_float(_pf(best_expression))}"
        )

    lines.append("")
    lines.append("## Evidence")
    lines.extend(_evidence_table(evidence))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Failure mode page.
# ---------------------------------------------------------------------------


def render_failure_mode_page(*, mode: str, wi: wl.WikiInput) -> str:
    if mode not in _MODE_IMPLICATION:
        return ""
    evidence = _sorted(e for e in wi.expressions if e.get("failure_mode") == mode)
    if not evidence:
        return ""

    theses_affected = len({e.get("thesis_id") for e in evidence})
    feature_counter: Counter[str] = Counter()
    for e in evidence:
        for f in e.get("features_used") or []:
            feature_counter[f] += 1
    common_features = [f for f, _ in feature_counter.most_common(5)]

    frontmatter = {
        "mode": mode,
        "implication": _MODE_IMPLICATION[mode],
        "evidence_count": len(evidence),
        "theses_affected": theses_affected,
        "common_features": common_features,
    }
    fm_yaml = yaml.safe_dump(frontmatter, sort_keys=False, default_flow_style=False).rstrip()
    lines = [f"---\n{fm_yaml}\n---", "", f"# {mode}", ""]
    lines.append(f"**Implication**: {_MODE_IMPLICATION[mode]}")
    lines.append("")
    lines.append("## Evidence")
    lines.extend(_evidence_table(evidence))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Combination page.
# ---------------------------------------------------------------------------


def render_combination_page(*, features: tuple[str, str], wi: wl.WikiInput) -> str:
    a, b = sorted(features)
    evidence = _sorted(
        e
        for e in wi.expressions
        if a in (e.get("features_used") or []) and b in (e.get("features_used") or [])
    )
    if not evidence:
        return ""

    approved = [e for e in evidence if e.get("failure_mode") == "APPROVED"]
    pfs = [_pf(e) for e in evidence if _pf(e) is not None]
    best_pf = max(pfs) if pfs else None

    frontmatter = {
        "pair": f"{a} × {b}",
        "evidence_count": len(evidence),
        "approved_count": len(approved),
        "confidence": _confidence(len(approved) or len(evidence)),
    }
    if best_pf is not None:
        frontmatter["best_profit_factor"] = round(best_pf, 4)

    fm_yaml = yaml.safe_dump(frontmatter, sort_keys=False).rstrip()
    lines = [f"---\n{fm_yaml}\n---", "", f"# {a} × {b}", ""]
    lines.append("## Evidence")
    lines.extend(_evidence_table(evidence))
    return "\n".join(lines) + "\n"


def combination_filename(features: tuple[str, str]) -> str:
    a, b = sorted(features)
    return f"{a}_x_{b}.md"
