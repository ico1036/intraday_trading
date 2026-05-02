from intraday.strategies.multi import TurtleAtrCertificationStopLossStrategy


def test_turtle_atr_certification_stop_loss_strategy_smoke():
    s = TurtleAtrCertificationStopLossStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
