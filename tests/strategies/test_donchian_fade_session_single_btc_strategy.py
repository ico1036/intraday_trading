from intraday.strategies.multi.donchian_fade_session_single_btc_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["horizon"] == "session"
    assert ALPHA_CELL["universe"] == "single"
    assert ALPHA_CELL["idea_family"] == "donchian_fade"
