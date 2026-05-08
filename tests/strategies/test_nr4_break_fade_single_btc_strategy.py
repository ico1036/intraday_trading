from intraday.strategies.multi.nr4_break_fade_single_btc_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["universe"] == "single"
    assert ALPHA_CELL["idea_family"] == "nr4_break_fade"
