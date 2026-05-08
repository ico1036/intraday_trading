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

The deterministic CLI defaults to 1m futures bars:

```bash
uv run python scripts/tools/backtest.py \
  --data-type bars \
  --strategy MyAlphaStrategy \
  --symbols BTCUSDT ETHUSDT \
  --data-path data/futures_klines \
  --start "2026-04-01 00:00:00" \
  --end "2026-04-30 23:59:00" \
  --output-dir archive/manual/MyAlphaStrategy/is \
  --json
```

The runnable example is:

```bash
uv run python scripts/run_manual_backtest.py --help
uv run python scripts/run_manual_backtest.py \
  --symbols BTCUSDT ETHUSDT \
  --start "2025-03-01" \
  --end "2025-03-31 23:59:59"
```

It is intentionally written as a learning file. To test your own strategy,
edit `build_strategy()` in `scripts/run_manual_backtest.py`.

The underlying shape is:

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
- Runnable example: `scripts/run_manual_backtest.py`
- Backtest runner: `src/intraday/backtest/multi_tick_runner.py`
- Data loader: `src/intraday/data/loader.py`
- Artifact contract: `docs/ALPHA_ARTIFACT_CONTRACT.md`
