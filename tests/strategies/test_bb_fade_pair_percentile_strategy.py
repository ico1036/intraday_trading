from intraday.strategies.multi.bb_fade_pair_percentile_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "percentile"
    assert ALPHA_CELL["universe"] == "pair"
