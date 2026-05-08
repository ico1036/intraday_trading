from intraday.strategies.multi.two_bar_revert_basket_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["idea_family"] == "two_bar_revert"
