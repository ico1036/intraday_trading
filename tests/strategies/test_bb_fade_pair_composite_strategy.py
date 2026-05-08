from intraday.strategies.multi.bb_fade_pair_composite_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "composite"
    assert ALPHA_CELL["universe"] == "pair"
