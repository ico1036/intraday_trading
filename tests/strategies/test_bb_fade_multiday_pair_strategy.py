from intraday.strategies.multi.bb_fade_multiday_pair_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["horizon"] == "multi_day"
    assert ALPHA_CELL["universe"] == "pair"
