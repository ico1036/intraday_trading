from intraday.strategies.multi.bb_band_fade_session_basket_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["horizon"] == "session"
    assert ALPHA_CELL["idea_family"] == "bb_band_fade"
