from intraday.strategies.multi.dispersion_signal_flip_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["exit"] == "signal_flip"
    assert ALPHA_CELL["idea_family"] == "dispersion_meanrev_xs"
