#!/usr/bin/env python3
"""Small local control wrapper for an installed automation runtime."""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path


TOOLS_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME_DIR = Path("/home/mat/distrobox-homes/atlas-agent/agent-runtime")
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
    raw = args.runtime_dir or os.environ.get("ATLAS_RUNTIME_DIR") or str(DEFAULT_RUNTIME_DIR)
    return Path(raw).expanduser().resolve()


def runtime_script(root: Path, name: str) -> str:
    return str(root / name)


def run_runtime(root: Path, command: list[str]) -> int:
    if not root.is_dir():
        raise SystemExit(f"runtime dir does not exist: {root}")
    if not Path(command[0]).exists():
        raise SystemExit(f"missing runtime script: {command[0]}")
    if os.environ.get("ATLAS_RUNTIME_SKIP_SYNC", "").lower() not in {"1", "true", "yes"}:
        sync_cmd = [
            sys.executable,
            str(TOOLS_ROOT / "scripts" / "sync_runtime_template.py"),
            "--runtime-dir",
            str(root),
            "--apply",
            "--migrate-config",
            "--readonly",
        ]
        print("+ " + shlex.join(sync_cmd), flush=True)
        subprocess.run(sync_cmd, cwd=TOOLS_ROOT, check=True)
    print("+ " + shlex.join(command), flush=True)
    env = os.environ.copy()
    env["PWD"] = str(root)
    return subprocess.run(command, cwd=root, env=env).returncode


def require_yes(name: str, command: list[str], yes: bool) -> None:
    flags = sorted(flag for flag in MUTATING_FLAGS if flag in command)
    if flags and not yes:
        raise SystemExit(f"{name} would pass mutating flag(s) {', '.join(flags)}; rerun with --yes.")


def print_file(path: Path) -> None:
    if not path.exists():
        print(f"{path.name}: MISSING")
        return
    text = path.read_text(encoding="utf-8")
    print(text, end="" if text.endswith("\n") else "\n")


def cmd_status(args: argparse.Namespace) -> int:
    root = runtime_dir(args)
    print(f"Runtime dir: {root}")
    print()
    print("repos.txt:")
    print_file(root / "repos.txt")
    print()
    print("projects.txt:")
    print_file(root / "projects.txt")
    if args.check:
        print()
        return run_runtime(root, [runtime_script(root, "check_runtime.sh")])
    return 0


def cmd_repos(args: argparse.Namespace) -> int:
    print_file(runtime_dir(args) / "repos.txt")
    return 0


def cmd_projects(args: argparse.Namespace) -> int:
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
    if args.apply:
        command.append("--apply")
    if args.migrate_config:
        command.append("--migrate-config")
    if args.readonly:
        command.append("--readonly")
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
    return run_runtime(root, command)


def cmd_queue(args: argparse.Namespace) -> int:
    root = runtime_dir(args)
    command = [runtime_script(root, "atlas-agent-plan-queue")]
    add_plan_args(command, args)
    command.extend(["--apply", "--queue", "--max-queue", str(args.max_queue)])
    if args.publish:
        command.append("--publish")
    require_yes("queue", command, args.yes)
    return run_runtime(root, command)


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
    require_yes("dry-cycle", command, args.yes)
    return run_runtime(root, command)


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
    require_yes("run-once", command, args.yes)
    return run_runtime(root, command)


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
    require_yes("shift", command, args.yes)
    return run_runtime(root, command)


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
    require_yes("review", command, args.yes)
    return run_runtime(root, command)


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
    require_yes("finalize", command, args.yes)
    return run_runtime(root, command)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-dir", help="Runtime directory. Defaults to ATLAS_RUNTIME_DIR or the local Atlas runtime.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="Show runtime path and target files.")
    status.add_argument("--check", action="store_true", help="Run check_runtime.sh after printing target files.")
    status.set_defaults(func=cmd_status)

    repos = subparsers.add_parser("repos", help="Print repos.txt.")
    repos.set_defaults(func=cmd_repos)

    projects = subparsers.add_parser("projects", help="Print projects.txt.")
    projects.set_defaults(func=cmd_projects)

    sync = subparsers.add_parser("sync", help="Check or apply managed runtime files from the source template.")
    sync.add_argument("--apply", action="store_true", help="Overwrite managed runtime files from the template.")
    sync.add_argument("--migrate-config", action="store_true", help="Append missing config.env keys from the template example.")
    sync.add_argument("--readonly", action="store_true", help="Make managed copied files read-only after sync.")
    sync.set_defaults(func=cmd_sync)

    plan_preview = subparsers.add_parser("plan-preview", help="Preview plan projection and queue eligibility.")
    plan_preview.add_argument("--plan", required=True)
    plan_preview.add_argument("--repo", required=True)
    plan_preview.add_argument("--strategy", choices=("workstreams", "phases"))
    plan_preview.add_argument("--project-owner")
    plan_preview.add_argument("--project-number", type=positive_int)
    plan_preview.set_defaults(func=cmd_plan_preview)

    queue = subparsers.add_parser("queue", help="Apply a plan and queue eligible work.")
    queue.add_argument("--plan", required=True)
    queue.add_argument("--repo", required=True)
    queue.add_argument("--strategy", choices=("workstreams", "phases"))
    queue.add_argument("--max-queue", type=positive_int, default=1)
    queue.add_argument("--publish", action="store_true")
    queue.add_argument("--yes", action="store_true", help="Confirm mutating runtime actions.")
    queue.set_defaults(func=cmd_queue)

    dry_cycle = subparsers.add_parser("dry-cycle", help="Run a bounded non-publish unattended cycle.")
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

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
