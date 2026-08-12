from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from executor_backend.chain.client import AgentContractClient
from executor_backend.chain.events import AgentEventIndexer, event_topic
from executor_backend.chain.rpc import JsonRpcClient
from executor_backend.chain.signer import ExecutorSigner
from executor_backend.config import load_config
from executor_backend.daemon import (
    init_agent_runtime,
    loop,
    run_once,
    service_status,
    start_service,
    stop_service,
    tail_log,
)
from executor_backend.hyper.client import HyperCoreClient
from executor_backend.runtime import RuntimePaths, append_jsonl, utc_now_iso, write_json
from executor_backend.services.nav import NavService, nav_change_bps
from executor_backend.services.reconciliation import ReconciliationService
from executor_backend.services.redeem import RedeemService
from executor_backend.services.trading_gateway import TradingServiceGateway


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("amount must be positive")
    return parsed


def nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("amount cannot be negative")
    return parsed


def usdc_asset_units(value: str) -> int:
    try:
        scaled = Decimal(value) * Decimal(10**6)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError("invalid USDC amount") from exc
    if not scaled.is_finite() or scaled <= 0 or scaled != scaled.to_integral_value():
        raise argparse.ArgumentTypeError("USDC amount must be positive with at most 6 decimals")
    return int(scaled)


def validate_manual_nav_settlement(
    assets: int,
    previous_assets: int,
    pending_core_deposits: int,
    pending_core_withdrawals: int,
    max_change_bps: int,
    force: bool,
) -> int:
    if pending_core_deposits or pending_core_withdrawals:
        raise ValueError("manual NAV settlement blocked while Core bridge accounting is pending")
    change_bps = nav_change_bps(assets, previous_assets)
    if previous_assets == 0 and not force:
        raise ValueError("initial manual NAV settlement requires --force")
    if change_bps > max_change_bps and not force:
        raise ValueError(
            f"NAV change {change_bps} bps exceeds limit {max_change_bps}; "
            "review and pass --force explicitly"
        )
    return change_bps


def build_agent_client(dry_run: bool, with_rpc: bool = True) -> AgentContractClient:
    cfg = load_config()
    signer = None
    if not dry_run:
        if cfg.signer.mode != "private_key":
            raise SystemExit(
                "send blocked while SIGNER_MODE is not private_key; "
                "review the operation and set SIGNER_MODE=private_key explicitly"
            )
        if cfg.network.name == "mainnet" and os.getenv("ALLOW_MAINNET_SEND") != "true":
            raise SystemExit(
                "mainnet send blocked; set ALLOW_MAINNET_SEND=true in the process environment"
            )
        if not cfg.signer.executor_private_key:
            raise SystemExit("EXECUTOR_PRIVATE_KEY is required for send mode")
        signer = ExecutorSigner.from_private_key(cfg.signer.executor_private_key)
        if cfg.agent.executor_address and signer.address.lower() != cfg.agent.executor_address.lower():
            raise SystemExit(
                f"EXECUTOR_PRIVATE_KEY address {signer.address} does not match EXECUTOR_ADDRESS {cfg.agent.executor_address}"
            )
    return AgentContractClient(
        cfg.agent.agent_address,
        rpc=JsonRpcClient(cfg.network.evm_rpc_url) if (with_rpc or not dry_run) else None,
        signer=signer,
        chain_id=cfg.network.chain_id,
        dry_run=dry_run,
        gas_limit=cfg.signer.gas_limit,
        core_deposit_wallet=cfg.agent.core_deposit_wallet,
        spot_destination_dex=cfg.agent.spot_destination_dex,
        usdc_token_index=cfg.agent.usdc_token_index,
        core_usdc_wei_per_asset_unit=cfg.agent.core_usdc_wei_per_asset_unit,
    )


def tx_payload(
    *,
    cfg,
    command: str,
    result,
    params: dict[str, Any] | None = None,
    requires_hypercore_verification: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": "tx",
        "command": command,
        "agent_address": cfg.agent.agent_address,
        "params": params or {},
        "tx": {
            "status": result.status,
            "hash": result.tx_hash,
            "calldata": result.calldata,
            "dry_run": result.dry_run,
        },
        "created_at": utc_now_iso(),
    }
    if requires_hypercore_verification:
        payload["requires_hypercore_verification"] = True
        payload["verify_hint"] = (
            "Treat the HyperEVM transaction as submitted only. Run hyper-state and confirm "
            "HyperCore ledger/balances before any confirm-* command."
        )
    return payload


