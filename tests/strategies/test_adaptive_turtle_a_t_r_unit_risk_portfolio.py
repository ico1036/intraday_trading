from intraday.strategies.multi import AdaptiveTurtleATRUnitRiskPortfolio


def test_adaptive_turtle_a_t_r_unit_risk_portfolio_smoke():
    s = AdaptiveTurtleATRUnitRiskPortfolio(symbols=["BTCUSDT", "ETHUSDT"], lookback_minutes=30, top_n=1, bottom_n=1)
    assert hasattr(s, "calculate_rankings")
    assert hasattr(s, "generate_signals")
