from intraday.strategies.multi.session_extreme_basket_rrank_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "rolling_rank"
    assert ALPHA_CELL["idea_family"] == "session_extreme_revert"
