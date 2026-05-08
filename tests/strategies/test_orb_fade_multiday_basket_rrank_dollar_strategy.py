from intraday.strategies.multi.orb_fade_multiday_basket_rrank_dollar_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["bar"] == "DOLLAR"
