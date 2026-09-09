"""Bounded Azure outer controller; observation is explicit, authority stays local.

Preview is pure. Observe may refresh native reads and local review evidence. Run
may consume existing, exact signed grants through the existing bounded children.
No issuer adapter, installation, service, merge or deployment is invoked here.
"""

from __future__ import annotations

import sys
sys.dont_write_bytecode = True

import argparse
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import pwd
import re
import stat
import time
from typing import Any
import uuid

from atlas_authority import canonical_digest, strict_json_loads
from atlas_runtime_config import RuntimeConfig, load_runtime_config, require_capability, validate_input_path, validate_runtime_path


class SupervisorError(RuntimeError):
    """A controller boundary or child result cannot be established."""


ACTIONS = frozenset({"assess", "local_execute", "draft_pr", "board_write"})
MAX_STATE_BYTES = 250_000
SOURCE_FILES = ("atlas_supervisor.py", "atlas_intake.py", "atlas_approval.py", "atlas_dispatch.py",
                "atlas_authority.py", "atlas_routing.py", "atlas_human_gates.py", "atlas_runtime_config.py",
                "atlas_azure_worker.py", "atlas_azure_reconcile.py", "atlas_azure_devops.py")


def _object(value: Any, required: set[str], label: str, optional: set[str] = frozenset()) -> dict:
    if type(value) is not dict or not required.issubset(value) or set(value) - required - optional:
        raise SupervisorError(label + " has missing or unsupported fields")
    return value


def _integer(value: Any, minimum: int, maximum: int, label: str) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise SupervisorError(f"{label} must be an integer from {minimum} through {maximum}")
    return value


def _text(value: Any, label: str, maximum: int = 4000) -> str:
    if type(value) is not str or not value.strip() or len(value) > maximum or "\x00" in value:
        raise SupervisorError(label + " requires bounded nonempty text")
    return value


def validate_queue(queue: Any, config: RuntimeConfig) -> dict:
    _object(queue, {"schema_version", "repository_url", "limits", "items"}, "supervisor queue")
    _integer(queue["schema_version"], 1, 1, "queue schema")
    if config.provider != "azure-devops" or queue["repository_url"] != config.repository["url"]:
        raise SupervisorError("supervisor queue requires the exact explicit Azure repository")
    limits = _object(queue["limits"], {"max_cycles", "max_items", "max_seconds"}, "queue limits")
    _integer(limits["max_cycles"], 1, 20, "max_cycles")
    _integer(limits["max_items"], 1, 100, "max_items")
    _integer(limits["max_seconds"], 1, 3600, "max_seconds")
    if type(queue["items"]) is not list or not 1 <= len(queue["items"]) <= 100:
        raise SupervisorError("queue requires one through 100 explicit items")
    prefix = f"azdo:{config.repository['organization']}:{config.repository['project']}:"
    identities = set()
    for item in queue["items"]:
        _object(item, {"id", "definition", "context_root", "actions"}, "queue item", {"proposal"})
        if type(item["id"]) is not str or not re.fullmatch(re.escape(prefix) + r"[1-9][0-9]*", item["id"]) or item["id"] in identities:
            raise SupervisorError("queue issue IDs must be distinct and preserve the exact Azure namespace")
        identities.add(item["id"])
        if type(item["definition"]) is not dict:
            raise SupervisorError("queue definition must be an explicit bounded draft")
        packet = item["definition"].get("worker_packet", {})
        if type(packet) is not dict or packet.get("id", item["id"]) != item["id"]:
            raise SupervisorError("queue and draft packet issue identity differ")
        _text(item["context_root"], "context_root", 1000)
        root = Path(item["context_root"])
        identity_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
        if not root.is_absolute() or ".." in root.parts or (root != identity_home and identity_home not in root.parents):
            raise SupervisorError("explicit context root must belong to the current passwd identity")
        actions = item["actions"]
        if type(actions) is not list or any(type(action) is not str or action not in ACTIONS for action in actions) or len(set(actions)) != len(actions):
            raise SupervisorError("queue actions must be distinct bounded child operations")
        if "proposal" in item and type(item["proposal"]) is not dict:
            raise SupervisorError("Board work requires an exact separately prepared proposal")
    canonical_digest(queue)  # Reject nonfinite, oversized and non-JSON inputs.
    return queue


def _material(value: Any) -> Any:
    """Observation metadata is not progress; preserve revisions and all facts."""
    if type(value) is dict:
        return {key: _material(item) for key, item in value.items() if key not in {"observed_at", "observed_at_epoch", "last_observed_at", "created_at", "updated_at"}}
    if type(value) is list:
        return [_material(item) for item in value]
    return value


def _owned(path: Path, root: Path, *, directory: bool = False) -> None:
    if path != root and root not in path.parents:
        raise SupervisorError("controller state escapes the explicit runtime")
    for current in reversed((path, *path.parents)):
        if current != root and root not in current.parents:
            continue
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise SupervisorError("controller state must be owned, protected and contain no symlinks")
    if directory and not path.is_dir():
        raise SupervisorError("controller state requires an existing protected directory")


