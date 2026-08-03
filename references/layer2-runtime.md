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

Daemon modes:

| Mode | Behavior |
| --- | --- |
| `observe` | Read state and write reports only |
| `assisted` | Generate reports and suggested commands; human confirms sends |
| `auto` | Send narrowly allowed Executor transactions after checks pass |

Default to `assisted`. In assisted mode the daemon writes observations and suggested commands; it does not automatically confirm deposits/withdrawals or settle NAV without an explicit `--send`.

Recommended automation:

- Safe: `service run-once`, `agent-chain-state`, HyperCore checks, NAV preview, reconcile reports.
- Assisted: `nav-cycle`, `nav-settle`, `confirm-core-deposit`, `confirm-withdrawal`.
- Manual only: owner config, `syncCoreAccounting`, upgrades, pause/unpause.
