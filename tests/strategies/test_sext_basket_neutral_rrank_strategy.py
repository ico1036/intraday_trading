from intraday.strategies.multi.sext_basket_neutral_rrank_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "rolling_rank"
    assert ALPHA_CELL["exit"] == "neutral_zone"
