from intraday.strategies.multi.session_extreme_pair_zscore_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "z_score"
    assert ALPHA_CELL["universe"] == "pair"
    assert ALPHA_CELL["idea_family"] == "session_extreme_revert"
