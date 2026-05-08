from intraday.strategies.multi.orb_fade_topk_neutral_rrank_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "rolling_rank"
    assert ALPHA_CELL["exit"] == "neutral_zone"
