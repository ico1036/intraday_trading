from intraday.strategies.multi.donchian_fade_signal_flip_session_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["horizon"] == "session"
    assert ALPHA_CELL["idea_family"] == "donchian_fade"
