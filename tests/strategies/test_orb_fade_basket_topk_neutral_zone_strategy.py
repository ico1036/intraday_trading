from intraday.strategies.multi.orb_fade_basket_topk_neutral_zone_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["exit"] == "neutral_zone"
    assert ALPHA_CELL["universe"] == "basket_topk"
