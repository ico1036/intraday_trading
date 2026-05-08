from intraday.strategies.multi.donchian_fade_basket_zscore_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "z_score"
    assert ALPHA_CELL["idea_family"] == "donchian_fade"
