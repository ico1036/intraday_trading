from intraday.strategies.multi.ts_burst_neutral_zone_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["exit"] == "neutral_zone"
    assert ALPHA_CELL["idea_family"] == "ts_burst_revert"
