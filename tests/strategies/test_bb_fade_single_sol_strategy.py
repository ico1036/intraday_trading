from intraday.strategies.multi.bb_fade_single_sol_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["exit"] == "neutral_zone"
    assert ALPHA_CELL["transform"] == "raw"
