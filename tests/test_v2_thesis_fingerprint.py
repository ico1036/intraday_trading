"""Phase 2-2 — thesis_fingerprint.py contract.

A thesis is a canonical triple (direction, features, trigger_schema). Two
theses with identical canonical form MUST hash identically, even if English
prose differs. Features must be from the bounded vocab.
"""
from __future__ import annotations

import pytest

from scripts.agent.v2.deterministic import thesis_fingerprint as tf


# ---------------------------------------------------------------------------
# Basic shape.
# ---------------------------------------------------------------------------


def test_fingerprint_format():
    fp = tf.fingerprint(
        direction="reversal",
        features=["vpin"],
        trigger_schema={"when": "vpin > p90", "side": "sell"},
    )
    assert fp.startswith("sha256:")
    assert len(fp) == len("sha256:") + 64
    assert all(c in "0123456789abcdef" for c in fp.removeprefix("sha256:"))


def test_fingerprint_is_deterministic():
    kwargs = dict(
        direction="momentum",
        features=["price_momentum", "volume_imbalance"],
        trigger_schema={"when": "momentum > p80", "side": "buy"},
    )
    assert tf.fingerprint(**kwargs) == tf.fingerprint(**kwargs)


# ---------------------------------------------------------------------------
# Canonicalisation — same thesis, different surface form, same fingerprint.
# ---------------------------------------------------------------------------


def test_feature_order_does_not_matter():
    a = tf.fingerprint(
        direction="momentum",
        features=["volume_imbalance", "price_momentum"],
        trigger_schema={"when": "x", "side": "buy"},
    )
    b = tf.fingerprint(
        direction="momentum",
        features=["price_momentum", "volume_imbalance"],
        trigger_schema={"when": "x", "side": "buy"},
    )
    assert a == b


def test_direction_is_case_normalized():
    a = tf.fingerprint(
        direction="Reversal",
        features=["vpin"],
        trigger_schema={"when": "vpin > p90"},
    )
    b = tf.fingerprint(
        direction="reversal",
        features=["vpin"],
        trigger_schema={"when": "vpin > p90"},
    )
    assert a == b


def test_duplicate_features_are_collapsed():
    a = tf.fingerprint(
        direction="carry",
        features=["funding_carry"],
        trigger_schema={"when": "funding > 0"},
    )
    b = tf.fingerprint(
        direction="carry",
        features=["funding_carry", "funding_carry"],
        trigger_schema={"when": "funding > 0"},
    )
    assert a == b


def test_trigger_schema_key_order_does_not_matter():
    a = tf.fingerprint(
        direction="momentum",
        features=["price_momentum"],
        trigger_schema={"when": "mom > p80", "side": "buy", "exit": "time"},
    )
    b = tf.fingerprint(
        direction="momentum",
        features=["price_momentum"],
        trigger_schema={"exit": "time", "side": "buy", "when": "mom > p80"},
    )
    assert a == b


# ---------------------------------------------------------------------------
# Discrimination — different thesis → different fingerprint.
# ---------------------------------------------------------------------------


def test_different_direction_diverges():
    a = tf.fingerprint(
        direction="momentum",
        features=["price_momentum"],
        trigger_schema={"when": "x"},
    )
    b = tf.fingerprint(
        direction="reversal",
        features=["price_momentum"],
        trigger_schema={"when": "x"},
    )
    assert a != b


def test_different_features_diverges():
    a = tf.fingerprint(
        direction="reversal",
        features=["vpin"],
        trigger_schema={"when": "x"},
    )
    b = tf.fingerprint(
        direction="reversal",
        features=["ofi"],
        trigger_schema={"when": "x"},
    )
    assert a != b


def test_different_trigger_schema_diverges():
    a = tf.fingerprint(
        direction="momentum",
        features=["price_momentum"],
        trigger_schema={"when": "mom > p80"},
    )
    b = tf.fingerprint(
        direction="momentum",
        features=["price_momentum"],
        trigger_schema={"when": "mom > p90"},
    )
    assert a != b


# ---------------------------------------------------------------------------
# Validation — features must be in the bounded vocab.
# ---------------------------------------------------------------------------


def test_rejects_feature_not_in_vocab():
    with pytest.raises(tf.ThesisValidationError) as exc:
        tf.fingerprint(
            direction="momentum",
            features=["some_random_feature"],
            trigger_schema={"when": "x"},
        )
    assert "some_random_feature" in str(exc.value)


def test_rejects_empty_direction():
    with pytest.raises(tf.ThesisValidationError):
        tf.fingerprint(
            direction="",
            features=["vpin"],
            trigger_schema={"when": "x"},
        )


def test_rejects_empty_features():
    with pytest.raises(tf.ThesisValidationError):
        tf.fingerprint(
            direction="momentum",
            features=[],
            trigger_schema={"when": "x"},
        )


def test_rejects_empty_trigger_schema():
    with pytest.raises(tf.ThesisValidationError):
        tf.fingerprint(
            direction="momentum",
            features=["vpin"],
            trigger_schema={},
        )


# ---------------------------------------------------------------------------
# parse_from_thesis_md — read frontmatter form.
# ---------------------------------------------------------------------------


def test_fingerprint_from_thesis_markdown():
    md = """---
direction: reversal
features: [vpin, volume_imbalance]
trigger_schema:
  when: "vpin > p90"
  side: sell
---

# Thesis: Informed flow exhaustion
"""
    fp1 = tf.fingerprint_from_markdown(md)
    fp2 = tf.fingerprint(
        direction="reversal",
        features=["vpin", "volume_imbalance"],
        trigger_schema={"when": "vpin > p90", "side": "sell"},
    )
    assert fp1 == fp2


def test_fingerprint_from_markdown_ignores_body():
    md1 = """---
direction: reversal
features: [vpin]
trigger_schema:
  when: "x"
---

# Thesis A
Some prose.
"""
    md2 = """---
direction: reversal
features: [vpin]
trigger_schema:
  when: "x"
---

# Thesis B — completely different wording
Wholly different prose.
"""
    assert tf.fingerprint_from_markdown(md1) == tf.fingerprint_from_markdown(md2)


def test_fingerprint_from_markdown_errors_without_frontmatter():
    with pytest.raises(tf.ThesisValidationError):
        tf.fingerprint_from_markdown("# just a heading, no frontmatter\n")
