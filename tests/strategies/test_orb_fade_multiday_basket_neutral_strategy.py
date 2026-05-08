from intraday.strategies.multi.orb_fade_multiday_basket_neutral_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["exit"] == "neutral_zone"
    assert ALPHA_CELL["horizon"] == "multi_day"
