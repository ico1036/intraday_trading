from intraday.strategies.multi.orb_fade_topk_signal_neutral_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "z_score"
    assert ALPHA_CELL["universe"] == "basket_topk"
    assert ALPHA_CELL["exit"] == "neutral_zone"
