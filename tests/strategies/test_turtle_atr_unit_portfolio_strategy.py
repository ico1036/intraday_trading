from intraday.strategies.multi import TurtleAtrUnitPortfolioStrategy


def test_turtle_atr_unit_portfolio_strategy_smoke():
    s = TurtleAtrUnitPortfolioStrategy(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
