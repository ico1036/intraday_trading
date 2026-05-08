from intraday.strategies.multi.lr_residual_pair_zscore_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["universe"] == "pair"
    assert ALPHA_CELL["idea_family"] == "lr_residual_fade"
