from intraday.strategies.multi.atr_band_fade_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["idea_family"] == "atr_band_fade"
