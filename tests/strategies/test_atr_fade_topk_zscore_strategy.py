from intraday.strategies.multi.atr_fade_topk_zscore_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "z_score"
    assert ALPHA_CELL["universe"] == "basket_topk"
    assert ALPHA_CELL["idea_family"] == "atr_band_fade"
