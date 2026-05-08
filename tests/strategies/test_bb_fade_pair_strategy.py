from intraday.strategies.multi.bb_fade_pair_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["universe"] == "pair"
    assert ALPHA_CELL["idea_family"] == "bb_band_fade"
