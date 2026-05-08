from intraday.strategies.multi.burst_then_fade_basket_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["idea_family"] == "burst_then_fade"
