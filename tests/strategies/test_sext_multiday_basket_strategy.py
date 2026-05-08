from intraday.strategies.multi.sext_multiday_basket_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["horizon"] == "multi_day"
    assert ALPHA_CELL["idea_family"] == "session_extreme_revert"
