from intraday.strategies.multi.bb_fade_basket_ts_zstrategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "z_score"
    assert ALPHA_CELL["exit"] == "time_stop"
    assert ALPHA_CELL["universe"] == "basket_full"
