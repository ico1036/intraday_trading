from intraday.strategies.multi.bb_fade_pair_ewma_residual_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "ewma_residual"
    assert ALPHA_CELL["universe"] == "pair"
