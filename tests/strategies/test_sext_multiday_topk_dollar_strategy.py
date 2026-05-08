from intraday.strategies.multi.sext_multiday_topk_dollar_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["bar"] == "DOLLAR"
