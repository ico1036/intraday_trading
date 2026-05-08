from intraday.strategies.multi.lr_residual_multiday_basket_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["horizon"] == "multi_day"
    assert ALPHA_CELL["idea_family"] == "lr_residual_fade"
