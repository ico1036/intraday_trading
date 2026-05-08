from intraday.strategies.multi.donchian_fade_basket_ewma_residual_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "ewma_residual"
    assert ALPHA_CELL["idea_family"] == "donchian_fade"