class SupervisorStore:
    def __init__(self, runtime: Path):
        self.runtime = runtime
        self.root = runtime / ".azure-supervisor"

    @contextmanager
    def locked(self):
        runtime = validate_runtime_path(self.runtime)
        if runtime != self.runtime:
            raise SupervisorError("runtime must not resolve through a symlink")
        home = Path(pwd.getpwuid(os.getuid()).pw_dir)
        for current in (runtime, *runtime.parents):
            if current != home and home not in current.parents:
                break
            _owned(current, home, directory=True)
            if current.name in {"worktrees", "assessment-worktrees", ".git"} or (current / ".git").exists() or (current / ".git").is_symlink():
                raise SupervisorError("supervisor state must be outside Git checkouts and agent worktrees")
        if not self.root.exists() and not self.root.is_symlink():
            self.root.mkdir(mode=0o700)
        _owned(self.root, runtime, directory=True)
        descriptor = os.open(self.root / "supervisor.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022 or info.st_nlink != 1:
                raise SupervisorError("supervisor lock is not one protected regular file")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise SupervisorError("another supervisor is observing or executing this runtime") from exc
            yield
        finally:
            os.close(descriptor)

    def read(self, key: str) -> dict | None:
        path = self.root / (key + ".json")
        if not path.exists() and not path.is_symlink():
            return None
        _owned(path, self.runtime)
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_STATE_BYTES:
            raise SupervisorError("supervisor state is not bounded regular JSON")
        value = strict_json_loads(path.read_bytes())
        if type(value) is not dict:
            raise SupervisorError("supervisor state must be a JSON object")
        return value

    def write(self, key: str, value: dict) -> None:
        if not re.fullmatch(r"(?:run|(?:item|proposal)-[a-f0-9]{64})", key):
            raise SupervisorError("supervisor state key is invalid")
        _owned(self.root, self.runtime, directory=True)
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
        if len(raw) > MAX_STATE_BYTES:
            raise SupervisorError("supervisor state exceeds its bounded receipt size")
        path = self.root / (key + ".json")
        if path.exists() or path.is_symlink():
            _owned(path, self.runtime)
        temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if temporary.exists():
                temporary.unlink()


class AzureSupervisor:
    def __init__(self, config: RuntimeConfig, policy: dict, queue: dict, *, provider=None, client=None,
                 runner=None, clock=None, monotonic=None):
        from atlas_routing import validate_policy
        self.config = config
        self.policy, self.queue = deepcopy(validate_policy(policy)), deepcopy(validate_queue(queue, config))
        if self.policy["repository_url"] != config.repository["url"]:
            raise SupervisorError("routing policy targets another repository")
        self.provider, self.client, self.runner = provider, client, runner
        self.clock, self.monotonic = clock or time.time, monotonic or time.monotonic
        self.store = SupervisorStore(config.runtime_dir) if config.runtime_dir is not None else None
        self.deadline = None

    def preview(self) -> dict:
        """No state read, lock, auth, process, model or provider construction."""
        return {"schema_version": 1, "mode": "preview", "state": "preview", "inert": True,
                "completion": False, "effects": [], "queue_sha256": canonical_digest(self.queue),
                "policy_sha256": canonical_digest(self.policy), "configuration": self.config.report(),
                "limits": self.queue["limits"], "items": [{"id": item["id"], "state": "not_observed", "actions": item["actions"]} for item in self.queue["items"]],
                "next_action": "Explicit observe refreshes native evidence and the local review inbox; exact grants are required separately for run."}

    def _time(self, required: float = 0) -> None:
        if self.deadline is not None and self.monotonic() + required >= self.deadline:
            raise SupervisorError("supervisor time budget cannot admit the next bounded operation")

    def _call(self, function, *args, **kwargs):
        self._time()
        result = function(*args, **kwargs)
        self._time()
        return result

    def _identity(self) -> dict:
        directory = Path(__file__).parent
        hashes = {}
        for name in SOURCE_FILES:
            path = directory / name
            if not path.is_file() or path.is_symlink():
                raise SupervisorError("supervisor child source identity is unavailable")
            hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        return {"configuration_sha256": canonical_digest(self.config.report()), "policy_sha256": canonical_digest(self.policy),
                "code_sha256": canonical_digest(hashes), "queue_sha256": canonical_digest(self.queue)}

    def _client(self):
        require_capability(self.config, "read")
        if self.client is None:
            from atlas_azure_devops import AzureDevOpsClient, azure_cli_headers
            self._time()
            self.client = AzureDevOpsClient(self.config.repository["organization"], self.config.repository["project"],
                self.config.runtime_dir, capabilities=self.config.capabilities, headers=azure_cli_headers())
        return self.client

    def _inspect(self, item: dict) -> dict:
        if self.provider is None:
            from atlas_azure_devops import AzureBoardsProvider
            self.provider = AzureBoardsProvider(self._client())
        packet = item["definition"].get("worker_packet", {})
        contract = {key: packet.get(key) for key in ("expected_manifest", "supplement", "inspection_authority")}
        fingerprint = canonical_digest(contract)
        if fingerprint not in self._snapshot_cache:
            ids = [row["id"] for row in self._selected_items if canonical_digest({key: row["definition"].get("worker_packet", {}).get(key) for key in contract}) == fingerprint]
            self._snapshot_cache[fingerprint] = self._call(self.provider.inspect, ids, expected_manifest=packet.get("expected_manifest"),
                supplement=packet.get("supplement"), authority=packet.get("inspection_authority"), fresh=True)
        return self._snapshot_cache[fingerprint]

    def _config(self, item: dict) -> RuntimeConfig:
        return replace(self.config, repository={**self.config.repository, "checkout": item["context_root"]})

    def _request(self, inbox, item, request, statuses):
        card = self._call(inbox.prepare, request, now=self.clock())
        response = self._call(inbox.find_response, request, now=self.clock())
        statuses.append({"request": request, "card": card, "response_status": response.get("status", "invalid")})
        return response

    def _human(self, inbox, item, definition, statuses):
        packet = definition.get("worker_packet", {})
        if type(packet.get("revision")) is not int or packet["revision"] < 1:
            return [], definition
        revised, receipts = deepcopy(definition), []
        answers = {answer["gate_id"]: answer for answer in revised.get("human_answers", []) if type(answer) is dict and type(answer.get("gate_id")) is str}
        for gate in definition.get("human_gates", []):
            if type(gate) is not dict or gate.get("candidate_sha") is None and gate.get("stage") == "after":
                continue  # A future candidate is a tracked template, not present evidence.
            if gate.get("action") == "draft_pr":
                continue  # Publication uses the immutable prepared template below.
            context = {"issue_id": item["id"], "issue_revision": packet["revision"], "worker_packet_sha256": canonical_digest(packet),
                       "candidate_sha": gate.get("candidate_sha"), "action": gate.get("action"), "policy_sha256": canonical_digest(self.policy)}
            request = {"schema_version": 1, "repository_url": self.config.repository["url"], "issue_id": item["id"],
                       "issue_revision": packet["revision"], "action": "human_gate", "owner": gate.get("owner"),
                       "question": gate.get("question"), "artifact_sha256": gate.get("artifact_sha256"),
                       "policy_sha256": canonical_digest(self.policy), "bindings": None, "step_id": gate.get("id"),
                       "human_gate": {"gate": gate, "context": context}}
            response = self._request(inbox, item, request, statuses)
            if response.get("status") == "accepted" and type(response.get("human_receipt")) is dict:
                receipt = response["human_receipt"]
                receipts.append(receipt)
                if gate.get("stage") == "before" and gate.get("kind") in {"input", "test", "taste", "feedback"}:
                    answers[gate["id"]] = {"gate_id": gate["id"], "response": receipt["response"]}
        if answers:
            revised["human_answers"] = list(answers.values())
        return receipts, revised

    def _operation_request(self, item, action, bindings, identity, *, models=None):
        packet = item["definition"].get("worker_packet", {})
        owner = item["definition"].get("owner")
        _text(owner, "named operation owner", 240)
        return {"schema_version": 1, "repository_url": self.config.repository["url"], "issue_id": item["id"],
                "issue_revision": packet["revision"], "action": action, "owner": owner,
                "question": {"assess": "Authorize the bounded routing assessment and independent challenge for this exact evidence and model policy?",
                             "local_execute": "Authorize local preparation of this exact bounded task, commands, models and acceptance requirements?",
                             "draft_pr": "Authorize draft publication of this exact prepared candidate and acceptance evidence?",
                             "board_write": "Authorize only this exact revision-tested Board proposal?"}[action],
                "artifact_sha256": canonical_digest({"queue_item": item, "identity": identity, "bindings": bindings}),
                "policy_sha256": canonical_digest(self.policy), "bindings": bindings,
                "details": {"task": packet.get("task"), "write_scope": packet.get("write_scope"),
                            "commands": packet.get("commands"), "acceptance": packet.get("acceptance"),
                            "effective_models": models or {}, "repository_url": self.config.repository["url"],
                            "base_commit": packet.get("base_commit"), "candidate_sha": bindings.get("candidate_sha"),
                            "board_patches": item.get("proposal", {}).get("patches", []),
                            "runtime_identity": identity, "completion": False},
                "step_id": item["definition"].get("step", {}).get("id", action) + ":" + action}

    def _provenance(self, state, receipts):
        route = state.get("routing")
        report = state.get("intake_report", {})
        if type(route) is not dict or not report.get("intake"):
            raise SupervisorError("no recorded routing result is available")
        return {"intake": report["intake"], "policy": self.policy, "assessment": route["assessment"],
                "challenge": route["challenge"], "decision": route["decision"], "human_receipts": receipts}

    def _prepared(self, worker, packet):
        return self._call(worker.verify_prepared_evidence, packet)

    def _ingest(self, action, result, state, controller=None, worker=None, packet=None, proposal=None):
        """Require independent durable child proof, never exit-zero inference."""
        if type(result) is not dict or result.get("completion") is True or result.get("release_completion_inferred") is True:
            raise SupervisorError("child result cannot assert supervisor or human completion")
        if action == "assess":
            from atlas_dispatch import verify_routing_transport
            job = controller.store.read("job", controller.key)
            if not job or job.get("state") != "assessed":
                raise SupervisorError("assessment lacks a durable completed parent journal")
            primary, challenge, decision = controller._cache(job, None)
            state["routing"] = {"assessment": primary, "challenge": challenge, "decision": decision}
            if decision.get("route_ready"):
                from atlas_runtime_config import resolve_routed_config
                resolved = resolve_routed_config(controller.config, self._provenance(state, state.get("human_receipts", [])), now=self.clock())
                verify_routing_transport(resolved, now=self.clock())
            return {"state": "assessed", "decision_sha256": canonical_digest(decision), "route_ready": decision.get("route_ready") is True}
        if action in {"local_execute", "draft_pr"}:
            claim = self._prepared(worker, packet)
            if action == "local_execute" and (result.get("state") != "prepared" or result.get("operation_id") != canonical_digest(packet) or result.get("candidate_sha") != claim["candidate_sha"] or result.get("evidence_sha256") != claim["evidence_sha256"]):
                raise SupervisorError("worker result lacks exact durable candidate and acceptance proof")
            if action == "draft_pr" and (result.get("state") != "pr_open" or claim.get("state") != "pr_open" or type(result.get("pull_request_id")) is not int or result["pull_request_id"] != claim.get("pull_request_id")):
                raise SupervisorError("publication result lacks a reconciled durable PR identity")
            return {"state": "prepared" if action == "local_execute" else "pr_open", "candidate_sha": claim["candidate_sha"],
                    "evidence_sha256": claim["evidence_sha256"], "operation_id": canonical_digest(packet),
                    "pull_request_id": claim.get("pull_request_id")}
        if action == "board_write":
            import atlas_azure_reconcile as reconcile
            fingerprint = canonical_digest(proposal)
            if result.get("packet_sha256") != fingerprint or result.get("status") not in {"applied", "already_applied", "no_changes"}:
                raise SupervisorError("Board outcome remains uncertain or lacks its exact proposal receipt")
            path = self.config.runtime_dir / "azure-reconcile" / (fingerprint + ".json")
            _owned(path, self.config.runtime_dir)
            if not path.is_file() or path.stat().st_size > 2_000_000:
                raise SupervisorError("Board journal is not a bounded regular evidence file")
            journal = strict_json_loads(path.read_bytes())
            entries = journal.get("entries", [])
            if journal.get("packet_sha256") != fingerprint or len(entries) != len(proposal["patches"]) or any(entry.get("status") != "verified" for entry in entries):
                raise SupervisorError("Board result lacks complete durable reciprocal readback")
            expected = proposal["baseline"]
            changes = {row["issue_id"]: row for row in proposal["changes"]}
            for entry, patch in zip(entries, proposal["patches"]):
                if entry.get("issue_id") != patch["issue_id"] or entry.get("json_patch") != patch["json_patch"] or not reconcile._same(entry.get("before"), expected):
                    raise SupervisorError("Board journal effects differ from the exact proposal")
                reconcile._check_after(expected, entry["after"], changes[patch["issue_id"]])
                expected = entry["after"]
            current = self._call(reconcile._read_current, self._client(), proposal, self.clock)
            if not reconcile._same(expected, current):
                raise SupervisorError("Board readback changed after the child receipt")
            return {"state": "board_reconciled", "proposal_sha256": fingerprint, "readback_sha256": canonical_digest(current)}
        raise SupervisorError("unsupported child result")

    def _dependency_diff(self, snapshot):
        missing = snapshot.get("missing_dependency_edges", [])
        unexpected = snapshot.get("unexpected_dependency_edges", [])
        return {"missing": missing, "unexpected": unexpected, "expected_count": snapshot.get("expected_dependency_count"),
                "native_count": snapshot.get("native_dependency_count"),
                "next_action": "Read fresh expanded raw items for the missing-edge endpoints, prepare an exact revision-tested Board proposal, then obtain its separate Board grant." if missing or unexpected else None}

    def _prepare_dependencies(self, snapshot, state):
        """Prepare an unapproved exact native-link diff from fresh raw reads."""
        import atlas_azure_reconcile as reconcile
        result = self._dependency_diff(snapshot)
        if not result["missing"]:
            result["preparation_status"] = "not_required" if not result["unexpected"] else "blocked"
            return result
        cache_key = canonical_digest(snapshot)
        if cache_key in self._proposal_cache:
            cached, proof = self._proposal_cache[cache_key]
            if proof:
                state["dependency_proposal"] = deepcopy(proof)
            return deepcopy(cached)
        result["preparation_status"] = "blocked"
        try:
            rows = snapshot.get("items")
            missing = result["missing"]
            if snapshot.get("complete") is not True or result["unexpected"] or type(rows) is not list or not 1 <= len(rows) <= reconcile.MAX_ITEMS:
                raise SupervisorError("dependency proposal needs a complete bounded native graph without unexpected edges")
            reconcile._fresh_timestamp(snapshot.get("observed_at"), 300, self.clock())
            org, project = self.config.repository["organization"], self.config.repository["project"]
            revisions = {}
            for row in rows:
                identifier = row.get("id")
                reconcile.issue_number(identifier, org, project)
                if identifier in revisions or type(row.get("revision")) is not int or row["revision"] < 1:
                    raise SupervisorError("dependency proposal requires exact unique native revisions")
                revisions[identifier] = row["revision"]
            if type(missing) is not list or not 1 <= len(missing) <= reconcile.MAX_ITEMS or any(type(edge) is not list or len(edge) != 2 or any(type(value) is not str or value not in revisions for value in edge) for edge in missing):
                raise SupervisorError("missing-edge evidence lacks complete bounded endpoints")
            pairs = {tuple(edge) for edge in missing}
            if len(pairs) != len(missing):
                raise SupervisorError("missing-edge evidence contains duplicates")
            client = self.client or getattr(self.provider, "client", None)
            if client is None or not callable(getattr(client, "get_work_items", None)):
                raise SupervisorError("fresh expanded raw-item client is unavailable; normalized hashes cannot substitute for immutable field proof")
            if client.organization != org or client.project != project:
                raise SupervisorError("raw-item client targets another Azure namespace")
            requested_at = self.clock()
            raw = self._call(client.get_work_items, sorted(reconcile.issue_number(value, org, project) for value in revisions), fresh=True)
            observed = reconcile._epoch(raw.observed_at)
            if raw.complete is not True or raw.blockers or getattr(raw, "cache_hit", False) or not requested_at - 1 <= observed <= self.clock() + 5:
                raise SupervisorError("fresh complete expanded native reads are required to prepare the dependency proposal")
            projected = [reconcile.project_item(item, org, project) for item in raw.items]
            if len(projected) != len(revisions) or {row["issue_id"]: row["revision"] for row in projected} != revisions:
                raise SupervisorError("native graph revisions changed during dependency proposal preparation")
            native = {row["id"]: set(row.get("native_dependencies", [])) for row in rows}
            if any({relation["target"] for relation in row["relations"] if relation["kind"] == "predecessor"} != native[row["issue_id"]] for row in projected):
                raise SupervisorError("native dependency relations changed during proposal preparation")
            changes = {}
            for identifier, predecessor in sorted(pairs):
                changes.setdefault(identifier, []).append(predecessor)
            spec = {"operator_owned_tags": [], "approved_dependencies": [{"issue_id": identifier, "predecessor": predecessor} for identifier, predecessor in sorted(pairs)],
                    "changes": [{"issue_id": identifier, "add_predecessors": predecessors} for identifier, predecessors in sorted(changes.items())], "max_age_seconds": 900}
            proposal = reconcile.build_proposal({"complete": True, "observed_at": raw.observed_at, "items": raw.items}, spec, org, project, now=self.clock())
            previous = state.get("dependency_proposal", {})
            old = self.store.read("proposal-" + previous["sha256"]) if re.fullmatch(r"[a-f0-9]{64}", str(previous.get("sha256", ""))) else None
            if old is not None and canonical_digest(_material(old)) == canonical_digest(_material(proposal)):
                try:
                    reconcile.validate_proposal(old, now=self.clock())
                    proposal = old
                except ValueError:
                    pass
            fingerprint = canonical_digest(proposal)
            self.store.write("proposal-" + fingerprint, proposal)
            state["dependency_proposal"] = {"sha256": fingerprint, "status": "unapproved",
                "path": str(self.store.root / ("proposal-" + fingerprint + ".json"))}
            result.update(preparation_status="prepared_unapproved", proposal_sha256=fingerprint,
                          proposal_path=state["dependency_proposal"]["path"], execution_eligibility="blocked",
                          next_action="Review the exact sanitized proposal, supply it as the queue item's proposal with explicit board_write action, then obtain its separate exact signed Board grant.")
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError) as exc:
            result["preparation_blocker"] = str(exc)[:500]
        self._proposal_cache[cache_key] = (deepcopy(result), deepcopy(state.get("dependency_proposal")) if result["preparation_status"] == "prepared_unapproved" else None)
        return result

    def _recover(self, item, state, config):
        """Reconcile an interrupted call from durable child evidence only."""
        operation = state.get("operation", {})
        if operation.get("state") not in {"calling", "uncertain"}:
            return None
        action = operation.get("action")
        if action in {"local_execute", "draft_pr"}:
            from atlas_azure_worker import AzureWorker
            from atlas_runtime_config import resolve_routed_config
            packet = state.get("intake_report", {}).get("intake", {}).get("worker_packet")
            if not packet or not state.get("routing"):
                return "uncertain"
            base = AzureWorker(config, clock=self.clock, **({"runner": self.runner} if self.runner else {}))
            try:
                claim = base._publication_claim(packet)
            except (OSError, RuntimeError, ValueError):
                return "uncertain"
            if claim.get("state") not in {"prepared", "publishing", "publication_uncertain", "pr_open"}:
                return "uncertain"
            historical = base._prepared_time(claim, packet)
            resolved = resolve_routed_config(config, self._provenance(state, state.get("human_receipts", [])), now=historical)
            worker = AzureWorker(resolved, provider=self.provider, client=self.client, clock=self.clock, **({"runner": self.runner} if self.runner else {}))
            self._prepared(worker, packet)
            if action == "draft_pr":
                worker.client = self._client()
                prs, refs = self._call(worker._inventory, packet)
                existing = worker._matching_publication(packet, claim, prs, refs)
                if existing is None:
                    return "uncertain"
                state["child_evidence"] = {"state": "pr_open", "candidate_sha": claim["candidate_sha"],
                    "evidence_sha256": claim["evidence_sha256"], "operation_id": canonical_digest(packet),
                    "pull_request_id": existing["pullRequestId"], "readback_verified": True}
            else:
                state["child_evidence"] = {"state": "prepared", "candidate_sha": claim["candidate_sha"],
                    "evidence_sha256": claim["evidence_sha256"], "operation_id": canonical_digest(packet), "pull_request_id": None}
            operation["state"] = "verified"
            return "reconciled"
        if action == "assess":
            from atlas_dispatch import AzureDispatcher
            report = state.get("intake_report", {})
            if not report.get("intake"):
                return "uncertain"
            controller = AzureDispatcher(config, self.policy, report["intake"], report["snapshot"], context_root=item["context_root"], runner=self.runner, clock=self.clock)
            proof = self._ingest("assess", {}, state, controller=controller)
            state["child_evidence"], operation["state"] = proof, "verified"
            return "reconciled"
        if action == "board_write" and item.get("proposal"):
            proof = self._ingest("board_write", {"packet_sha256": canonical_digest(item["proposal"]), "status": "already_applied"}, state, proposal=item["proposal"])
            state["child_evidence"], operation["state"] = proof, "verified"
            return "reconciled"
        return "uncertain"

    def _step(self, item, state, inbox, identity, mode, key):
        from atlas_intake import build_intake
        from atlas_dispatch import AzureDispatcher
        from atlas_azure_worker import AzureWorker, validate_packet
        from atlas_runtime_config import resolve_routed_config
        statuses = []
        snapshot = self._inspect(item)
        result = {"id": item["id"], "state": "blocked", "requests": statuses, "dependency_diff": self._prepare_dependencies(snapshot, state),
                  "completion": False, "child_evidence": state.get("child_evidence"),
                  "intake_report_path": str(self.store.root / (key + ".json"))}
        config = self._config(item)
        pinned = state.get("child_evidence", {}).get("state") in {"prepared", "pr_open"} or state.get("operation", {}).get("state") in {"calling", "uncertain"}
        if pinned and (state.get("entry_sha256") != canonical_digest(item) or any(state.get(name) != identity[name] for name in ("configuration_sha256", "policy_sha256", "code_sha256"))):
            result.update(state="conflict", blockers=["prepared or uncertain scope, policy, code or configuration changed; preserve the original identity and reconcile explicitly"])
            return result
        recovery = self._recover(item, state, config)
        if recovery == "uncertain":
            result.update(state="uncertain", blockers=["prior child outcome lacks complete durable readback; do not replay the operation"])
            return result
        if recovery:
            result.update(recovered=True, child_evidence=state.get("child_evidence"))
        # Prepared candidates retain the exact historical routing identity. They
        # may wait for a human; current native revision/dependencies still matter.
        prepared = state.get("child_evidence", {}).get("state") in {"prepared", "pr_open"}
        definition, receipts = deepcopy(item["definition"]), []
        active = {**item, "definition": definition}
        models = {}
        if prepared:
            if state.get("entry_sha256") != canonical_digest(item) or any(state.get(name) != identity[name] for name in ("configuration_sha256", "policy_sha256", "code_sha256")):
                result.update(state="conflict", blockers=["prepared scope, policy, code or configuration changed; preserve the candidate and reconcile explicitly"])
                return result
            packet = state["intake_report"]["intake"]["worker_packet"]
            active["definition"]["worker_packet"] = deepcopy(packet)
            original_receipts = state.get("human_receipts", [])
            provisional = AzureWorker(config, runner=self.runner, clock=self.clock) if self.runner else AzureWorker(config, clock=self.clock)
            claim = provisional._publication_claim(packet)
            historical = provisional._prepared_time(claim, packet)
            resolved = resolve_routed_config(config, self._provenance(state, original_receipts), now=historical)
            worker = AzureWorker(resolved, provider=self.provider, client=self.client, clock=self.clock, **({"runner": self.runner} if self.runner else {}))
            self._prepared(worker, packet)
            selected = [row for row in snapshot.get("items", []) if row.get("id") == item["id"]]
            from atlas_azure_reconcile import _epoch
            fresh = 0 <= self.clock() - _epoch(snapshot.get("observed_at")) <= 300
            if not fresh or snapshot.get("complete") is not True or snapshot.get("dependency_complete") is not True or snapshot.get("blockers") or len(selected) != 1 or selected[0].get("revision") != packet["revision"] or selected[0].get("eligible") is not True:
                result.update(state="blocked", blockers=["prepared candidate requires fresh unchanged native revision, complete dependencies and current authority"])
                return result
            if state["child_evidence"]["state"] == "pr_open":
                worker.client = self._client()
                prs, refs = self._call(worker._inventory, packet)
                publication = worker._matching_publication(packet, claim, prs, refs)
                if publication is None or publication["pullRequestId"] != state["child_evidence"].get("pull_request_id"):
                    raise SupervisorError("fresh PR inventory no longer confirms the recorded draft publication")
                result["state"] = "pr_open"
                return result
            if "draft_pr" not in item["actions"]:
                result["state"] = "prepared"
                return result
            publication_receipts = []
            for row in worker.publication_gate_contexts(packet, claim["candidate_sha"]):
                gate = row["gate"]
                request = {"schema_version": 1, "repository_url": config.repository["url"], "issue_id": packet["id"], "issue_revision": packet["revision"],
                           "action": "human_gate", "owner": gate["owner"], "question": gate["question"], "artifact_sha256": gate["artifact_sha256"],
                           "policy_sha256": canonical_digest(self.policy), "bindings": None, "step_id": gate["id"], "human_gate": {"gate": gate, "context": row["context"]}}
                response = self._request(inbox, item, request, statuses)
                if response.get("status") != "accepted" or type(response.get("human_receipt")) is not dict:
                    result["state"] = "waiting_human"
                    return result
                publication_receipts.append(response["human_receipt"])
            action = "draft_pr"
            models = resolved.report()["models"]
            bindings = worker.authorization_bindings(packet, action, candidate_sha=claim["candidate_sha"], evidence_sha256=claim["evidence_sha256"], human_receipts=publication_receipts)
            def invoke(grant):
                worker.client = self._client()
                return worker.publish(packet, grant, human_receipts=publication_receipts)
            admission = 120
            ingest = {"worker": worker, "packet": packet}
        elif "board_write" in item["actions"] and item.get("proposal") is not None:
            import atlas_azure_reconcile as reconcile
            proposal = item["proposal"]
            recorded = state.get("child_evidence", {})
            if recorded.get("state") == "board_reconciled" and recorded.get("proposal_sha256") == canonical_digest(proposal):
                proof = self._ingest("board_write", {"packet_sha256": canonical_digest(proposal), "status": "already_applied"}, state, proposal=proposal)
                result.update(state="board_reconciled", child_evidence=proof)
                return result
            reconcile.validate_proposal(proposal, now=self.clock())
            selected = [row for row in snapshot.get("items", []) if row.get("id") == item["id"]]
            baseline = proposal["baseline"].get(item["id"], {})
            if snapshot.get("complete") is not True or len(selected) != 1 or type(selected[0].get("revision")) is not int or selected[0]["revision"] != baseline.get("revision"):
                raise SupervisorError("Board request requires the selected item's current exact proposal revision")
            if "revision" in active["definition"].get("worker_packet", {}) and active["definition"]["worker_packet"]["revision"] != baseline["revision"]:
                raise SupervisorError("Board draft packet revision is stale; review the current native proposal")
            active["definition"]["worker_packet"] = {**active["definition"].get("worker_packet", {}), "id": item["id"], "revision": baseline["revision"]}
            action = "board_write"
            bindings = reconcile.authorization_bindings(proposal, config, self.config.runtime_dir)
            invoke = lambda grant: reconcile.apply_proposal(proposal, self._client(), runtime_dir=self.config.runtime_dir,
                capabilities=config.capabilities, authorization=grant, config=config, clock=self.clock)
            admission, ingest = 30, {"proposal": proposal}
        else:
            previous = state.get("intake_report")
            report = self._call(build_intake, config, self.policy, definition, snapshot, context_root=item["context_root"], previous=previous, now=self.clock())
            if report.get("intake"):
                # Native/default fields are bound BEFORE a human signs the
                # packet. Stale revisions never generate old approval cards.
                definition["worker_packet"] = deepcopy(report["intake"]["worker_packet"])
                receipts, answered = self._human(inbox, item, definition, statuses)
                if answered != definition:
                    report = self._call(build_intake, config, self.policy, answered, snapshot, context_root=item["context_root"], previous=report, now=self.clock())
                definition = answered
                active["definition"] = definition
            state["intake_report"] = report
            state["human_receipts"] = receipts
            result.update(missing_fields=report.get("missing_fields", []), human_questions=report.get("human_questions", []),
                          material_fingerprint=report.get("material_fingerprint"), reused=report.get("reused", False))
            if not report.get("intake"):
                result["state"] = "draft"
                return result
            packet = report["intake"]["worker_packet"]
            active["definition"]["worker_packet"] = packet
            controller = AzureDispatcher(config, self.policy, report["intake"], report["snapshot"], context_root=item["context_root"], runner=self.runner, clock=self.clock)
            decision = controller.preview()["decision"]
            if definition.get("step", {}).get("kind") in {"human", "external"}:
                handoff = controller.check_handoff(receipts) if receipts else None
                result.update(state="human_evidence_verified" if handoff and handoff["state"] == "gate_evidence_verified" else "waiting_human",
                              handoff_evidence=handoff, next_action="The external action remains human-owned; this controller never executes pipelines, approvals, merges or deployments.")
                return result
            if decision.get("blockers"):
                result.update(state="blocked", blockers=decision["blockers"])
                return result
            job = controller.store.read("job", controller.key)
            if job is not None:
                primary, challenge, decision = controller._cache(job, None)
                state["routing"] = {"assessment": primary, "challenge": challenge, "decision": decision}
            if job is None:
                required_inputs = {gate["id"] for gate in definition.get("human_gates", []) if gate.get("id") in decision.get("pending_gates", []) and gate.get("kind") != "approval"}
                if required_inputs - {receipt["gate_id"] for receipt in receipts}:
                    result["state"] = "waiting_human"
                    return result
                if "assess" not in item["actions"]:
                    result.update(state="blocked", blockers=["routing assessment is required but absent from the explicit queue actions"])
                    return result
                action, bindings = "assess", controller.bindings
                models = self.policy["assessment_models"]
                invoke = lambda grant: controller.assess(grant, human_receipts=receipts)
                admission, ingest = 600, {"controller": controller}
            else:
                if decision.get("route_ready") is not True:
                    result.update(state="waiting_human", blockers=decision.get("blockers", []),
                        human_questions=[{"field": "routing_resolution", "owner": definition.get("owner"),
                                          "question": "Review the assessment and independent challenge, then provide the missing business decision or a revised bounded scope/evidence contract.",
                                          "artifact_sha256": canonical_digest(decision), "assessment": primary["result"],
                                          "challenge": challenge["result"] if challenge else None}])
                    return result
                if "local_execute" not in item["actions"]:
                    result["state"] = "assessed"
                    return result
                resolved = resolve_routed_config(config, self._provenance(state, receipts), now=self.clock())
                worker = AzureWorker(resolved, provider=self.provider, client=self.client, clock=self.clock, **({"runner": self.runner} if self.runner else {}))
                validate_packet(resolved, packet)
                action = "local_execute"
                models = resolved.report()["models"]
                bindings = worker.authorization_bindings(packet, action)
                invoke = lambda grant: controller.execute(grant, human_receipts=receipts, provider=self.provider, client=self.client)["worker_result"]
                admission = packet["role_timeout_seconds"] * 5 + sum(command["timeout_seconds"] for command in packet["commands"]) * 2
                ingest = {"worker": worker, "packet": packet}
        request = self._operation_request(active, action, bindings, identity, models=models)
        response = self._request(inbox, item, request, statuses)
        result["next_action"] = action
        if response.get("status") != "accepted" or type(response.get("grant")) is not dict:
            result.update(state="waiting_authority", authority_status=response.get("status", "invalid"))
            return result
        if mode == "observe":
            result["state"] = "authorized_pending_run"
            return result
        self._time(admission)
        state["operation"] = {"action": action, "state": "calling", "request_id": response["request_id"],
                              "request_revision": response["request_revision"], "bindings_sha256": canonical_digest(bindings)}
        self.store.write(key, state)  # Durable intent before the child can act.
        try:
            child = self._call(invoke, response["grant"])
            evidence = self._ingest(action, child, state, **ingest)
        except Exception:
            state["operation"]["state"] = "uncertain"
            self.store.write(key, state)
            raise
        state["operation"]["state"] = "verified"
        state["child_evidence"] = evidence
        result.update(state=evidence["state"], child_evidence=evidence, child_action=action)
        return result

    def _operate(self, mode, *, max_cycles=None, max_items=None, max_seconds=None):
        require_capability(self.config, "read")
        if self.store is None or self.config.runtime_dir is None:
            raise SupervisorError("supervisor requires an explicit existing runtime directory")
        limits = dict(self.queue["limits"])
        for name, supplied in (("max_cycles", max_cycles), ("max_items", max_items), ("max_seconds", max_seconds)):
            if supplied is not None:
                limits[name] = _integer(supplied, 1, limits[name], name)
        from atlas_approval import ApprovalInbox
        inbox = ApprovalInbox(self.config.runtime_dir)
        identity = self._identity()
        self.deadline = self.monotonic() + limits["max_seconds"]
        report = {"schema_version": 1, "mode": mode, "state": "bounded", "completion": False, "inert": False,
                  "effects": ["native-read", "local-status-and-inbox"], "items": [], "cycles": 0,
                  "configuration": self.config.report(), "identity": identity, "limits": limits,
                  "time_enforcement": "Admission and between-operation deadline checks; synchronous child/read transport timeouts may finish after this budget. No detached children."}
        with self.store.locked():
            for cycle in range(limits["max_cycles"]):
                self._time()
                self._selected_items = self.queue["items"][:limits["max_items"]]
                self._snapshot_cache = {}
                self._proposal_cache = {}
                current, stop = [], False
                for item in self._selected_items:
                    self._time()
                    key = "item-" + canonical_digest({"repository_url": self.config.repository["url"], "id": item["id"]})
                    state = self.store.read(key) or {"schema_version": 1, "id": item["id"], "unchanged_observations": 0}
                    if state.get("id") != item["id"] or type(state.get("schema_version")) is not int or state["schema_version"] != 1:
                        raise SupervisorError("durable item identity is invalid")
                    if any(name in state and type(state[name]) is not dict for name in ("child_evidence", "operation", "intake_report", "routing")) or type(state.get("unchanged_observations")) is not int or state["unchanged_observations"] < 0:
                        raise SupervisorError("durable item progress fields are malformed")
                    pinned = state.get("child_evidence", {}).get("state") in {"prepared", "pr_open"} or state.get("operation", {}).get("state") in {"calling", "uncertain"}
                    if not pinned:
                        state.update(identity, entry_sha256=canonical_digest(item))
                    try:
                        outcome = self._step(item, state, inbox, identity, mode, key)
                    except Exception as exc:
                        outcome = {"id": item["id"], "state": "uncertain" if state.get("operation", {}).get("state") in {"calling", "uncertain"} else "blocked",
                                   "completion": False, "blockers": [str(exc)[:500]], "requests": []}
                    stable = {key: outcome.get(key) for key in ("id", "state", "blockers", "missing_fields", "human_questions", "material_fingerprint", "child_evidence", "dependency_diff")}
                    if type(stable.get("dependency_diff")) is dict:
                        stable["dependency_diff"] = {key: value for key, value in stable["dependency_diff"].items() if key not in {"proposal_path", "proposal_sha256"}}
                    stable["request_status"] = [{"action": row["request"]["action"], "owner": row["request"]["owner"],
                        "question": row["request"]["question"], "status": row["response_status"]} for row in outcome.get("requests", [])]
                    fingerprint = canonical_digest(_material(stable))
                    unchanged = state.get("unchanged_observations", 0) + 1 if state.get("observation_fingerprint") == fingerprint else 0
                    state.update(observation_fingerprint=fingerprint, unchanged_observations=unchanged,
                                 last_state=outcome["state"], last_observed_at=self.clock())
                    self.store.write(key, state)
                    outcome["unchanged_observations"] = unchanged
                    current.append(outcome)
                    if outcome.get("child_action"):
                        report["effects"].append("authorized-child:" + outcome["child_action"])
                    if outcome["state"] in {"uncertain", "conflict"}:
                        report["stop_reason"] = outcome["state"]
                        stop = True
                        break
                if not stop and current and all(outcome["unchanged_observations"] >= 1 for outcome in current):
                    report["stop_reason"] = "two_unchanged_observations"
                    stop = True
                report["items"], report["cycles"] = current, cycle + 1
                if stop:
                    break
            report.setdefault("stop_reason", "bounded_cycle_limit")
            report["requests"] = [row for item in report["items"] for row in item.get("requests", [])]
            self.store.write("run", {key: value for key, value in report.items() if key not in {"configuration", "items"}} |
                             {"item_states": [{"id": item["id"], "state": item["state"]} for item in report["items"]]})
        return report

    def observe(self, **limits):
        return self._operate("observe", **limits)

    def run(self, **limits):
        return self._operate("run", **limits)


def _read(path):
    source = validate_input_path(path)
    if source.stat().st_size > MAX_STATE_BYTES:
        raise SupervisorError("supervisor input exceeds its bounded size")
    value = strict_json_loads(source.read_bytes())
    if type(value) is not dict:
        raise SupervisorError("supervisor input must be a JSON object")
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("config", "runtime-dir", "policy", "queue"):
        parser.add_argument("--" + name, required=True)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true")
    modes.add_argument("--observe", action="store_true")
    modes.add_argument("--run", action="store_true")
    for name in ("max-cycles", "max-items", "max-seconds"):
        parser.add_argument("--" + name, type=int)
    args = parser.parse_args(argv)
    try:
        config = load_runtime_config(args.config, runtime_dir=args.runtime_dir)
        controller = AzureSupervisor(config, _read(args.policy), _read(args.queue))
        limits = {key: getattr(args, key) for key in ("max_cycles", "max_items", "max_seconds")}
        result = controller.run(**limits) if args.run else controller.observe(**limits) if args.observe else controller.preview()
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"schema_version": 1, "state": "blocked", "completion": False, "error": str(exc)[:500]}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
