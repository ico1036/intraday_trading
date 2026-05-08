from intraday.strategies.multi.donchian_fade_intraday_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["horizon"] == "intraday"
    assert ALPHA_CELL["idea_family"] == "donchian_fade"