def emit_tx(
    *,
    cfg,
    command: str,
    result,
    params: dict[str, Any] | None = None,
    requires_hypercore_verification: bool = False,
) -> None:
    payload = tx_payload(
        cfg=cfg,
        command=command,
        result=result,
        params=params,
        requires_hypercore_verification=requires_hypercore_verification,
    )
    paths = RuntimePaths.from_agent(cfg.agent.agent_address)
    paths.ensure()
    append_jsonl(paths.operations, payload)
    print(json.dumps(payload, sort_keys=True, indent=2))


def add_common_send_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--send", action="store_true", help="sign with EXECUTOR_PRIVATE_KEY and broadcast")


def main() -> None:
    parser = argparse.ArgumentParser(prog="hyper-agent-executor")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("config")
    sub.add_parser("agent-init")

    service = sub.add_parser("service")
    service_sub = service.add_subparsers(dest="service_cmd", required=True)
    service_sub.add_parser("status")
    service_sub.add_parser("stop")
    service_logs = service_sub.add_parser("logs")
    service_logs.add_argument("--lines", type=int, default=80)
    service_run_once = service_sub.add_parser("run-once")
    service_run_once.add_argument("--json", action="store_true")
    service_start = service_sub.add_parser("start")
    service_start.add_argument("--interval", type=int, default=300)
    service_loop = service_sub.add_parser("loop")
    service_loop.add_argument("--interval", type=int, default=300)

    state_cmd = sub.add_parser("hyper-state")
    state_cmd.add_argument("--user", help="defaults to AGENT_ADDRESS")

    logs_cmd = sub.add_parser("logs")
    logs_cmd.add_argument("--from-block", type=int, required=True)
    logs_cmd.add_argument("--to-block", default="latest")
    logs_cmd.add_argument("--event", help="event signature, e.g. DailyNavSettled(uint64,uint64,uint256,uint256,uint256,address,bytes32)")

    reconcile = sub.add_parser("reconcile")
    reconcile.add_argument("--agent-evm-usdc", type=int, required=True)
    reconcile.add_argument("--tracked-core-usdc", type=int, required=True)
    reconcile.add_argument("--pending-core-deposits", type=int, default=0)
    reconcile.add_argument("--pending-core-withdrawals", type=int, required=True)

    redeem = sub.add_parser("prepare-redeem-liquidity")
    redeem.add_argument("--confirmed-redeem-amount", type=positive_int, required=True)
    redeem.add_argument("--agent-evm-idle", type=nonnegative_int, required=True)
    redeem.add_argument("--accounted-evm-idle", type=nonnegative_int, required=True)
    redeem.add_argument("--pending-core-withdrawals", type=nonnegative_int, required=True)
    redeem.add_argument("--hypercore-free-usdc", type=nonnegative_int, required=True)
    redeem.add_argument("--request-id", required=True)
    redeem.add_argument("--deadline", required=True)

    nav_preview = sub.add_parser("nav-preview")
    nav_preview.add_argument("--day", type=positive_int, required=True)
    nav_preview.add_argument(
        "--evm-idle-usdc", type=int, required=True, help="raw observed HyperEVM token balance"
    )
    nav_preview.add_argument(
        "--accounted-evm-usdc",
        type=int,
        required=True,
        help="protocol-accounted HyperEVM balance from accountedEvmUsdc()",
    )
    nav_preview.add_argument("--reserved-redeem", type=int, default=0)
    nav_preview.add_argument("--pending-core-deposits", type=int, default=0)
    nav_preview.add_argument("--pending-core-withdrawals", type=int, default=0)

    chain_state = sub.add_parser("agent-chain-state")
    chain_state.add_argument("--json", action="store_true")

    nav_cycle = sub.add_parser("nav-cycle")
    add_common_send_flags(nav_cycle)
    nav_cycle.add_argument("--day", type=positive_int, help="defaults to current UTC yyyymmdd")
    nav_cycle.add_argument(
        "--max-change-bps", type=nonnegative_int, help="defaults to MAX_NAV_CHANGE_BPS"
    )

    nav_settle = sub.add_parser("nav-settle")
    add_common_send_flags(nav_settle)
    nav_settle.add_argument("--day", type=positive_int, required=True)
    nav_settle.add_argument(
        "--assets",
        type=nonnegative_int,
        required=True,
        help="accounted total assets from a reviewed snapshot",
    )
    nav_settle.add_argument("--snapshot-hash", required=True)
    nav_settle.add_argument(
        "--force",
        action="store_true",
        help="allow an initial or over-limit manual settlement after explicit review",
    )

    auth = sub.add_parser("authorize-approved")
    add_common_send_flags(auth)
    auth.add_argument("--wallet", help="defaults to EXECUTOR_ADDRESS in collapsed-role mode")
    auth.add_argument("--name", default="executor")

    deposit = sub.add_parser("deposit-core")
    add_common_send_flags(deposit)
    deposit.add_argument("--amount", type=positive_int, required=True)

    confirm_deposit = sub.add_parser("confirm-core-deposit")
    add_common_send_flags(confirm_deposit)
    confirm_deposit.add_argument("--amount", type=positive_int, required=True)

    withdraw = sub.add_parser("withdraw-core")
    add_common_send_flags(withdraw)
    withdraw_amount = withdraw.add_mutually_exclusive_group(required=True)
    withdraw_amount.add_argument(
        "--amount-usdc",
        dest="amount_asset_units",
        type=usdc_asset_units,
        help="human USDC amount; converted using Agent coreUsdcWeiPerAssetUnit",
    )
    withdraw_amount.add_argument(
        "--amount-wei",
        type=positive_int,
        help="raw spotSend units; USDC normally uses 1 USDC = 100,000,000",
    )
    withdraw.add_argument(
        "--fee-buffer-usdc",
        type=usdc_asset_units,
        default=10_000,
        help="minimum spot USDC left for dynamic fees (default: 0.01)",
    )

    confirm = sub.add_parser("confirm-withdrawal")
    add_common_send_flags(confirm)
    confirm.add_argument("--amount", type=positive_int, required=True)

    move = sub.add_parser("move-usdc")
    add_common_send_flags(move)
    move_amount = move.add_mutually_exclusive_group(required=True)
    move_amount.add_argument(
        "--amount-usdc",
        dest="amount_asset_units",
        type=usdc_asset_units,
        help="human USDC amount; usdClassTransfer uses 1 USDC = 1,000,000",
    )
    move_amount.add_argument(
        "--amount-wei",
        type=positive_int,
        help="raw usdClassTransfer units; 1 USDC = 1,000,000",
    )
    move.add_argument("--to-perp", action="store_true")

    args = parser.parse_args()
    cfg = load_config()
    if args.cmd == "config":
        print(cfg)
        return
    if args.cmd == "agent-init":
        paths = init_agent_runtime(cfg)
        print(
            json.dumps(
                {
                    "agent_address": cfg.agent.agent_address,
                    "runtime_dir": str(paths.agent_dir),
                    "config_env": str(paths.config_env),
                    "operations": str(paths.operations),
                    "log": str(paths.executor_log),
                },
                sort_keys=True,
                indent=2,
            )
        )
        return
    if args.cmd == "service":
        if args.service_cmd == "start":
            print(json.dumps(start_service(cfg, args.interval), sort_keys=True, indent=2))
        elif args.service_cmd == "stop":
            print(json.dumps(stop_service(cfg), sort_keys=True, indent=2))
        elif args.service_cmd == "status":
            print(json.dumps(service_status(cfg), sort_keys=True, indent=2))
        elif args.service_cmd == "logs":
            print(tail_log(cfg, args.lines))
        elif args.service_cmd == "run-once":
            report = run_once(cfg)
            if args.json:
                print(json.dumps(report, sort_keys=True, indent=2))
            else:
                state = report["hypercore"]
                print(
                    "checked "
                    f"agent={report['agent_address']} "
                    f"spot_usdc={state['spot_usdc']} "
                    f"perp_account_value={state['perp_account_value']} "
                    f"perp_withdrawable={state['perp_withdrawable']} "
                    f"ledger_items={len(state['ledger'])}"
                )
        elif args.service_cmd == "loop":
            loop(cfg, args.interval)
        return

    if args.cmd == "hyper-state":
        hyper = HyperCoreClient(cfg.network.hypercore_api_url)
        state = hyper.fetch_state(args.user or cfg.agent.agent_address)
        print(state)
        return
    if args.cmd == "logs":
        rpc = JsonRpcClient(cfg.network.evm_rpc_url)
        indexer = AgentEventIndexer(rpc, cfg.agent.agent_address)
        to_block = int(args.to_block) if str(args.to_block).isdigit() else args.to_block
        topics = [event_topic(args.event)] if args.event else None
        for log in indexer.get_logs(args.from_block, to_block, topics):
            print(log)
        return

    if args.cmd == "reconcile":
        hyper = HyperCoreClient(cfg.network.hypercore_api_url)
        service = ReconciliationService(hyper)
        report = service.build_report(
            cfg.agent.agent_address,
            args.agent_evm_usdc,
            args.tracked_core_usdc,
            args.pending_core_deposits,
            args.pending_core_withdrawals,
        )
        print(service.to_json(report))
        return
    if args.cmd == "prepare-redeem-liquidity":
        trading = TradingServiceGateway(cfg.trading_service)
        service = RedeemService(
            AgentContractClient(cfg.agent.agent_address),
            trading,
            cfg.redeem_liquidity_buffer_bps,
        )
        plan = service.plan_liquidity(
            args.confirmed_redeem_amount,
            args.agent_evm_idle,
            args.accounted_evm_idle,
            args.pending_core_withdrawals,
            args.hypercore_free_usdc,
            cfg.agent.agent_address,
        )
        result = service.prepare_liquidity(plan, args.request_id, args.deadline)
        print(
            json.dumps(
                {
                    "plan": asdict(plan),
                    "status": result["status"],
                    "trading_result": result["trading_result"],
                },
                sort_keys=True,
                indent=2,
                default=str,
            )
        )
        return
    if args.cmd == "nav-preview":
        agent = AgentContractClient(cfg.agent.agent_address)
        hyper = HyperCoreClient(cfg.network.hypercore_api_url)
        nav = NavService(agent, hyper)
        snapshot = nav.preview(
            cfg.agent.agent_address,
            args.day,
            args.evm_idle_usdc,
            args.accounted_evm_usdc,
            args.reserved_redeem,
            args.pending_core_withdrawals,
            pending_core_deposits=args.pending_core_deposits,
        )
        print(nav.to_json(snapshot))
        return
    if args.cmd == "agent-chain-state":
        agent = build_agent_client(dry_run=True, with_rpc=True)
        state = agent.read_chain_state().to_dict()
        print(json.dumps(state, sort_keys=True, indent=2) if args.json else state)
        return
    if args.cmd == "nav-cycle":
        day = args.day or int(datetime.now(UTC).strftime("%Y%m%d"))
        agent = build_agent_client(dry_run=not args.send, with_rpc=True)
        chain_state = agent.read_chain_state()
        hyper = HyperCoreClient(cfg.network.hypercore_api_url)
        nav = NavService(agent, hyper)
        snapshot = nav.preview(
            cfg.agent.agent_address,
            day,
            chain_state.evm_idle_usdc,
            chain_state.accounted_evm_usdc,
            chain_state.reserved_redeem_amount,
            chain_state.pending_core_withdrawals,
            chain_state.last_settled_share_price or chain_state.initial_share_price or 10**18,
            pending_core_deposits=chain_state.pending_core_deposits,
        )
        max_change_bps = args.max_change_bps if args.max_change_bps is not None else cfg.max_nav_change_bps
        previous_assets = chain_state.last_settled_total_assets
        change_bps = nav_change_bps(snapshot.settled_total_assets, previous_assets)
        safe_to_send = previous_assets == 0 or change_bps <= max_change_bps
        tx = None
        if args.send:
            if not safe_to_send:
                raise SystemExit(
                    f"NAV change {change_bps} bps exceeds limit {max_change_bps}; review manually"
                )
            tx = nav.settle(snapshot)
        else:
            tx = agent.settle_daily_nav(day, snapshot.settled_total_assets, snapshot.snapshot_hash)
        paths = RuntimePaths.from_agent(cfg.agent.agent_address)
        paths.ensure()
        snapshot_path = paths.nav_snapshots / f"{day}-{snapshot.snapshot_hash[2:10]}.json"
        payload = {
            "type": "nav_cycle",
            "mode": "send" if args.send else "assisted",
            "agent_chain_state": chain_state.to_dict(),
            "snapshot": json.loads(nav.to_json(snapshot)),
            "checks": {
                "previous_assets": previous_assets,
                "change_bps": change_bps,
                "max_change_bps": max_change_bps,
                "safe_to_send": safe_to_send,
            },
            "tx": {
                "status": tx.status if tx else None,
                "hash": tx.tx_hash if tx else None,
                "calldata": tx.calldata if tx else None,
                "dry_run": tx.dry_run if tx else None,
            },
            "created_at": utc_now_iso(),
        }
        if not cfg.auto_nav:
            payload["automation_hint"] = (
                "After validating this daily NAV flow, set ENABLE_AUTO_NAV=true and restart "
                "the service to submit one guarded settlement per UTC day."
            )
        write_json(snapshot_path, payload)
        append_jsonl(paths.operations, payload)
        print(json.dumps({**payload, "snapshot_path": str(snapshot_path)}, sort_keys=True, indent=2))
        return
    agent = build_agent_client(dry_run=not args.send)
    if args.cmd == "nav-settle":
        chain_state = agent.read_chain_state()
        try:
            change_bps = validate_manual_nav_settlement(
                assets=args.assets,
                previous_assets=chain_state.last_settled_total_assets,
                pending_core_deposits=chain_state.pending_core_deposits,
                pending_core_withdrawals=chain_state.pending_core_withdrawals,
                max_change_bps=cfg.max_nav_change_bps,
                force=args.force,
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        emit_tx(
            cfg=cfg,
            command="nav-settle",
            result=agent.settle_daily_nav(args.day, args.assets, args.snapshot_hash),
            params={
                "day": args.day,
                "assets": args.assets,
                "snapshot_hash": args.snapshot_hash,
                "change_bps": change_bps,
                "force": args.force,
            },
        )
    elif args.cmd == "authorize-approved":
        wallet = args.wallet or cfg.agent.executor_address
        if not wallet:
            raise SystemExit("--wallet or EXECUTOR_ADDRESS is required")
        emit_tx(
            cfg=cfg,
            command="authorize-approved",
            result=agent.authorize_approved_wallet(wallet, args.name),
            params={"wallet": wallet, "name": args.name},
            requires_hypercore_verification=True,
        )
    elif args.cmd == "deposit-core":
        try:
            preflight = agent.core_deposit_preflight(args.amount)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        emit_tx(
            cfg=cfg,
            command="deposit-core",
            result=agent.deposit_usdc_to_core(args.amount, preflight=False),
            params={"amount": args.amount, "preflight": preflight},
            requires_hypercore_verification=True,
        )
    elif args.cmd == "confirm-core-deposit":
        emit_tx(
            cfg=cfg,
            command="confirm-core-deposit",
            result=agent.confirm_core_deposit(args.amount),
            params={"amount": args.amount},
        )
    elif args.cmd == "withdraw-core":
        runtime_config = agent.resolve_runtime_config()
        scale = runtime_config["core_usdc_wei_per_asset_unit"]
        amount_wei = (
            args.amount_wei if args.amount_wei is not None else args.amount_asset_units * scale
        )
        if amount_wei % scale != 0:
            raise SystemExit(f"--amount-wei must be divisible by Agent unit scale {scale}")
        amount_asset_units = amount_wei // scale
        if amount_wei > 2**64 - 1:
            raise SystemExit("withdraw-core amount exceeds uint64 raw action limit")
        if args.send:
            spot_usdc_available = HyperCoreClient(cfg.network.hypercore_api_url).fetch_state(
                cfg.agent.agent_address
            ).spot_usdc_available
            if amount_asset_units + args.fee_buffer_usdc > spot_usdc_available:
                raise SystemExit(
                    "withdraw-core blocked: requested amount plus fee buffer exceeds "
                    f"observed available spot USDC ({spot_usdc_available} asset units)"
                )
        emit_tx(
            cfg=cfg,
            command="withdraw-core",
            result=agent.request_core_withdrawal(amount_wei),
            params={
                "amount_usdc_units": amount_asset_units,
                "amount_wei": amount_wei,
                "core_usdc_wei_per_asset_unit": scale,
                "fee_buffer_usdc_units": args.fee_buffer_usdc,
            },
            requires_hypercore_verification=True,
        )
    elif args.cmd == "confirm-withdrawal":
        emit_tx(
            cfg=cfg,
            command="confirm-withdrawal",
            result=agent.confirm_core_withdrawal(args.amount),
            params={"amount": args.amount},
        )
    elif args.cmd == "move-usdc":
        amount_wei = (
            args.amount_wei if args.amount_wei is not None else args.amount_asset_units
        )
        if amount_wei > 2**64 - 1:
            raise SystemExit("move-usdc amount exceeds uint64 raw action limit")
        if args.send:
            core_state = HyperCoreClient(cfg.network.hypercore_api_url).fetch_state(
                cfg.agent.agent_address
            )
            available = (
                core_state.spot_usdc_available
                if args.to_perp
                else core_state.perp_withdrawable
            )
            if amount_wei > available:
                source = "spot" if args.to_perp else "perp withdrawable"
                raise SystemExit(
                    f"move-usdc blocked: amount exceeds observed {source} USDC "
                    f"({available} asset units)"
                )
        emit_tx(
            cfg=cfg,
            command="move-usdc",
            result=agent.move_usdc_class(amount_wei, args.to_perp),
            params={
                "amount_usdc_units": amount_wei,
                "amount_wei": amount_wei,
                "to_perp": args.to_perp,
            },
            requires_hypercore_verification=True,
        )


if __name__ == "__main__":
    main()
