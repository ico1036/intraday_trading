from intraday.strategies.multi.rsi_extreme_fade_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["idea_family"] == "rsi_extreme_fade"
