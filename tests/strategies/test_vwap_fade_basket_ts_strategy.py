from intraday.strategies.multi.vwap_fade_basket_ts_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["exit"] == "time_stop"
    assert ALPHA_CELL["idea_family"] == "vwap_fade"
