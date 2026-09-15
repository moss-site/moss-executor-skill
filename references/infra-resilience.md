# HyperCore read resilience (2026-09-15)

Baseline: `48e7b4e`. Review and merge this PR before updating fleet skill pins.
No live API writes, NAV settlements, or daemon restarts were performed for this PR.

## Bugs

- `HyperCoreClient.post_info()` issued one un-retried HTTP request. Temporary 429,
  5xx or connection failure aborted an otherwise read-only NAV/state operation.
- Every 300s daemon observation fetched `userNonFundingLedgerUpdates` without a
  time filter, even though `run_once` only used balances/positions for its watcher
  report and suggestions. Each instance repeated this unnecessary ledger read.
- The daemon polled with a fixed interval after failures, without jitter or
  honoring Retry-After, producing synchronized fleet retry load.
- There was no explicit read-provider override separate from deployment's
  network/signing URL convention.

## Changes / invariants

- `HYPERCORE_INFO_URL` optionally overrides `HYPERCORE_API_URL` for this backend's
  read-only HyperCore client. Use the native `/info` base (e.g.
  `https://provider.example`), NOT `/hypercore` or `/info`. It does not change
  NETWORK/CHAIN_ID, EVM RPC, signer, or trading-service endpoint.
- Read transport uses at most 4 attempts / nominal 45s budget, individual timeout
  <=10s, exponential jitter, Retry-After seconds/date. Only 408/429/selected5xx and
  network failures retry. 401/403, malformed JSON and permanent errors fail closed.
  A Retry-After longer than the budget is surfaced, not shortened.
- `[INFO_RETRY_EXHAUSTED]` is a machine-readable signal to orchestration: do not
  retry the whole command again after this HTTP retry policy finishes.
- `fetch_state(..., include_ledger=False)` is used ONLY by background observation.
  Its report explicitly includes `ledger_included=false`; an empty list is not
  presented as evidence of no transfers. NAV, funding evidence and reconciliation
  retain the default `include_ledger=True` and all original accounting gates.
- Daemon startup/normal interval get jitter; read failures back off and honor
  Retry-After, then reset after success. Errors remain visible in service state.
- Transaction broadcast, nonce handling, NAV force thresholds, accounting confirm,
  fees and amounts are untouched. No cached balances or partial snapshots.

## Validation

`PYTHONPATH=executor-backend python -m unittest discover -s executor-backend/tests`

Includes 429 then success, permanent auth failure, long Retry-After, transport
failure, read URL selection, watcher skip versus default ledger inclusion, and
live-loop recovery/backoff/reset with mocked network/time. All tests are offline.
Read-provider compatibility was separately probed by the operator; production
rate/capacity, all-agent stability and NAV correctness need deployment verification.
