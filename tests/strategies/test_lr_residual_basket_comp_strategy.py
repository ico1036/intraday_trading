from intraday.strategies.multi.lr_residual_basket_comp_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "composite"
    assert ALPHA_CELL["idea_family"] == "lr_residual_fade"
