from intraday.strategies.multi.sext_multiday_basket_comp_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "composite"
    assert ALPHA_CELL["horizon"] == "multi_day"
