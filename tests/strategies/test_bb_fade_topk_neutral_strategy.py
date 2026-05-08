from intraday.strategies.multi.bb_fade_topk_neutral_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["exit"] == "neutral_zone"
    assert ALPHA_CELL["universe"] == "basket_topk"
