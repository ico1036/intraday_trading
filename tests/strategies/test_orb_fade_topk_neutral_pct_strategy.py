from intraday.strategies.multi.orb_fade_topk_neutral_pct_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "percentile"
    assert ALPHA_CELL["universe"] == "basket_topk"
    assert ALPHA_CELL["exit"] == "neutral_zone"
