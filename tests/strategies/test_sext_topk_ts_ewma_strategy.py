from intraday.strategies.multi.sext_topk_ts_ewma_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "ewma_residual"
    assert ALPHA_CELL["universe"] == "basket_topk"
    assert ALPHA_CELL["exit"] == "time_stop"
