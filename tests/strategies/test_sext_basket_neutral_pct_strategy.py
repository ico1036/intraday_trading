from intraday.strategies.multi.sext_basket_neutral_pct_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "percentile"
    assert ALPHA_CELL["exit"] == "neutral_zone"
