from intraday.strategies.multi.bb_fade_multiday_topk_ewma_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "ewma_residual"
    assert ALPHA_CELL["universe"] == "basket_topk"
