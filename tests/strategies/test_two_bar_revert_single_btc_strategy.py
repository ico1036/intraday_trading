from intraday.strategies.multi.two_bar_revert_single_btc_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["universe"] == "single"
    assert ALPHA_CELL["idea_family"] == "two_bar_revert"
