from intraday.strategies.multi.orb_fade_multiday_single_btc_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["horizon"] == "multi_day"
    assert ALPHA_CELL["universe"] == "single"
