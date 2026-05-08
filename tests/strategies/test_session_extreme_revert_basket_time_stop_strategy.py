from intraday.strategies.multi.session_extreme_revert_basket_time_stop_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["exit"] == "time_stop"
    assert ALPHA_CELL["idea_family"] == "session_extreme_revert"
