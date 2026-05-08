from intraday.strategies.multi.pivot_fade_single_btc_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["idea_family"] == "pivot_fade"
    assert ALPHA_CELL["universe"] == "single"
