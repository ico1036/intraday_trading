from intraday.strategies.multi.sext_basket_full_ts_ewma_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "ewma_residual"
    assert ALPHA_CELL["exit"] == "time_stop"
    assert ALPHA_CELL["idea_family"] == "session_extreme_revert"
