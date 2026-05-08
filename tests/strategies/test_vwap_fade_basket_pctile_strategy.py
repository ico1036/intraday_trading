from intraday.strategies.multi.vwap_fade_basket_pctile_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "percentile"
    assert ALPHA_CELL["idea_family"] == "vwap_fade"
