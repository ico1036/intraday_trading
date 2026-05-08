from intraday.strategies.multi.orb_fade_single_sol_zscore_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["universe"] == "single"
    assert ALPHA_CELL["exit"] == "time_stop"
