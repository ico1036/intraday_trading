from intraday.strategies.multi.bb_fade_single_eth_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["exit"] == "time_stop"
    assert ALPHA_CELL["idea_family"] == "bb_band_fade"
