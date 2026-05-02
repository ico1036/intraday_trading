"""Phase 1-4 — agent prompt sanity tests.

These tests don't validate LLM behaviour (impossible to unit-test). They
lock critical constraint language so refactors don't silently drop guards.
"""
from __future__ import annotations

from scripts.agent.v2.agents import analyst, developer, researcher


# ---------------------------------------------------------------------------
# Researcher identity.
# ---------------------------------------------------------------------------


def test_researcher_identity_mentions_bounded_vocab():
    text = researcher.identity_prompt()
    assert "config/expression_axes.yaml" in text
    assert "config/feature_vocab.yaml" in text


def test_researcher_identity_forbids_verdict_write():
    text = researcher.identity_prompt()
    assert "Never write verdict.md" in text


def test_researcher_identity_forbids_raw_log_read():
    text = researcher.identity_prompt()
    assert "expression_log.jsonl" in text
    assert "research_map.md" in text


def test_researcher_identity_references_framework_limitations():
    text = researcher.identity_prompt()
    assert "FRAMEWORK_LIMITATIONS.md" in text


def test_framework_limitations_doc_exists():
    from pathlib import Path
    path = Path(__file__).resolve().parent.parent / "docs" / "v2" / "FRAMEWORK_LIMITATIONS.md"
    assert path.is_file(), f"missing {path}"
    body = path.read_text()
    assert "# Framework limitations" in body
    assert "## What the agent should refuse" in body


def test_researcher_identity_lists_all_failure_modes():
    text = researcher.identity_prompt()
    expected = {
        "SIGNAL_SPARSE",
        "SIGNAL_NOISY",
        "LATE_ENTRY",
        "EDGE_DECAY",
        "REGIME_DEPENDENT",
        "FEE_DOMINATED",
        "OVERFIT_SYMBOL",
        "THESIS_INVERTED",
        "OTHER",
    }
    missing = {m for m in expected if m not in text}
    assert not missing, f"missing modes in researcher identity: {missing}"


# ---------------------------------------------------------------------------
# Researcher task builders.
# ---------------------------------------------------------------------------


def test_compose_expression_task_includes_context():
    text = researcher.compose_expression_task(
        run_id="r1",
        thesis_id="th_001",
        thesis_md="# Thesis body",
        prior_seen=[
            {
                "expression_id": "exp_001",
                "failure_mode": "SIGNAL_NOISY",
                "expression_spec": {"bar_domain": "VOLUME"},
            }
        ],
        research_map="map",
        verdict_hints=["new_axis_required"],
        addresses_hint="exp_001:SIGNAL_NOISY",
        next_expression_id="exp_002",
    )
    assert "th_001" in text
    assert "exp_002" in text
    assert "exp_001:SIGNAL_NOISY" in text
    assert "new_axis_required" in text
    assert "SIGNAL_NOISY" in text


def test_new_thesis_task_lists_refuted_fingerprints():
    text = researcher.new_thesis_task(
        run_id="r1",
        thesis_id="th_002",
        strategy_request="Probe VPIN reversal",
        research_map="map",
        refuted_fingerprints=["sha256:aaa", "sha256:bbb"],
        next_expression_id="exp_001",
    )
    assert "th_002" in text
    assert "sha256:aaa" in text
    assert "sha256:bbb" in text
    assert "Probe VPIN reversal" in text


def test_new_thesis_task_handles_empty_refuted_list():
    text = researcher.new_thesis_task(
        run_id="r1",
        thesis_id="th_001",
        strategy_request="Any idea",
        research_map="",
        refuted_fingerprints=[],
        next_expression_id="exp_001",
    )
    assert "none yet" in text.lower()


# ---------------------------------------------------------------------------
# Developer.
# ---------------------------------------------------------------------------


def test_developer_identity_forbids_mcp_and_core_files():
    text = developer.identity_prompt()
    assert "Don't call MCP backtest tools" in text
    assert "base.py" in text


def test_developer_identity_uses_unified_portfolio_template():
    text = developer.identity_prompt()
    assert "src/intraday/strategies/multi/_alpha_template.py" in text
    assert "src/intraday/strategies/multi/<name>.py" in text
    assert "symbols=[\"BTCUSDT\"]" in text
    assert "PortfolioOrder" in text
    assert "Order(weight=...)" in text


def test_developer_task_includes_paths():
    text = developer.task_prompt(
        algorithm_prompt_path="/work/algorithm_prompt.txt",
        workdir="/work",
    )
    assert "/work/algorithm_prompt.txt" in text
    assert "/work" in text
    assert "src/intraday/strategies/multi/_alpha_template.py" in text
    assert "symbols: list[str]" in text
    assert "PortfolioOrder" in text


# ---------------------------------------------------------------------------
# Analyst.
# ---------------------------------------------------------------------------


def test_analyst_identity_enforces_enum_output():
    text = analyst.identity_prompt()
    assert "failure_mode.txt" in text
    assert "enum, not prose" in text
    assert "Never write verdict.md" in text


def test_analyst_identity_lists_all_modes_and_approved():
    text = analyst.identity_prompt()
    for mode in (
        "SIGNAL_SPARSE",
        "SIGNAL_NOISY",
        "LATE_ENTRY",
        "EDGE_DECAY",
        "REGIME_DEPENDENT",
        "FEE_DOMINATED",
        "OVERFIT_SYMBOL",
        "THESIS_INVERTED",
        "OTHER",
    ):
        assert mode in text, f"analyst missing {mode}"
    assert "APPROVED" in text
