from intraday.strategies.multi.orb_fade_basket_topk_percentile_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "percentile"
    assert ALPHA_CELL["universe"] == "basket_topk"
