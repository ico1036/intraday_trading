from intraday.strategies.multi.bb_fade_multiday_basket_pct_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "percentile"
    assert ALPHA_CELL["horizon"] == "multi_day"
    assert ALPHA_CELL["idea_family"] == "bb_band_fade"
