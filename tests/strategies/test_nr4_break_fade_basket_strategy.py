from intraday.strategies.multi.nr4_break_fade_basket_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["idea_family"] == "nr4_break_fade"
