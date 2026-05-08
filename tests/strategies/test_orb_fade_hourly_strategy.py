from intraday.strategies.multi.orb_fade_hourly_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["horizon"] == "ultra_short"
    assert ALPHA_CELL["idea_family"] == "orb_fade"
