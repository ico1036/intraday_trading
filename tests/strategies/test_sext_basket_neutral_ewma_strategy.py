from intraday.strategies.multi.sext_basket_neutral_ewma_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "ewma_residual"
    assert ALPHA_CELL["exit"] == "neutral_zone"
