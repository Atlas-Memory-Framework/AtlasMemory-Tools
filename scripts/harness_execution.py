#!/usr/bin/env python3
"""Prepare inert, bounded runtime proposals; this module never starts a process."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import stat
import sys
from typing import Any

sys.dont_write_bytecode = True

from harness_service import (  # noqa: E402
    HarnessService,
    HarnessServiceError,
    MAX_CODE_BYTES,
    _blocker,
    _owned_path,
    _read_bytes,
    _read_json,
)


OPERATION = "github-cycle"
DEFAULT_OPTIONS = {
    "max_minutes": 10,
    "cycles": 1,
    "max_per_repo": 1,
    "publish": False,
    "apply": False,
    "review_apply": False,
}
REPO_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z")
READ_SCRIPTS = (
    "atlas-agent-shift",
    "atlas-agent-unattended",
    "atlas_agent_common.py",
    "atlas-agent-reconcile",
    "atlas-agent-orchestrator",
    "atlas-agent-triage",
    "atlas-agent-review",
    "atlas-agent-cycle-summary",
)
WRITE_SCRIPTS = (
    "atlas-agent-worker",
    "atlas-agent-project-sync",
    "atlas-agent-semantic-review",
    "atlas-agent-local-validate",
    "atlas-agent-pr-repair",
)
MAX_CODE_FILES = 128


def canonical_code_files(tools_root: Path) -> list[str]:
    """Finite source inventory, never a scan of mutable installed state.

    Runtime imports and entrypoints currently live at the template root. Tests,
    examples, configuration, job trees and caches are deliberately excluded.
    """
    root = tools_root / "templates" / "local-automation-runtime"
    names = []
    for index, path in enumerate(root.iterdir()):
        if index >= 512:
            raise HarnessServiceError("runtime_source_inventory", "Canonical runtime source inventory exceeds its bounded limit.")
        if path.is_file() and (path.suffix in {".py", ".sh"} or path.name.startswith("atlas-agent-")):
            names.append(path.name)
    if not names or len(names) > MAX_CODE_FILES:
        raise HarnessServiceError("runtime_source_inventory", "Canonical runtime code inventory is missing or exceeds its bounded limit.")
    return sorted(names)


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def proposal_digest(proposal: dict[str, Any]) -> str:
    """Stable identity of the material proposal, excluding no effect fields."""
    return _digest(json.dumps(proposal, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8"))


def validated_options(options: dict[str, Any] | None) -> dict[str, Any]:
    if options is None:
        return dict(DEFAULT_OPTIONS)
    if not isinstance(options, dict) or set(options) - set(DEFAULT_OPTIONS):
        raise HarnessServiceError("invalid_options", "Use only the documented bounded cycle options; arbitrary commands and arguments are forbidden.")
    values = {**DEFAULT_OPTIONS, **options}
    for key, maximum in (("max_minutes", 30), ("cycles", 3), ("max_per_repo", 2)):
        if type(values[key]) is not int or not 1 <= values[key] <= maximum:
            raise HarnessServiceError("invalid_options", "Cycle budget options require integers inside the documented bounds.")
    for key in ("publish", "apply", "review_apply"):
        if type(values[key]) is not bool:
            raise HarnessServiceError("invalid_options", "Effect options require explicit booleans.")
    return values


def _metadata(path: Path, root: Path) -> dict[str, int | bool]:
    """Bind secret-bearing runtime config by metadata without reading its bytes."""
    if not path.exists() and not path.is_symlink():
        return {"exists": False}
    resolved = _owned_path(path, boundary=root)
    info = resolved.stat()
    return {
        "exists": True,
        "device": info.st_dev,
        "inode": info.st_ino,
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
        "ctime_ns": info.st_ctime_ns,
        "mode": stat.S_IMODE(info.st_mode),
    }


class HarnessExecution:
    def __init__(self, service: HarnessService):
        self.service = service

    def _inventory(self, root: Path) -> tuple[list[str], str]:
        try:
            content = _read_bytes(root / "repos.txt", boundary=root)
            info = (root / "repos.txt").stat()
            if info.st_nlink != 1 or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                raise HarnessServiceError("unsafe_inventory", "Runtime inventory must not be hard-linked or writable by another identity.")
            text = content.decode("utf-8")
        except UnicodeError as exc:
            raise HarnessServiceError("invalid_inventory", "Runtime repos.txt must be UTF-8 GitHub owner/repository lines.") from exc
        targets = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Inline comments and URLs are deliberately not accepted. The same
            # exact inventory is later consumed by the known runtime entrypoint.
            if not REPO_PATTERN.fullmatch(line) or line.lower() == "instablinds/website":
                raise HarnessServiceError("invalid_inventory", "Runtime inventory requires GitHub owner/repository lines without URLs, inline comments or provider aliases.")
            if line.casefold() in {target.casefold() for target in targets}:
                raise HarnessServiceError("invalid_inventory", "Runtime inventory contains duplicate GitHub targets.")
            targets.append(line)
            if len(targets) > 32:
                raise HarnessServiceError("inventory_too_large", "A bounded harness cycle supports at most 32 registered GitHub targets.")
        if not targets:
            raise HarnessServiceError("empty_inventory", "Add an explicit GitHub target to runtime repos.txt before preparing a cycle.")
        return targets, _digest(content)

    def _scripts(self, root: Path, options: dict[str, Any], blockers: list[dict[str, str]]) -> dict[str, str]:
        names = canonical_code_files(self.service.tools_root)
        bindings = {}
        canonical = self.service.tools_root / "templates" / "local-automation-runtime"
        for name in names:
            path = root / name
            try:
                content = _read_bytes(path, boundary=root, max_bytes=MAX_CODE_BYTES)
                expected = _read_bytes(canonical / name, boundary=canonical, max_bytes=MAX_CODE_BYTES)
                bindings[name] = _digest(content)
                info = path.stat()
                if info.st_nlink != 1 or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                    blockers.append(_blocker("unsafe_runtime_code_mode", "Installed runtime code must not be hard-linked or writable by another identity.", "Review runtime code ownership and mode before execution."))
                if content != expected:
                    blockers.append(_blocker("runtime_script_drift", "An installed runtime script differs from the reviewed canonical template.", "Review and explicitly sync managed runtime files before execution."))
                if name.startswith("atlas-agent-") and not info.st_mode & stat.S_IXUSR:
                    blockers.append(_blocker("runtime_script_not_executable", "A required installed runtime entrypoint is not executable.", "Repair the installed runtime entrypoint mode before execution."))
            except HarnessServiceError:
                blockers.append(_blocker("missing_runtime_script", "A required owned runtime script is missing, unsafe or exceeds the bounded read limit.", "Install or explicitly upgrade this runtime from the canonical template."))
        return bindings

    def prepare(self, runtime_id: str, operation: str = OPERATION, options: dict[str, Any] | None = None) -> dict[str, Any]:
        if operation != OPERATION:
            raise HarnessServiceError("unsupported_operation", "Only the named github-cycle operation is supported; arbitrary commands and shell arguments are forbidden.")
        values = validated_options(options)
        runtime = self.service.get_runtime(runtime_id)
        root = Path(runtime["runtime_dir"])
        blockers: list[dict[str, str]] = []
        if runtime["provider"] != "github":
            blockers.append(_blocker("unsupported_provider_operation", "The GitHub cycle cannot operate on an Azure runtime.", "Use the existing explicit Azure inspector, dispatcher and signed operation contracts."))
            return self.service._envelope(
                status="blocked", proposal=None, proposal_id=None, blockers=blockers,
                next_actions=[{"operation": "inspect", "runtime_id": runtime_id}],
            )

        configuration = runtime.get("configuration", {})
        capabilities = configuration.get("capabilities", [])
        if "local_execute" not in capabilities:
            blockers.append(_blocker("missing_execution_capability", "The registered non-secret configuration does not enable local_execute.", "Review and explicitly configure local_execute for this runtime; capability is not execution authorization."))
        if values["publish"] and "draft_pr" not in capabilities:
            blockers.append(_blocker("missing_publication_capability", "Draft publication is not enabled in the non-secret runtime configuration.", "Review and explicitly configure draft_pr before proposing publication."))

        registry_sha = _digest(_read_bytes(self.service.registry))
        config_sha = _digest(_read_bytes(Path(runtime["config"]))) if runtime.get("config") else None
        try:
            targets, inventory_sha = self._inventory(root)
        except HarnessServiceError as exc:
            targets, inventory_sha = [], None
            blockers.append(_blocker(exc.code, exc.message, "Repair the owned runtime inventory, then prepare again."))
        scripts = self._scripts(root, values, blockers)
        try:
            env_metadata = _metadata(root / "config.env", root)
            if not env_metadata.get("exists"):
                blockers.append(_blocker("missing_runtime_config", "The installed legacy runtime has no config.env file.", "Provision the existing runtime configuration explicitly before execution; preparation never installs it."))
        except HarnessServiceError:
            env_metadata = {"unsafe": True}
            blockers.append(_blocker("unsafe_runtime_config", "Runtime shell configuration is not an owned regular file inside the registered boundary.", "Review the runtime configuration path before execution."))

        policy_files = {}
        for name in ("required-checks.json", "local-validation.json" if values["apply"] else "required-checks.json"):
            if name in policy_files:
                continue
            path = root / name
            if path.exists() or path.is_symlink():
                try:
                    content = _read_bytes(path, boundary=root)
                    _read_json(path, boundary=root)
                    policy_files[name] = _digest(content)
                except HarnessServiceError:
                    blockers.append(_blocker("unsafe_runtime_policy", "A runtime policy file is not safely readable within the bounded limit.", "Review runtime policy files before execution."))
            else:
                policy_files[name] = None
                if name == "required-checks.json":
                    blockers.append(_blocker("missing_runtime_policy", "The installed runtime has no required-checks.json policy.", "Provision and review the runtime check policy before execution."))

        observation = self.service.inspect(runtime_id)
        inspection_blocked = False
        for item in observation.get("blockers", []):
            if item.get("code") != "no_runtime_evidence":
                blockers.append(item)
                inspection_blocked = True

        # Default mode omits validation, whose existing --apply flag controls
        # label writes rather than whether project shell commands execute.
        stages = "reconcile,dispatch,review,summary"
        if values["apply"]:
            stages = "reconcile,dispatch,review,semantic-review,review,local-validate,review,repair,review,summary"
        argv = [
            str(root / "atlas-agent-shift"),
            "--cycles", str(values["cycles"]),
            "--max-minutes", str(values["max_minutes"]),
            "--cycle-timeout-seconds", str(values["max_minutes"] * 60),
            "--sleep-seconds", "0",
            "--project-reconcile-every", "0",
            "--stop-before-deadline-seconds", "1",
            "--",
            "--project-reconcile-every", "0",
            "--repos-file", str(root / "repos.txt"),
            "--required-checks-file", str(root / "required-checks.json"),
            "--stages", stages,
            "--max-per-repo", str(values["max_per_repo"]),
            "--dispatch-max-per-repo", str(values["max_per_repo"]),
            "--repair-max", "1",
            "--repair-concurrency", "1",
            "--local-validate-max", "1",
            "--local-validate-concurrency", "1",
            "--semantic-review-max", "1",
            "--semantic-review-concurrency", "1",
            "--cleanup-mode", "off",
            "--no-worker-notifications",
            "--execution-targets-file", str(root / "repos.txt"),
            "--no-project-reconcile-apply",
            "--stop-on-error",
        ]
        # No-post-cycle-summary is not a valid flag: the runtime uses an
        # opt-in store_true flag, so absence is the explicit no-notification mode.
        if values["publish"]:
            argv.append("--publish")
        if values["apply"]:
            argv.extend(["--apply", "--local-validation-file", str(root / "local-validation.json")])
        if values["review_apply"]:
            argv.append("--review-apply")
        else:
            argv.extend(["--no-reconcile-apply", "--no-semantic-review-apply", "--no-local-validation-apply"])
        if not any(values[key] for key in ("publish", "apply", "review_apply")):
            argv.append("--dry-run")

        effects = {
            "provider_read": True,
            "local_runtime_artifacts": True,
            "worker_execution": values["publish"] or values["apply"],
            "draft_pr_publication": values["publish"],
            "existing_pr_branch_repair": values["apply"],
            "issue_labels_comments": values["review_apply"] or values["publish"] or values["apply"],
            "project_updates": values["publish"] or values["apply"],
            "dispatch_readiness_changes": values["publish"],
            "missing_base_branch_creation": values["publish"],
            "project_validation_commands": values["apply"],
            "merge": False,
            "close_issues": False,
            "deployed_validation_stage": False,
            "deployment_requested": False,
            "cleanup": False,
            "notifications": False,
        }
        proposal = {
            "runtime_id": runtime_id,
            "operation": OPERATION,
            "provider": "github",
            "runtime_dir": str(root),
            "options": values,
            "argv": argv,
            "cwd": str(root),
            "targets": targets,
            "effects": effects,
            "budgets": {
                "max_minutes": values["max_minutes"], "cycles": values["cycles"],
                "max_per_repo": values["max_per_repo"], "repair_max": 1,
                "cycle_timeout_seconds": values["max_minutes"] * 60,
            },
            "bindings": {
                "registry_sha256": registry_sha,
                "nonsecret_config_sha256": config_sha,
                "inventory_sha256": inventory_sha,
                "scripts": scripts,
                "runtime_policy_files": policy_files,
                "config_env_metadata": env_metadata,
            },
            "required_authorization": {
                "granted": False,
                "source": "host_tool_approval",
                "message": "Execution requires separate host authorization for this exact proposal and effects. A proposal digest, capability, authorization_ref or worker agreement grants no authority.",
            },
            "limitations": [
                "Preparation runs no child processes, provider queries or workload commands.",
                "Runtime config.env content and credentials were not read; its metadata is bound for change detection only.",
                "Non-secret JSON configuration gates wrapper capabilities; the legacy runtime still resolves effective worker settings from its own configuration and environment.",
                "Downstream issue instructions and project command semantics require their existing review and execution gates; this proposal does not certify them safe or complete.",
                "No merge, close, deployment, cleanup or notification operation is requested by this fixed stage selection.",
            ],
            "blockers": blockers,
        }
        digest = proposal_digest(proposal)
        next_actions = []
        if blockers:
            if inspection_blocked:
                next_actions.extend(observation.get("next_actions", []))
            next_actions.extend({"operation": "resolve_blocker", "runtime_id": runtime_id,
                                 "code": item.get("code"), "next_action": item.get("next_action")}
                                for item in blockers)
        else:
            next_actions.append({"operation": "authorize_start", "runtime_id": runtime_id, "proposal_id": digest})
        return self.service._envelope(
            status="blocked" if blockers else "prepared",
            proposal_id=digest,
            proposal=proposal,
            blockers=blockers,
            next_actions=next_actions,
            validation={"status": "unverified", "message": "Preparation establishes a bounded proposal only; it does not execute work or establish accepted task progress."},
        )
