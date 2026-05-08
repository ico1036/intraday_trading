from intraday.strategies.multi.sext_multiday_basket_ts_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["exit"] == "time_stop"
    assert ALPHA_CELL["horizon"] == "multi_day"
