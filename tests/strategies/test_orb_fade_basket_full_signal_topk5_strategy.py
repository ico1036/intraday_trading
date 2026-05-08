from intraday.strategies.multi.orb_fade_basket_full_signal_topk5_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "composite"
    assert ALPHA_CELL["universe"] == "basket_topk"
    assert ALPHA_CELL["exit"] == "neutral_zone"
