from intraday.strategies.multi.atr_fade_basket_pct_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "percentile"
    assert ALPHA_CELL["idea_family"] == "atr_band_fade"
