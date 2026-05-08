from intraday.strategies.multi.intraday_seasonality_topk_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["universe"] == "basket_topk"
    assert ALPHA_CELL["idea_family"] == "intraday_seasonality"
