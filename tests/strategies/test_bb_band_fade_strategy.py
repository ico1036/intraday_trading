from intraday.strategies.multi.bb_band_fade_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["idea_family"] == "bb_band_fade"
    assert ALPHA_CELL["exit"] == "signal_flip"
