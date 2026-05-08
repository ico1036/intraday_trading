from intraday.strategies.multi.bb_fade_basket_rolling_rank_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "rolling_rank"
    assert ALPHA_CELL["universe"] == "basket_full"
