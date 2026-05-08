from intraday.strategies.multi.orb_fade_basket_signal_pctile_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["exit"] == "neutral_zone"
    assert ALPHA_CELL["idea_family"] == "orb_fade"
