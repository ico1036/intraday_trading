from intraday.strategies.multi.orb_fade_topk_neutral_ewma_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "ewma_residual"
    assert ALPHA_CELL["exit"] == "neutral_zone"
