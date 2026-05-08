from intraday.strategies.multi.donchian_fade_single_btc_composite_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "composite"
    assert ALPHA_CELL["universe"] == "single"
    assert ALPHA_CELL["idea_family"] == "donchian_fade"
