from intraday.strategies.multi.atr_band_fade_time_stop_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["exit"] == "time_stop"
    assert ALPHA_CELL["idea_family"] == "atr_band_fade"
