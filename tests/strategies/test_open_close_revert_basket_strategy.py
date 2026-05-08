from intraday.strategies.multi.open_close_revert_basket_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["idea_family"] == "open_close_revert"
