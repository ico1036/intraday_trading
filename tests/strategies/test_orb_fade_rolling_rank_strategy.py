from intraday.strategies.multi.orb_fade_rolling_rank_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "rolling_rank"
    assert ALPHA_CELL["idea_family"] == "orb_fade"
