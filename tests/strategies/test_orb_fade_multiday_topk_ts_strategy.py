from intraday.strategies.multi.orb_fade_multiday_topk_ts_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["exit"] == "time_stop"
    assert ALPHA_CELL["universe"] == "basket_topk"
    assert ALPHA_CELL["horizon"] == "multi_day"
