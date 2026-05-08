from intraday.strategies.multi.atr_fade_basket_session_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["horizon"] == "session"
    assert ALPHA_CELL["idea_family"] == "atr_band_fade"
