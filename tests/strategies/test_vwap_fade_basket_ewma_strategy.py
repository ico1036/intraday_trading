from intraday.strategies.multi.vwap_fade_basket_ewma_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "ewma_residual"
    assert ALPHA_CELL["idea_family"] == "vwap_fade"
