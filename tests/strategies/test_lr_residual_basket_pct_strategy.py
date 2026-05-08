from intraday.strategies.multi.lr_residual_basket_pct_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "percentile"
    assert ALPHA_CELL["idea_family"] == "lr_residual_fade"
