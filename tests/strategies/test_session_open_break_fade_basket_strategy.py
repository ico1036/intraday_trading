from intraday.strategies.multi.session_open_break_fade_basket_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["idea_family"] == "session_open_break_fade"
