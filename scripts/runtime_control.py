#!/usr/bin/env python3
"""Small local control wrapper for an installed automation runtime."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit


TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(TOOLS_ROOT / "templates" / "local-automation-runtime"))
from atlas_runtime_config import (  # noqa: E402
    RuntimeConfigError,
    load_runtime_config,
    normalize_provider,
    validate_runtime_path,
)

AZURE_COMMANDS = {"status", "repos", "projects", "models", "sync", "azure-inspect", "azure-worker", "azure-reconcile", "azure-dispatch",
                  "azure-supervise", "azure-intake", "azure-approval"}
MUTATING_FLAGS = {
    "--apply",
    "--publish",
    "--merge",
    "--close-issues",
    "--review-apply",
    "--post-cycle-summary",
}


def positive_int(raw: str) -> int:
    value = int(raw)
    if value < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return value


def runtime_dir(args: argparse.Namespace) -> Path:
    configured = getattr(args, "runtime_config", None)
    raw = args.runtime_dir or os.environ.get("ATLAS_RUNTIME_DIR")
    if raw is None and configured is not None:
        raw = configured.runtime_dir
    return validate_runtime_path(raw)


def runtime_script(root: Path, name: str) -> str:
    try:
        script = (root / name).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise RuntimeConfigError(f"missing runtime script: {name}") from exc
    if not script.is_file() or root not in script.parents or script.stat().st_uid != os.getuid():
        raise RuntimeConfigError("runtime script must be an owned file inside the explicit runtime directory")
    return str(script)


def run_runtime(root: Path, command: list[str], *, preview: bool = False) -> int:
    root = validate_runtime_path(root)
    runtime_script(root, str(Path(command[0]).relative_to(root)))
    if preview:
        print(json.dumps({"mode": "preview", "dispatched": False, "completion": False, "cwd": str(root), "argv": command}, indent=2))
        return 0
    print("+ " + shlex.join(command), flush=True)
    env = os.environ.copy()
    env["PWD"] = str(root)
    return subprocess.run(command, cwd=root, env=env).returncode


def require_yes(name: str, command: list[str], yes: bool) -> None:
    flags = sorted(flag for flag in MUTATING_FLAGS if flag in command)
    if flags and not yes:
        raise SystemExit(f"{name} would pass mutating flag(s) {', '.join(flags)}; rerun with --yes.")


def require_execution_yes(args: argparse.Namespace) -> None:
    if not getattr(args, "dry_run", False) and not getattr(args, "yes", False):
        raise RuntimeConfigError("execution requires --yes after separate authorization; use --dry-run for an inert preview")


def validate_github_target(target: str) -> None:
    target = target.strip().strip("/")
    if target.startswith("https://"):
        parsed = urlsplit(target)
        if parsed.netloc.lower() != "github.com" or parsed.query or parsed.fragment:
            raise RuntimeConfigError("GitHub commands require a GitHub repository target")
        target = parsed.path.strip("/")
    if target.lower().endswith(".git"):
        target = target[:-4]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", target):
        raise RuntimeConfigError("GitHub commands cannot consume Azure IDs or repository targets")
    if target.lower() == "instablinds/website":
        raise RuntimeConfigError("Instablinds/Website is an Azure repository; its GitHub archive cannot be an active runtime target")


def validate_github_inputs(args: argparse.Namespace) -> None:
    if getattr(args, "repo", None):
        validate_github_target(args.repo)
    if args.runtime_config:
        url = args.runtime_config.repository.get("url")
        if url:
            validate_github_target(url)
    if args.command in {"status", "repos", "projects", "models", "sync", "plan-preview", "queue"}:
        return
    inventory = runtime_dir(args) / "repos.txt"
    if inventory.exists():
        target = inventory.resolve(strict=True)
        if inventory.parent not in target.parents or target.stat().st_uid != os.getuid():
            raise RuntimeConfigError("GitHub inventory must stay inside the explicit runtime")
        for line in target.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                validate_github_target(line)


def print_file(path: Path) -> None:
    if not path.exists():
        print(f"{path.name}: MISSING")
        return
    resolved = path.resolve(strict=True)
    if path.parent.resolve() not in resolved.parents or resolved.stat().st_uid != os.getuid():
        raise RuntimeConfigError("runtime inventory must be an owned file inside the explicit runtime directory")
    text = path.read_text(encoding="utf-8")
    print(text, end="" if text.endswith("\n") else "\n")


def cmd_status(args: argparse.Namespace) -> int:
    root = runtime_dir(args)
    config = getattr(args, "runtime_config", None)
    if config is not None:
        print(json.dumps(config.report(), indent=2))
        if args.check:
            print("Status never executes readiness checks. Use the explicit provider inspector.")
        return 0
    print(f"Runtime dir: {root}")
    print(f"Provider: {args.provider}")
    print()
    print("repos.txt:")
    print_file(root / "repos.txt")
    print()
    print("projects.txt:")
    print_file(root / "projects.txt")
    if args.check:
        print()
        return run_runtime(root, [runtime_script(root, "check_runtime.sh")], preview=True)
    return 0


def cmd_repos(args: argparse.Namespace) -> int:
    if args.provider == "azure-devops":
        print(json.dumps(args.runtime_config.repository, indent=2))
        return 0
    print_file(runtime_dir(args) / "repos.txt")
    return 0


def cmd_projects(args: argparse.Namespace) -> int:
    if args.provider == "azure-devops":
        print(args.runtime_config.repository["project"])
        return 0
    print_file(runtime_dir(args) / "projects.txt")
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    root = runtime_dir(args)
    command = [
        sys.executable,
        str(TOOLS_ROOT / "scripts" / "sync_runtime_template.py"),
        "--runtime-dir",
        str(root),
    ]
    if args.apply and not args.dry_run:
        require_execution_yes(args)
    if args.migrate_config and not args.apply:
        raise RuntimeConfigError("configuration migration requires explicitly authorized --apply")
    if args.apply:
        command.append("--apply")
    if args.migrate_config:
        command.append("--migrate-config")
    if args.readonly:
        command.append("--readonly")
    if not args.apply or args.dry_run:
        print(json.dumps({"mode": "preview", "dispatched": False, "argv": command}, indent=2))
        return 0
    print("+ " + shlex.join(command), flush=True)
    return subprocess.run(command, cwd=TOOLS_ROOT).returncode


def add_plan_args(command: list[str], args: argparse.Namespace) -> None:
    command.extend(["--plan", args.plan, "--repo", args.repo])
    if getattr(args, "strategy", None):
        command.extend(["--strategy", args.strategy])
    if getattr(args, "project_owner", None):
        command.extend(["--project-owner", args.project_owner])
    if getattr(args, "project_number", None) is not None:
        command.extend(["--project-number", str(args.project_number)])


def cmd_plan_preview(args: argparse.Namespace) -> int:
    root = runtime_dir(args)
    command = [runtime_script(root, "atlas-agent-plan-queue")]
    add_plan_args(command, args)
    command.append("--dry-run")
    return run_runtime(root, command, preview=True)


def cmd_queue(args: argparse.Namespace) -> int:
    root = runtime_dir(args)
    command = [runtime_script(root, "atlas-agent-plan-queue")]
    add_plan_args(command, args)
    command.extend(["--apply", "--queue", "--max-queue", str(args.max_queue)])
    if args.publish:
        command.append("--publish")
    if not args.dry_run:
        require_yes("queue", command, args.yes)
    return run_runtime(root, command, preview=args.dry_run)


def cmd_dry_cycle(args: argparse.Namespace) -> int:
    root = runtime_dir(args)
    command = [
        runtime_script(root, "atlas-agent-unattended"),
        "--cycles",
        str(args.cycles),
        "--max-per-repo",
        str(args.max_per_repo),
        "--repair-dry-run",
    ]
    if args.review_apply:
        command.append("--review-apply")
    return run_runtime(root, command, preview=True)


def cmd_run_once(args: argparse.Namespace) -> int:
    root = runtime_dir(args)
    command = [
        runtime_script(root, "atlas-agent-unattended"),
        "--cycles",
        str(args.cycles),
        "--max-per-repo",
        str(args.max_per_repo),
    ]
    for enabled, flag in (
        (args.publish, "--publish"),
        (args.apply, "--apply"),
        (args.merge, "--merge"),
        (args.close_issues, "--close-issues"),
        (args.review_apply, "--review-apply"),
        (args.post_cycle_summary, "--post-cycle-summary"),
    ):
        if enabled:
            command.append(flag)
    require_execution_yes(args)
    return run_runtime(root, command, preview=args.dry_run)


def cmd_shift(args: argparse.Namespace) -> int:
    root = runtime_dir(args)
    command = [
        runtime_script(root, "atlas-agent-shift"),
        "--cycles",
        str(args.cycles),
        "--sleep-seconds",
        str(args.sleep_seconds),
        "--dispatch-max-per-repo",
        str(args.dispatch_max_per_repo),
        "--repair-max",
        str(args.repair_max),
    ]
    if args.max_minutes is not None:
        command.extend(["--max-minutes", str(args.max_minutes)])
    if args.deadline:
        command.extend(["--deadline", args.deadline])
    for enabled, flag in (
        (args.publish, "--publish"),
        (args.apply, "--apply"),
        (args.merge, "--merge"),
        (args.close_issues, "--close-issues"),
        (args.review_apply, "--review-apply"),
        (args.post_cycle_summary, "--post-cycle-summary"),
    ):
        if enabled:
            command.append(flag)
    require_execution_yes(args)
    return run_runtime(root, command, preview=args.dry_run)


def cmd_review(args: argparse.Namespace) -> int:
    root = runtime_dir(args)
    command = [runtime_script(root, "atlas-agent-review")]
    if args.apply:
        command.append("--apply")
    if args.summary:
        command.extend(["--summary", args.summary])
    if args.required_checks_file:
        command.extend(["--required-checks-file", args.required_checks_file])
    if args.allow_no_checks:
        command.append("--allow-no-checks")
    if args.apply and not args.dry_run:
        require_yes("review", command, args.yes)
    return run_runtime(root, command, preview=args.dry_run or not args.apply)


def cmd_finalize(args: argparse.Namespace) -> int:
    root = runtime_dir(args)
    command = [runtime_script(root, "atlas-agent-finalize")]
    if args.required_checks_file:
        command.extend(["--required-checks-file", args.required_checks_file])
    else:
        command.extend(["--required-checks-file", str(root / "required-checks.json")])
    for enabled, flag in (
        (args.apply, "--apply"),
        (args.merge, "--merge"),
        (args.close_issues, "--close-issues"),
        (args.allow_no_checks, "--allow-no-checks"),
    ):
        if enabled:
            command.append(flag)
    mutation = args.apply or args.merge or args.close_issues
    if mutation and not args.dry_run:
        require_yes("finalize", command, args.yes)
    return run_runtime(root, command, preview=args.dry_run or not mutation)


def cmd_models(args: argparse.Namespace) -> int:
    if args.runtime_config is None:
        raise RuntimeConfigError("effective model reporting requires an explicit non-secret --config")
    print(json.dumps(args.runtime_config.report(), indent=2))
    return 0


def azure_command(args: argparse.Namespace, name: str) -> tuple[Path, list[str]]:
    if args.provider != "azure-devops" or args.runtime_config is None:
        raise RuntimeConfigError("Azure commands require an explicit Azure --config")
    root = runtime_dir(args)
    command = [runtime_script(root, name), "--config", str(Path(args.config).resolve()), "--runtime-dir", str(root)]
    return root, command


def cmd_azure_inspect(args: argparse.Namespace) -> int:
    root, command = azure_command(args, "atlas-agent-azure-inspect")
    command.extend(["--ids", args.ids])
    for name in ("snapshot", "expected_manifest", "supplement", "authority"):
        value = getattr(args, name)
        if value:
            command.extend(["--" + name.replace("_", "-"), str(Path(value).resolve())])
    if args.live_read:
        command.append("--live-read")
    if args.build_ids:
        command.extend(["--build-ids", args.build_ids])
    if args.json:
        command.append("--json")
    return run_runtime(root, command, preview=args.dry_run)


def cmd_azure_reconcile(args: argparse.Namespace) -> int:
    root, command = azure_command(args, "atlas-agent-azure-reconcile")
    command.extend(["--packet", str(Path(args.packet).resolve())])
    if args.authorization:
        command.extend(["--authorization", str(Path(args.authorization).resolve())])
    if args.apply:
        command.append("--apply")
        if not args.authorize_packet_sha256 or not re.fullmatch(r"[a-f0-9]{64}", args.authorize_packet_sha256):
            raise RuntimeConfigError("Board apply requires the separately approved --authorize-packet-sha256")
        command.extend(["--authorize-packet-sha256", args.authorize_packet_sha256])
        if not args.authorization and not args.dry_run:
            raise RuntimeConfigError("Board apply also requires a separately signed --authorization envelope")
    return run_runtime(root, command, preview=args.dry_run or not args.apply)


def cmd_azure_dispatch(args: argparse.Namespace) -> int:
    root, command = azure_command(args, "atlas-agent-azure-dispatch")
    for name in ("policy", "intake", "snapshot", "context_root", "assessment", "challenge", "human_receipts", "authorization"):
        value = getattr(args, name)
        if value:
            command.extend(["--" + name.replace("_", "-"), str(Path(value).resolve())])
    action = "--assess" if args.assess else "--execute" if args.execute else "--check-handoff" if args.check_handoff else "--dry-run"
    command.append(action)
    if args.check_handoff:
        command.extend(["--handoff-stage", args.handoff_stage])
        if args.handoff_action:
            command.extend(["--handoff-action", args.handoff_action])
    if action != "--dry-run" and not args.dry_run:
        if action != "--check-handoff" and not args.authorization:
            raise RuntimeConfigError("model assessment and worker execution each require their own signed --authorization")
        if args.assessment or args.challenge:
            raise RuntimeConfigError("caller-supplied model assessments are preview-only")
    return run_runtime(root, command, preview=args.dry_run or action == "--dry-run")


def cmd_azure_worker(args: argparse.Namespace) -> int:
    root, command = azure_command(args, "atlas-agent-azure-worker")
    command.extend(["--packet", str(Path(args.packet).resolve())])
    action = "--execute" if args.execute else "--publish" if args.publish else "--dry-run"
    command.append(action)
    if args.authorization:
        command.extend(["--authorization", str(Path(args.authorization).resolve())])
    for name in ("routing", "human_receipts"):
        value = getattr(args, name)
        if value:
            command.extend(["--" + name.replace("_", "-"), str(Path(value).resolve())])
    if action != "--dry-run" and not args.authorization:
        raise RuntimeConfigError("worker execution and draft publication require separate exact --authorization packets")
    return run_runtime(root, command, preview=args.dry_run or action == "--dry-run")


def cmd_azure_supervise(args: argparse.Namespace) -> int:
    root, command = azure_command(args, "atlas-agent-azure-supervise")
    for name in ("queue", "policy"):
        command.extend(["--" + name, str(Path(getattr(args, name)).resolve())])
    for name in ("max_cycles", "max_items", "max_seconds"):
        command.extend(["--" + name.replace("_", "-"), str(getattr(args, name))])
    action = "--observe" if args.observe else "--run" if args.run else "--dry-run"
    command.append(action)
    # --run expresses intent only. The supervisor must obtain each exact grant
    # through its verified inbox and repeat the existing child authority checks.
    return run_runtime(root, command, preview=args.dry_run or action == "--dry-run")


def cmd_azure_intake(args: argparse.Namespace) -> int:
    root, command = azure_command(args, "atlas-agent-azure-intake")
    for name in ("policy", "definition", "context_root", "snapshot", "previous"):
        value = getattr(args, name)
        if value:
            command.extend(["--" + name.replace("_", "-"), str(Path(value).resolve())])
    command.append("--live-read" if args.live_read else "--dry-run")
    return run_runtime(root, command, preview=args.dry_run or not args.live_read)


def cmd_azure_approval(args: argparse.Namespace) -> int:
    root, command = azure_command(args, "atlas-agent-azure-approval")
    for name in ("request", "import_response", "response_file"):
        value = getattr(args, name)
        if value:
            command.extend(["--" + name.replace("_", "-"), str(Path(value).resolve())])
    for name in ("request_id", "decision", "response_text"):
        value = getattr(args, name)
        if value is not None:
            command.extend(["--" + name.replace("_", "-"), value])
    action = ("--prepare" if args.prepare else "--export" if args.export else "--reopen" if args.reopen
              else "--operator-issue" if args.operator_issue else None)
    if action:
        command.append(action)
    if action is None and not args.import_response:
        command.append("--dry-run")
    # Export is unsigned; issuer invocation is intent, never authentication.
    # The child validates imported responses against the fixed trust registry.
    return run_runtime(root, command, preview=args.dry_run or (action is None and not args.import_response))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-dir", help="Explicit existing runtime inside the current passwd home; alternatively set ATLAS_RUNTIME_DIR or runtime_dir in --config.")
    parser.add_argument("--provider", choices=("azure-devops", "azure_devops", "github"), help="Explicit provider; must match --config when both are supplied.")
    parser.add_argument("--config", help="Non-secret JSON provider/capability/model configuration; config.env is never loaded by this wrapper.")
    parser.add_argument("--dry-run", action="store_true", help="Print an inert preview without invoking a runtime command.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="Show runtime path and target files.")
    status.add_argument("--check", action="store_true", help="Preview the provider readiness check; status never executes checks.")
    status.set_defaults(func=cmd_status)

    repos = subparsers.add_parser("repos", help="Print repos.txt.")
    repos.set_defaults(func=cmd_repos)

    projects = subparsers.add_parser("projects", help="Print projects.txt.")
    projects.set_defaults(func=cmd_projects)

    models = subparsers.add_parser("models", help="Report the effective model, reasoning, source and argv for each role.")
    models.set_defaults(func=cmd_models)

    sync = subparsers.add_parser("sync", help="Check or apply managed runtime files from the source template.")
    sync.add_argument("--apply", action="store_true", help="Overwrite managed runtime files from the template.")
    sync.add_argument("--migrate-config", action="store_true", help="Append missing config.env keys from the template example.")
    sync.add_argument("--readonly", action="store_true", help="Make managed copied files read-only after sync.")
    sync.add_argument("--yes", action="store_true", help="Confirm this separately authorized explicit runtime update.")
    sync.set_defaults(func=cmd_sync)

    plan_preview = subparsers.add_parser("plan-preview", help="Preview plan projection and queue eligibility.")
    plan_preview.add_argument("--plan", required=True)
    plan_preview.add_argument("--repo", required=True)
    plan_preview.add_argument("--strategy", choices=("leaf-issues", "workstreams", "phases"))
    plan_preview.add_argument("--project-owner")
    plan_preview.add_argument("--project-number", type=positive_int)
    plan_preview.set_defaults(func=cmd_plan_preview)

    queue = subparsers.add_parser("queue", help="Apply a plan and queue eligible work.")
    queue.add_argument("--plan", required=True)
    queue.add_argument("--repo", required=True)
    queue.add_argument("--strategy", choices=("leaf-issues", "workstreams", "phases"))
    queue.add_argument("--max-queue", type=positive_int, default=1)
    queue.add_argument("--publish", action="store_true")
    queue.add_argument("--yes", action="store_true", help="Confirm mutating runtime actions.")
    queue.set_defaults(func=cmd_queue)

    dry_cycle = subparsers.add_parser("dry-cycle", help="Print a bounded cycle preview without dispatching a child process.")
    dry_cycle.add_argument("--cycles", type=positive_int, default=1)
    dry_cycle.add_argument("--max-per-repo", type=positive_int, default=1)
    dry_cycle.add_argument("--review-apply", action="store_true")
    dry_cycle.add_argument("--yes", action="store_true", help="Confirm mutating runtime actions.")
    dry_cycle.set_defaults(func=cmd_dry_cycle)

    run_once = subparsers.add_parser("run-once", help="Run the unattended loop with bounded defaults.")
    run_once.add_argument("--publish", action="store_true")
    run_once.add_argument("--apply", action="store_true")
    run_once.add_argument("--merge", action="store_true")
    run_once.add_argument("--close-issues", action="store_true")
    run_once.add_argument("--cycles", type=positive_int, default=1)
    run_once.add_argument("--max-per-repo", type=positive_int, default=1)
    run_once.add_argument("--review-apply", action=argparse.BooleanOptionalAction, default=True)
    run_once.add_argument("--post-cycle-summary", action=argparse.BooleanOptionalAction, default=True)
    run_once.add_argument("--yes", action="store_true", help="Confirm mutating runtime actions.")
    run_once.set_defaults(func=cmd_run_once)

    shift = subparsers.add_parser("shift", help="Run a bounded long shift with heartbeat/status/handoff files.")
    shift.add_argument("--publish", action="store_true")
    shift.add_argument("--apply", action="store_true")
    shift.add_argument("--merge", action="store_true")
    shift.add_argument("--close-issues", action="store_true")
    shift.add_argument("--cycles", type=positive_int, default=3)
    shift.add_argument("--max-minutes", type=float)
    shift.add_argument("--deadline")
    shift.add_argument("--sleep-seconds", type=float, default=300.0)
    shift.add_argument("--dispatch-max-per-repo", type=positive_int, default=1)
    shift.add_argument("--repair-max", type=positive_int, default=2)
    shift.add_argument("--review-apply", action=argparse.BooleanOptionalAction, default=True)
    shift.add_argument("--post-cycle-summary", action=argparse.BooleanOptionalAction, default=True)
    shift.add_argument("--yes", action="store_true", help="Confirm mutating runtime actions.")
    shift.set_defaults(func=cmd_shift)

    review = subparsers.add_parser("review", help="Run atlas-agent-review.")
    review.add_argument("--apply", action="store_true")
    review.add_argument("--summary")
    review.add_argument("--required-checks-file")
    review.add_argument("--allow-no-checks", action="store_true")
    review.add_argument("--yes", action="store_true", help="Confirm mutating runtime actions.")
    review.set_defaults(func=cmd_review)

    finalize = subparsers.add_parser("finalize", help="Run atlas-agent-finalize.")
    finalize.add_argument("--apply", action="store_true")
    finalize.add_argument("--merge", action="store_true")
    finalize.add_argument("--close-issues", action="store_true")
    finalize.add_argument("--required-checks-file")
    finalize.add_argument("--allow-no-checks", action="store_true")
    finalize.add_argument("--yes", action="store_true", help="Confirm mutating runtime actions.")
    finalize.set_defaults(func=cmd_finalize)

    inspect = subparsers.add_parser("azure-inspect", help="Read Azure evidence or an offline snapshot with the Azure-only inspector.")
    inspect.add_argument("--ids", required=True)
    inspect.add_argument("--snapshot")
    inspect.add_argument("--expected-manifest")
    inspect.add_argument("--supplement")
    inspect.add_argument("--authority")
    inspect.add_argument("--build-ids", help="Optional comma-separated build IDs for timeline evidence.")
    inspect.add_argument("--live-read", action="store_true")
    inspect.add_argument("--json", action="store_true")
    inspect.set_defaults(func=cmd_azure_inspect)

    worker = subparsers.add_parser("azure-worker", help="Preview one bounded Azure task; execution and draft publication are separately authorized actions.")
    worker.add_argument("--packet", required=True)
    worker_mode = worker.add_mutually_exclusive_group()
    worker_mode.add_argument("--execute", action="store_true")
    worker_mode.add_argument("--publish", action="store_true")
    worker.add_argument("--authorization")
    worker.add_argument("--routing")
    worker.add_argument("--human-receipts")
    worker.set_defaults(func=cmd_azure_worker)

    reconcile = subparsers.add_parser("azure-reconcile", help="Preview exact Board patches; apply requires a separately authorized packet hash.")
    reconcile.add_argument("--packet", required=True)
    reconcile.add_argument("--apply", action="store_true")
    reconcile.add_argument("--authorize-packet-sha256")
    reconcile.add_argument("--authorization", help="Separately signed Board-write envelope.")
    reconcile.set_defaults(func=cmd_azure_reconcile)

    dispatch = subparsers.add_parser("azure-dispatch", help="Inert routing preview, separately signed assessment, or bounded local execution.")
    for name in ("policy", "intake", "snapshot"):
        dispatch.add_argument("--" + name, required=True)
    for name in ("context-root", "assessment", "challenge", "human-receipts", "authorization"):
        dispatch.add_argument("--" + name)
    dispatch_mode = dispatch.add_mutually_exclusive_group()
    dispatch_mode.add_argument("--assess", action="store_true")
    dispatch_mode.add_argument("--execute", action="store_true")
    dispatch_mode.add_argument("--check-handoff", action="store_true")
    dispatch.add_argument("--handoff-stage", choices=("before", "after"), default="before")
    dispatch.add_argument("--handoff-action")
    dispatch.set_defaults(func=cmd_azure_dispatch)

    supervise = subparsers.add_parser("azure-supervise", help="Preview a bounded Azure queue; observe explicitly or consume separately signed child grants.")
    supervise.add_argument("--queue", required=True)
    supervise.add_argument("--policy", required=True)
    supervise_mode = supervise.add_mutually_exclusive_group()
    supervise_mode.add_argument("--observe", action="store_true", help="Refresh read-only Azure evidence and local decision requests.")
    supervise_mode.add_argument("--run", action="store_true", help="Run bounded cycles; every child still needs its exact signed authority.")
    supervise.add_argument("--max-cycles", type=positive_int, default=1)
    supervise.add_argument("--max-items", type=positive_int, default=1)
    supervise.add_argument("--max-seconds", type=positive_int, default=60)
    supervise.set_defaults(func=cmd_azure_supervise)

    intake = subparsers.add_parser("azure-intake", help="Preview explicit task inputs or read fresh Azure evidence to assemble a truthful intake.")
    for name in ("policy", "definition", "context-root"):
        intake.add_argument("--" + name, required=True)
    intake.add_argument("--snapshot")
    intake.add_argument("--previous")
    intake.add_argument("--live-read", action="store_true")
    intake.set_defaults(func=cmd_azure_intake)

    approval = subparsers.add_parser("azure-approval", help="Preview a human decision, prepare/export an unsigned request, or explicitly verify a response.")
    approval_source = approval.add_mutually_exclusive_group(required=True)
    approval_source.add_argument("--request")
    approval_source.add_argument("--request-id")
    approval_mode = approval.add_mutually_exclusive_group()
    approval_mode.add_argument("--prepare", action="store_true")
    approval_mode.add_argument("--export", action="store_true")
    approval_mode.add_argument("--reopen", action="store_true", help="Explicitly request another review revision after a verified prior response; never renews approval automatically.")
    approval_mode.add_argument("--import-response")
    approval_mode.add_argument("--operator-issue", action="store_true", help="Ask an existing protected issuer adapter; local intent supplies no authenticated approval.")
    approval.add_argument("--decision", choices=("accepted", "rejected", "feedback"))
    approval_response = approval.add_mutually_exclusive_group()
    approval_response.add_argument("--response-text")
    approval_response.add_argument("--response-file")
    approval.set_defaults(func=cmd_azure_approval)

    for subparser in subparsers.choices.values():
        subparser.add_argument("--dry-run", action="store_true", default=argparse.SUPPRESS,
                               help="Print an inert preview without invoking a runtime command.")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.runtime_config = None
        if args.config:
            args.runtime_config = load_runtime_config(
                args.config, runtime_dir=args.runtime_dir or os.environ.get("ATLAS_RUNTIME_DIR")
            )
        selected = args.provider or (args.runtime_config.provider if args.runtime_config else None)
        args.provider = normalize_provider(selected)
        if args.runtime_config and args.provider != args.runtime_config.provider:
            raise RuntimeConfigError("--provider does not match the explicit configuration")
        if args.provider == "azure-devops":
            if args.runtime_config is None:
                raise RuntimeConfigError("Azure commands require the explicit non-secret --config")
            if args.command not in AZURE_COMMANDS:
                raise RuntimeConfigError("Azure provider supports only explicit Azure inspection, intake, approval, supervision and bounded operations; no GitHub fallback or merge/deploy/cleanup workflow")
        elif args.command.startswith("azure-"):
            raise RuntimeConfigError("Azure commands cannot run with provider github")
        else:
            validate_github_inputs(args)
        runtime_dir(args)
        return args.func(args)
    except (RuntimeConfigError, OSError, ValueError) as exc:
        print(f"runtime configuration blocked: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
