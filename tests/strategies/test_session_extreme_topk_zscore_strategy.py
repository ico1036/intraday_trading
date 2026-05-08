from intraday.strategies.multi.session_extreme_topk_zscore_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["universe"] == "basket_topk"
    assert ALPHA_CELL["idea_family"] == "session_extreme_revert"
