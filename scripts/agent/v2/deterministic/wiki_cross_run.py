"""Cross-run page renderers.

Everything here is a pure (WikiInput) → markdown function. Determinism
guaranteed by sorting at the entry of each render.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Mapping

import yaml

from scripts.agent.v2.deterministic import wiki_loader as wl


_DEFAULT_TOP_N = 3


# ---------------------------------------------------------------------------
# refuted_theses.md
# ---------------------------------------------------------------------------


def render_refuted_theses(wi: wl.WikiInput) -> str:
    refuted = [
        t
        for t in wi.theses
        if t.verdict_status == "REFUTED" and t.fingerprint
    ]
    refuted.sort(key=lambda t: (t.fingerprint, t.run_id, t.thesis_id))

    frontmatter = {"total": len(refuted)}
    fm_yaml = yaml.safe_dump(frontmatter, sort_keys=False).rstrip()

    lines = [
        f"---\n{fm_yaml}\n---",
        "",
        "# Refuted theses",
        "",
    ]
    if not refuted:
        lines.append("_No refuted theses yet._")
        return "\n".join(lines) + "\n"

    lines.extend(
        [
            "| Fingerprint | Run | Thesis | Direction | Features |",
            "|---|---|---|---|---|",
        ]
    )
    for t in refuted:
        features = ",".join(t.features) if t.features else ""
        lines.append(
            f"| {t.fingerprint} | {t.run_id} | {t.thesis_id} | "
            f"{t.direction or ''} | {features} |"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# best_recipes.md
# ---------------------------------------------------------------------------


def _pf(e: Mapping) -> float | None:
    return (e.get("result") or {}).get("profit_factor")


def render_best_recipes(wi: wl.WikiInput, *, top_n: int = _DEFAULT_TOP_N) -> str:
    approved = [e for e in wi.expressions if e.get("failure_mode") == "APPROVED"]

    by_run: dict[str, list[dict]] = defaultdict(list)
    for e in approved:
        by_run[e.get("run_id", "")].append(e)

    for run_id, entries in by_run.items():
        entries.sort(
            key=lambda e: (
                -(float(_pf(e) or 0.0)),
                e.get("thesis_id", ""),
                e.get("expression_id", ""),
            )
        )

    frontmatter = {
        "total_approved": len(approved),
        "runs_covered": len(by_run),
    }
    fm_yaml = yaml.safe_dump(frontmatter, sort_keys=False).rstrip()

    lines = [
        f"---\n{fm_yaml}\n---",
        "",
        "# Best recipes",
        "",
    ]
    if not approved:
        lines.append("_No APPROVED expressions yet._")
        return "\n".join(lines) + "\n"

    for run_id in sorted(by_run.keys()):
        lines.append(f"## Run {run_id}")
        for e in by_run[run_id][:top_n]:
            r = e.get("result") or {}
            feats = ",".join(e.get("features_used") or [])
            pf = _pf(e)
            pf_str = "?" if pf is None else f"{pf:.2f}"
            lines.append(
                f"- **{e.get('thesis_id')} / {e.get('expression_id')}** — "
                f"PF {pf_str}, trades {r.get('total_trades', '?')}, "
                f"features [{feats}]"
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
