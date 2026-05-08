from intraday.strategies.multi.bb_fade_pair_ts_comp_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "composite"
    assert ALPHA_CELL["exit"] == "time_stop"
    assert ALPHA_CELL["universe"] == "pair"
