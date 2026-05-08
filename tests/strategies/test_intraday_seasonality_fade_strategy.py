from intraday.strategies.multi.intraday_seasonality_fade_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["idea_family"] == "intraday_seasonality"
