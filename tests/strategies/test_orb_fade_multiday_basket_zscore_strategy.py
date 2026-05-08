from intraday.strategies.multi.orb_fade_multiday_basket_zscore_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["horizon"] == "multi_day"
    assert ALPHA_CELL["transform"] == "z_score"
