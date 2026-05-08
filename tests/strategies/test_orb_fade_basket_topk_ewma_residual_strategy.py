from intraday.strategies.multi.orb_fade_basket_topk_ewma_residual_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "ewma_residual"
    assert ALPHA_CELL["universe"] == "basket_topk"
