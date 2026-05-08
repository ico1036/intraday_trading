from intraday.strategies.multi.donchian_fade_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["idea_family"] == "donchian_fade"
    assert ALPHA_CELL["exit"] == "signal_flip"
