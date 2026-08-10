# xs_volume_rank Live Runbook

This executor trades Binance USDⓈ-M perpetual futures from the latest durable
`weights.parquet`. It is deliberately fail-closed and dry-run by default.

## Account preparation

1. Use a dedicated Binance Futures account or sub-account with no unrelated
   positions or open orders.
2. Set position mode to **one-way**, not hedge mode.
3. Create an API key restricted to Futures trading, restrict it to the
   executor host IP, and disable withdrawals.
4. Store credentials outside git:

   ```bash
   export BINANCE_FUTURES_API_KEY='...'
   export BINANCE_FUTURES_API_SECRET='...'
   ```

5. Set the hard deployment cap in `config/live_xs_volume_rank.json`.
   `deployment_usdt` is gross target notional, not the full account balance.

## Safe rollout

Run testnet preflight and inspect every proposed order:

```bash
uv run python scripts/live_xs_volume_rank.py --testnet --json
```

Execute on testnet:

```bash
uv run python scripts/live_xs_volume_rank.py \
  --testnet --execute --confirm LIVE --json
```

Run mainnet preflight:

```bash
uv run python scripts/live_xs_volume_rank.py --json
```

Only after testnet and mainnet preflight are clean:

```bash
uv run python scripts/live_xs_volume_rank.py \
  --execute --confirm LIVE --json
```

The same signal fingerprint cannot execute twice. State is written under
`live/state/xs_volume_rank/`.

## Emergency stop

Create `live/KILL_SWITCH` to block all new runs:

```bash
touch live/KILL_SWITCH
```

This prevents new orders; it does not liquidate existing positions. Emergency
liquidation remains a deliberate manual account action until a separately
reviewed liquidation command is implemented.

## Daily sequence

1. Refresh daily market data.
2. Run the existing paper-forward job and verify today's `weights.parquet`.
3. Run live executor preflight.
4. Review gross/net, skipped minimum-notional targets, and order count.
5. Execute once after the prior UTC daily bar has closed.
6. Confirm the `.completed.json` reconciliation record.

Never schedule `--execute` until several testnet cycles have completed and
the exact production account configuration has been reviewed.
