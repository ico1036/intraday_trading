from intraday.strategies.multi.bb_fade_session_basket_composite_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "composite"
    assert ALPHA_CELL["idea_family"] == "bb_band_fade"
