from intraday.strategies.multi.session_extreme_revert_single_btc_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["idea_family"] == "session_extreme_revert"
    assert ALPHA_CELL["universe"] == "single"
