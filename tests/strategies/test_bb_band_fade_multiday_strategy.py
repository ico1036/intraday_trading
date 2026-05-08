from intraday.strategies.multi.bb_band_fade_multiday_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["horizon"] == "multi_day"
    assert ALPHA_CELL["idea_family"] == "bb_band_fade"
