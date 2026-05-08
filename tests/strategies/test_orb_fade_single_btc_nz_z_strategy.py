from intraday.strategies.multi.orb_fade_single_btc_nz_z_strategy import ALPHA_CELL


def test_metadata():
    assert ALPHA_CELL["transform"] == "z_score"
    assert ALPHA_CELL["exit"] == "neutral_zone"
    assert ALPHA_CELL["universe"] == "single"
