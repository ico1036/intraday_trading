from intraday.strategies.multi.bb_fade_pair_session_raw_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "raw"
    assert ALPHA_CELL["universe"] == "pair"
    assert ALPHA_CELL["horizon"] == "session"
