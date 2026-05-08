from intraday.strategies.multi.orb_fade_basket_time_stop_zscore_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["exit"] == "time_stop"
    assert ALPHA_CELL["transform"] == "z_score"
