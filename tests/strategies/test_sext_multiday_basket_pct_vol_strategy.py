from intraday.strategies.multi.sext_multiday_basket_pct_vol_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["bar"] == "VOLUME"
