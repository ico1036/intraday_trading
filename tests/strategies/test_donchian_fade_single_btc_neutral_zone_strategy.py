from intraday.strategies.multi.donchian_fade_single_btc_neutral_zone_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["exit"] == "neutral_zone"
    assert ALPHA_CELL["idea_family"] == "donchian_fade"
