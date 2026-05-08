from intraday.strategies.multi.atr_fast_fade_basket_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["idea_family"] == "atr_fast_fade"
