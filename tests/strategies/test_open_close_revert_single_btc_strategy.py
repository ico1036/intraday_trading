from intraday.strategies.multi.open_close_revert_single_btc_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["idea_family"] == "open_close_revert"
    assert ALPHA_CELL["universe"] == "single"
