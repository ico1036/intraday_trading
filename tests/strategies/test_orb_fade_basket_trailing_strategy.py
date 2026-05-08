from intraday.strategies.multi.orb_fade_basket_trailing_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["exit"] == "trailing"
    assert ALPHA_CELL["universe"] == "basket_full"
