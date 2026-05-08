from intraday.strategies.multi.two_bar_revert_topk_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["universe"] == "basket_topk"
    assert ALPHA_CELL["idea_family"] == "two_bar_revert"
