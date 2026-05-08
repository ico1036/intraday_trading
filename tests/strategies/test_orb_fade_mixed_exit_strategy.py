from intraday.strategies.multi.orb_fade_mixed_exit_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["exit"] == "mixed"
    assert ALPHA_CELL["idea_family"] == "orb_fade"
