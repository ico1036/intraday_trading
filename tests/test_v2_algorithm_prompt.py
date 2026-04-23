"""Phase 1-3 — algorithm_prompt v2 frontmatter parser."""
from __future__ import annotations

import pytest

from scripts.agent.v2 import algorithm_prompt as ap


SAMPLE_V2_PROMPT = """---
thesis_id: th_001
expression_id: exp_003
expression_spec:
  bar_domain: VOLUME
  bar_granularity: medium
  signal_form: z_score
  threshold_type: adaptive_quantile
  aggregation: ema
  regime_filter: vol_regime
  exit_rule: time_stop
  sizing: fixed
  universe: single_symbol
features_used: [vpin, volume_imbalance]
addresses: "exp_002:SIGNAL_SPARSE"
---

# Strategy: VPINReversalAdaptive

## Hypothesis
Informed-flow exhaustion in high VPIN regimes → short-term reversal.

## Parameters
- threshold: 0.7
"""


# ---------------------------------------------------------------------------
# Parsing.
# ---------------------------------------------------------------------------


def test_parse_returns_fields():
    p = ap.parse(SAMPLE_V2_PROMPT)
    assert p.thesis_id == "th_001"
    assert p.expression_id == "exp_003"
    assert p.expression_spec["signal_form"] == "z_score"
    assert p.features_used == ["vpin", "volume_imbalance"]
    assert p.addresses == "exp_002:SIGNAL_SPARSE"


def test_parse_returns_body():
    p = ap.parse(SAMPLE_V2_PROMPT)
    assert "# Strategy: VPINReversalAdaptive" in p.body
    assert "threshold: 0.7" in p.body


def test_parse_rejects_no_frontmatter():
    with pytest.raises(ap.AlgorithmPromptError):
        ap.parse("# Strategy: X\n\nNo frontmatter.\n")


def test_parse_rejects_missing_required_field():
    text = """---
expression_id: exp_001
expression_spec:
  bar_domain: VOLUME
features_used: [vpin]
---

# Strategy: X
"""
    with pytest.raises(ap.AlgorithmPromptError) as exc:
        ap.parse(text)
    assert "thesis_id" in str(exc.value)


def test_parse_rejects_bad_thesis_id():
    text = SAMPLE_V2_PROMPT.replace("thesis_id: th_001", "thesis_id: thesis-1")
    with pytest.raises(ap.AlgorithmPromptError):
        ap.parse(text)


def test_parse_rejects_bad_expression_spec_axis():
    text = SAMPLE_V2_PROMPT.replace(
        "bar_domain: VOLUME", "bar_domain: NONSENSE"
    )
    with pytest.raises(ap.AlgorithmPromptError):
        ap.parse(text)


def test_parse_rejects_unknown_feature():
    text = SAMPLE_V2_PROMPT.replace(
        "features_used: [vpin, volume_imbalance]",
        "features_used: [unobtanium]",
    )
    with pytest.raises(ap.AlgorithmPromptError):
        ap.parse(text)


def test_parse_allows_missing_addresses_for_first_expression():
    text = """---
thesis_id: th_001
expression_id: exp_001
expression_spec:
  bar_domain: VOLUME
  bar_granularity: medium
  signal_form: raw
  threshold_type: absolute
  aggregation: instantaneous
  regime_filter: none
  exit_rule: time_stop
  sizing: fixed
  universe: single_symbol
features_used: [vpin]
---

# Strategy: Baseline
"""
    p = ap.parse(text)
    assert p.addresses is None


# ---------------------------------------------------------------------------
# Building.
# ---------------------------------------------------------------------------


def test_build_roundtrip():
    parsed = ap.parse(SAMPLE_V2_PROMPT)
    rendered = ap.build(
        thesis_id=parsed.thesis_id,
        expression_id=parsed.expression_id,
        expression_spec=parsed.expression_spec,
        features_used=parsed.features_used,
        addresses=parsed.addresses,
        body=parsed.body,
    )
    reparsed = ap.parse(rendered)
    assert reparsed.thesis_id == parsed.thesis_id
    assert reparsed.expression_id == parsed.expression_id
    assert reparsed.expression_spec == parsed.expression_spec
    assert reparsed.features_used == parsed.features_used
    assert reparsed.addresses == parsed.addresses


def test_build_validates_inputs():
    with pytest.raises(ap.AlgorithmPromptError):
        ap.build(
            thesis_id="not_valid",
            expression_id="exp_001",
            expression_spec={"bar_domain": "VOLUME"},
            features_used=["vpin"],
            addresses=None,
            body="x",
        )


# ---------------------------------------------------------------------------
# File helpers.
# ---------------------------------------------------------------------------


def test_parse_file(tmp_path):
    path = tmp_path / "algorithm_prompt.txt"
    path.write_text(SAMPLE_V2_PROMPT)
    p = ap.parse_file(path)
    assert p.thesis_id == "th_001"


def test_write_file(tmp_path):
    path = tmp_path / "algorithm_prompt.txt"
    ap.write_file(
        path,
        thesis_id="th_001",
        expression_id="exp_001",
        expression_spec={
            "bar_domain": "VOLUME",
            "bar_granularity": "medium",
            "signal_form": "raw",
            "threshold_type": "absolute",
            "aggregation": "instantaneous",
            "regime_filter": "none",
            "exit_rule": "time_stop",
            "sizing": "fixed",
            "universe": "single_symbol",
        },
        features_used=["vpin"],
        addresses=None,
        body="# Strategy: Smoke\n",
    )
    assert path.is_file()
    p = ap.parse_file(path)
    assert p.expression_id == "exp_001"
