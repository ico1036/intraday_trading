from intraday.strategies.multi.range_position_basket_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["idea_family"] == "range_position_xs"
    assert ALPHA_CELL["universe"] == "basket_full"
