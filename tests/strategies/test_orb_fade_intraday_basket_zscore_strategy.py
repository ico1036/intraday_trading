from intraday.strategies.multi.orb_fade_intraday_basket_zscore_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "z_score"
    assert ALPHA_CELL["horizon"] == "intraday"
    assert ALPHA_CELL["universe"] == "basket_full"
