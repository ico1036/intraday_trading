from intraday.strategies.multi.sext_md_basket_trailing_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["exit"] == "trailing"
    assert ALPHA_CELL["horizon"] == "multi_day"
    assert ALPHA_CELL["idea_family"] == "session_extreme_revert"
