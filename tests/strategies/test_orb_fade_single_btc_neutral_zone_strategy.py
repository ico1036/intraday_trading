from intraday.strategies.multi.orb_fade_single_btc_neutral_zone_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["universe"] == "single"
    assert ALPHA_CELL["exit"] == "neutral_zone"
    assert ALPHA_CELL["idea_family"] == "orb_fade"
