from intraday.strategies.multi.sext_multiday_basket_zscore_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "z_score"
    assert ALPHA_CELL["horizon"] == "multi_day"
