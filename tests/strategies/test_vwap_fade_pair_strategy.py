from intraday.strategies.multi.vwap_fade_pair_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["universe"] == "pair"
    assert ALPHA_CELL["idea_family"] == "vwap_fade"
