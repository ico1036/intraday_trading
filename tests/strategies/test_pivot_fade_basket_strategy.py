from intraday.strategies.multi.pivot_fade_basket_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["idea_family"] == "pivot_fade"
    assert ALPHA_CELL["universe"] == "basket_full"
