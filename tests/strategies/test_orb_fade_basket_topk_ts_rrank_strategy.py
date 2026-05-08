from intraday.strategies.multi.orb_fade_basket_topk_ts_rrank_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "rolling_rank"
    assert ALPHA_CELL["exit"] == "time_stop"
    assert ALPHA_CELL["universe"] == "basket_topk"
