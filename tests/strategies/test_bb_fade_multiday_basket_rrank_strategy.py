from intraday.strategies.multi.bb_fade_multiday_basket_rrank_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "rolling_rank"
    assert ALPHA_CELL["horizon"] == "multi_day"
