from intraday.strategies.multi.sext_pair_ts_zscore_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "z_score"
    assert ALPHA_CELL["universe"] == "pair"
    assert ALPHA_CELL["exit"] == "time_stop"
