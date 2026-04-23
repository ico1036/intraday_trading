"""Phase 1-1 — expression_log writer contract.

Append-only SoT for a run. Validates against the YAML enums before writing,
so a bad enum never corrupts downstream digests.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.agent.v2 import expression_log as elog


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _good_spec(**overrides):
    base = dict(
        bar_domain="VOLUME",
        bar_granularity="medium",
        signal_form="raw",
        threshold_type="absolute",
        aggregation="instantaneous",
        regime_filter="none",
        exit_rule="time_stop",
        sizing="fixed",
        universe="single_symbol",
    )
    base.update(overrides)
    return base


def _good_entry(**overrides):
    base = dict(
        run_id="v1_smoke",
        thesis_id="th_001",
        expression_id="exp_001",
        expression_spec=_good_spec(),
        features_used=["vpin"],
        failure_mode="SIGNAL_NOISY",
        verdict_after="ACTIVE",
        artifact_path="archive/v1_smoke/theses/th_001/expressions/exp_001/",
    )
    base.update(overrides)
    return elog.ExpressionLogEntry(**base)


# ---------------------------------------------------------------------------
# Append behaviour.
# ---------------------------------------------------------------------------


def test_append_creates_jsonl_file(tmp_path):
    elog.append(tmp_path, _good_entry())
    log = tmp_path / "expression_log.jsonl"
    assert log.is_file()
    entries = [json.loads(line) for line in log.read_text().splitlines()]
    assert len(entries) == 1
    assert entries[0]["expression_id"] == "exp_001"


def test_multiple_appends_produce_multiple_lines(tmp_path):
    elog.append(tmp_path, _good_entry(expression_id="exp_001"))
    elog.append(tmp_path, _good_entry(expression_id="exp_002"))
    elog.append(tmp_path, _good_entry(expression_id="exp_003"))

    lines = (tmp_path / "expression_log.jsonl").read_text().splitlines()
    assert len(lines) == 3
    ids = [json.loads(line)["expression_id"] for line in lines]
    assert ids == ["exp_001", "exp_002", "exp_003"]


def test_append_also_writes_to_seen_failure_modes(tmp_path):
    elog.append(tmp_path, _good_entry())
    seen_path = tmp_path / "theses" / "th_001" / "seen_failure_modes.jsonl"
    assert seen_path.is_file()

    records = [json.loads(line) for line in seen_path.read_text().splitlines()]
    assert len(records) == 1
    r = records[0]
    assert r["expression_id"] == "exp_001"
    assert r["failure_mode"] == "SIGNAL_NOISY"
    assert r["expression_spec"]["bar_domain"] == "VOLUME"


def test_append_writes_timestamp_even_if_caller_omits(tmp_path):
    entry = _good_entry()
    assert entry.ts  # dataclass default supplies it
    elog.append(tmp_path, entry)
    record = json.loads(
        (tmp_path / "expression_log.jsonl").read_text().splitlines()[0]
    )
    assert record["ts"]


def test_seen_jsonl_is_partitioned_by_thesis(tmp_path):
    elog.append(tmp_path, _good_entry(thesis_id="th_001", expression_id="exp_001"))
    elog.append(tmp_path, _good_entry(thesis_id="th_002", expression_id="exp_002"))

    assert (tmp_path / "theses" / "th_001" / "seen_failure_modes.jsonl").is_file()
    assert (tmp_path / "theses" / "th_002" / "seen_failure_modes.jsonl").is_file()


# ---------------------------------------------------------------------------
# Validation — refuse to corrupt the log.
# ---------------------------------------------------------------------------


def test_rejects_unknown_axis_key(tmp_path):
    spec = _good_spec()
    spec["invented_axis"] = "nonsense"
    with pytest.raises(elog.ExpressionLogError) as exc:
        elog.append(tmp_path, _good_entry(expression_spec=spec))
    assert "invented_axis" in str(exc.value)


def test_rejects_unknown_axis_value(tmp_path):
    spec = _good_spec(bar_domain="SOMETHING_ELSE")
    with pytest.raises(elog.ExpressionLogError):
        elog.append(tmp_path, _good_entry(expression_spec=spec))


def test_rejects_unknown_feature(tmp_path):
    with pytest.raises(elog.ExpressionLogError):
        elog.append(tmp_path, _good_entry(features_used=["invented_feature"]))


def test_rejects_unknown_failure_mode(tmp_path):
    with pytest.raises(elog.ExpressionLogError):
        elog.append(tmp_path, _good_entry(failure_mode="SOMETHING_WEIRD"))


def test_accepts_literal_approved(tmp_path):
    # APPROVED is not in the failure_modes enum but is valid as a success tag.
    elog.append(tmp_path, _good_entry(failure_mode="APPROVED", verdict_after="APPROVED"))


def test_rejects_unknown_verdict_after(tmp_path):
    with pytest.raises(elog.ExpressionLogError):
        elog.append(tmp_path, _good_entry(verdict_after="SHRUG"))


def test_rejects_malformed_thesis_id(tmp_path):
    with pytest.raises(elog.ExpressionLogError):
        elog.append(tmp_path, _good_entry(thesis_id="thesis_001"))


def test_rejects_malformed_expression_id(tmp_path):
    with pytest.raises(elog.ExpressionLogError):
        elog.append(tmp_path, _good_entry(expression_id="expression_1"))


def test_does_not_write_on_validation_failure(tmp_path):
    """Partial write must not corrupt the log."""
    spec = _good_spec(bar_domain="BAD")
    with pytest.raises(elog.ExpressionLogError):
        elog.append(tmp_path, _good_entry(expression_spec=spec))
    assert not (tmp_path / "expression_log.jsonl").exists()
    assert not (tmp_path / "theses" / "th_001").exists()
