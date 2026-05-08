from intraday.strategies.multi.range_position_signal_flip_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["exit"] == "signal_flip"
    assert ALPHA_CELL["idea_family"] == "range_position_xs"
    assert ALPHA_CELL["horizon"] == "intraday"
