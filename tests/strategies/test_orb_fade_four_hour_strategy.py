from intraday.strategies.multi.orb_fade_4hour_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["horizon"] == "intraday"
    assert ALPHA_CELL["idea_family"] == "orb_fade"
