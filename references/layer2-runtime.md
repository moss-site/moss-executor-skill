# Layer2 Runtime

Layer2 is a lightweight Executor runtime:

```text
CLI commands + daemon watcher + local JSON/log evidence
```

No database is required in v1. The packaged skill installs backend code under `~/.moss-hyper-agent/executor-backend/current` and stores Agent runtime state under `~/.moss-hyper-agent/agents/<agent-id>/`.

Authoritative state:

- Agent contract state and events;
- HyperCore spot/perp/ledger;
- HyperEVM token balances.

Local evidence:

```text
~/.moss-hyper-agent/agents/<agent-id>/
├── config.env
├── service.pid
├── service_state.json
├── last_seen.json
├── operations.jsonl
├── nav_snapshots/
└── logs/
```

The default is assisted operation: the daemon reads state and writes reports, while transaction commands require explicit `--send`. `ENABLE_AUTO_NAV=true` is the one supported send-capable daemon switch. After the service is restarted, it attempts at most one `nav-cycle --send` per UTC day. It still fails closed on pending Core accounting, excessive NAV change, missing/mismatched signer, and missing mainnet acknowledgement.

Recommended automation:

- Safe: `service run-once`, `agent-chain-state`, HyperCore checks, NAV preview, reconcile reports.
- Optional automatic: daily `nav-cycle` only, after a successful manual cycle and explicit `ENABLE_AUTO_NAV=true`.
- Assisted: `nav-settle`, `confirm-core-deposit`, `confirm-withdrawal`, all Core transfers.
- Manual only: owner config, `syncCoreAccounting`, upgrades, pause/unpause.
