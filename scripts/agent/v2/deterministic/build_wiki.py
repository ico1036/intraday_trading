"""Idempotent wiki builder.

Clears ``wiki/facts`` and ``wiki/cross_run`` subtrees before rebuild so
stale pages do not leak. ``.gitkeep`` at the ``wiki/`` root level is
preserved. Everything downstream is a pure function of ``archive/``.

    build(archive_root, wiki_root) → BuildReport
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import yaml

from scripts.agent.v2.deterministic import (
    wiki_cross_run,
    wiki_loader,
    wiki_pages,
)


_CONFIG_DIR = Path(__file__).resolve().parents[4] / "config"


def _load_feature_vocab() -> list[str]:
    data = yaml.safe_load((_CONFIG_DIR / "feature_vocab.yaml").read_text())
    return sorted(data["features"].keys())


def _load_failure_modes() -> list[str]:
    data = yaml.safe_load((_CONFIG_DIR / "failure_modes.yaml").read_text())
    return sorted(data["modes"].keys())


@dataclass
class BuildReport:
    features_written: int
    combinations_written: int
    modes_written: int
    cross_run_written: int


def _clear_subtree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def build(archive_root: Path | str, wiki_root: Path | str) -> BuildReport:
    archive_root = Path(archive_root)
    wiki_root = Path(wiki_root)
    wiki_root.mkdir(parents=True, exist_ok=True)

    # Clear managed subtrees. ``.gitkeep`` at wiki/ level is left alone.
    _clear_subtree(wiki_root / "facts")
    _clear_subtree(wiki_root / "cross_run")

    features_dir = wiki_root / "facts" / "features"
    combos_dir = wiki_root / "facts" / "combinations"
    modes_dir = wiki_root / "facts" / "failure_modes"
    cross_run_dir = wiki_root / "cross_run"
    for d in (features_dir, combos_dir, modes_dir, cross_run_dir):
        d.mkdir(parents=True, exist_ok=True)

    wi = wiki_loader.load(archive_root)

    features = _load_feature_vocab()
    modes = _load_failure_modes()

    features_written = 0
    for feature in features:
        page = wiki_pages.render_feature_page(feature=feature, wi=wi)
        if page:
            (features_dir / f"{feature}.md").write_text(page)
            features_written += 1

    combinations_written = 0
    for i, a in enumerate(features):
        for b in features[i + 1 :]:
            page = wiki_pages.render_combination_page(features=(a, b), wi=wi)
            if page:
                (combos_dir / wiki_pages.combination_filename((a, b))).write_text(page)
                combinations_written += 1

    modes_written = 0
    for mode in modes:
        page = wiki_pages.render_failure_mode_page(mode=mode, wi=wi)
        if page:
            (modes_dir / f"{mode}.md").write_text(page)
            modes_written += 1

    cross_run_written = 0
    (cross_run_dir / "refuted_theses.md").write_text(
        wiki_cross_run.render_refuted_theses(wi)
    )
    cross_run_written += 1
    (cross_run_dir / "best_recipes.md").write_text(
        wiki_cross_run.render_best_recipes(wi)
    )
    cross_run_written += 1

    return BuildReport(
        features_written=features_written,
        combinations_written=combinations_written,
        modes_written=modes_written,
        cross_run_written=cross_run_written,
    )


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


def _cli() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="build_wiki",
        description="Rebuild wiki/ from archive/ (idempotent).",
    )
    project_root = Path(__file__).resolve().parents[4]
    parser.add_argument(
        "--archive",
        default=str(project_root / "archive"),
        help="archive root (default: ./archive)",
    )
    parser.add_argument(
        "--wiki",
        default=str(project_root / "wiki"),
        help="wiki root (default: ./wiki)",
    )
    args = parser.parse_args()

    report = build(args.archive, args.wiki)
    print(
        f"[build_wiki] features={report.features_written} "
        f"combinations={report.combinations_written} "
        f"modes={report.modes_written} "
        f"cross_run={report.cross_run_written}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
