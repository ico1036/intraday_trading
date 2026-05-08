from intraday.strategies.multi.atr_fade_basket_topk_signal_flip_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["exit"] == "signal_flip"
    assert ALPHA_CELL["universe"] == "basket_topk"
    assert ALPHA_CELL["idea_family"] == "atr_band_fade"
