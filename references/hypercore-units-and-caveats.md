# HyperCore Units And Caveats

## Units

HyperEVM USDC asset units:

```text
1 USDC = 1_000_000
```

`usdClassTransfer` amount:

```text
1 USDC = 1_000_000
```

`spotSend` withdrawal amount:

```text
1 USDC = 100_000_000
```

The contract converts `spotSend` amount to asset units with `CORE_USDC_WEI_PER_ASSET_UNIT`, normally `100`.

Prefer the CLI's human-unit form:

```text
move-usdc --amount-usdc 1
withdraw-core --amount-usdc 1
```

The legacy `--amount-wei` form remains available for exact raw actions, but the two actions use
different raw scales as documented above. Sending a withdrawal also checks the observed spot
available balance (`total - hold`) and preserves the configured CLI fee buffer. Spot-to-perp
transfers use the same available-balance check so funds held by open orders are not treated as free.

## Testnet Caveats

CoreWriter / deposit wallet HyperEVM transactions can succeed even when HyperCore does not apply the action.

Observed testnet caveat:

- Agent HyperEVM USDC -> CoreDepositWallet -> HyperCore spot can show successful HyperEVM receipt;
- Agent USDC can move to the deposit wallet / system address;
- HyperCore ledger and spot balance may still show no credit for fresh testnet Agent addresses.

Operational rule:

- Never confirm a core deposit from HyperEVM receipt alone.
- Confirm only after HyperCore ledger or balance proves the funds arrived.
- Never settle NAV while `pendingCoreDeposits` or `pendingCoreWithdrawals` is non-zero.

Spot -> HyperEVM withdrawal caveat:

- Leave spot USDC for dynamic fees.
- Full-balance spotSend can produce a successful HyperEVM tx but no HyperCore state change.
- Treat a CoreWriter `spotSend` receipt only as "submitted"; it is successful only after HyperCore
  shows a `spotTransfer` ledger item to `0x2000000000000000000000000000000000000000`
  and the Agent HyperEVM USDC balance increases.
- Do not call `confirm-withdrawal` until the HyperEVM USDC balance increase is observed.
- If a full-balance withdrawal was submitted and HyperCore did not apply it, restore accounting with
  `syncCoreAccounting(actualSpotUsdc, 0, 0)` after manual review.

Example from testnet:

```text
Agent spot before: 49.494542 USDC
Full-balance spotSend 49.494542 USDC:
  HyperEVM tx succeeded, but HyperCore spot stayed unchanged.

Partial spotSend 20 USDC:
  HyperCore ledger: spotTransfer amount=20.0 to 0x2000000000000000000000000000000000000000
  fee: 0.00064 USDC
  Agent HyperEVM USDC increased by 20 USDC
  Agent spot after: 29.493902 USDC
```

Operational recommendation:

```text
withdraw_amount < spot_balance
leave a conservative fee buffer in spot
prefer small test withdrawal before a larger withdrawal
```
