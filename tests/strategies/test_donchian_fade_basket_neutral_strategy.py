from intraday.strategies.multi.donchian_fade_basket_neutral_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["exit"] == "neutral_zone"
    assert ALPHA_CELL["idea_family"] == "donchian_fade"
