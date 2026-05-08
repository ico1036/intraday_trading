from intraday.strategies.multi.orb_continuation_session_signal_flip_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["exit"] == "signal_flip"
    assert ALPHA_CELL["idea_family"] == "opening_range_breakout"
