from intraday.strategies.multi.orb_fade_pair_time_stop_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["exit"] == "time_stop"
    assert ALPHA_CELL["universe"] == "pair"
