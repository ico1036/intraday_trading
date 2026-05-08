from intraday.strategies.multi.bb_fade_basket_nz_zscore_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "z_score"
    assert ALPHA_CELL["exit"] == "neutral_zone"
