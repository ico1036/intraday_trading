from intraday.strategies.multi.session_extreme_revert_basket_comp_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "composite"
    assert ALPHA_CELL["idea_family"] == "session_extreme_revert"
