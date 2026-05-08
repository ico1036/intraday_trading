from intraday.strategies.multi.sext_multiday_topk_pct_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "percentile"
    assert ALPHA_CELL["universe"] == "basket_topk"
    assert ALPHA_CELL["horizon"] == "multi_day"
