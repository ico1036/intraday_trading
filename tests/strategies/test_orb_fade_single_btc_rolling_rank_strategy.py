from intraday.strategies.multi.orb_fade_single_btc_rolling_rank_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "rolling_rank"
