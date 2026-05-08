from intraday.strategies.multi.bb_fade_single_btc_session_ts_z_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "z_score"
    assert ALPHA_CELL["exit"] == "time_stop"
    assert ALPHA_CELL["universe"] == "single"
    assert ALPHA_CELL["horizon"] == "session"
