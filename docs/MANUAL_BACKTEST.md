# Manual Backtest

Use this path when you do not want the agent.

## 1. Write A Strategy

Copy the portfolio alpha template:

```bash
cp src/intraday/strategies/multi/_alpha_template.py \
  src/intraday/strategies/multi/my_alpha.py
```

Edit only the copied strategy. Keep:

- `symbols: list[str]`
- `generate_order(self, state) -> PortfolioOrder | None`
- `Order(weight=...)` target weights

`symbols=["BTCUSDT"]` is the single-coin case. There is no separate
single-coin template.

## 2. Run A Backtest

Use `PortfolioTickBacktestRunner` directly:

```python
from datetime import datetime
from pathlib import Path

from intraday.backtest.multi_tick_runner import PortfolioTickBacktestRunner
from intraday.candle_builder import CandleType
from intraday.data import TickDataLoader
from intraday.strategies.multi.my_alpha import MyAlphaStrategy

symbols = ["BTCUSDT", "ETHUSDT"]
data_base = Path("data/futures_ticks")
loaders = {
    symbol: TickDataLoader(data_base / symbol / "2025", symbol=symbol)
    for symbol in symbols
}

strategy = MyAlphaStrategy(symbols=symbols)
runner = PortfolioTickBacktestRunner(
    strategy=strategy,
    data_loaders=loaders,
    bar_type=CandleType.VOLUME,
    bar_size=20.0,
    initial_capital=100_000.0,
    position_size_pct=1.0,
    leverage=1,
)

result = runner.run(
    start_time=datetime(2025, 3, 1),
    end_time=datetime(2025, 3, 31, 23, 59, 59),
)

print(result.total_return, result.profit_factor, result.total_trades)
```

## Core Files

- Strategy template: `src/intraday/strategies/multi/_alpha_template.py`
- Backtest runner: `src/intraday/backtest/multi_tick_runner.py`
- Data loader: `src/intraday/data/loader.py`
- Artifact contract: `docs/ALPHA_ARTIFACT_CONTRACT.md`
