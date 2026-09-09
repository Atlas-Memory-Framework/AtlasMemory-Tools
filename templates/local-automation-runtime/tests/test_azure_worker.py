from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager, redirect_stderr
from dataclasses import replace
from datetime import datetime, timezone
import json
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import atlas_azure_worker as worker
from atlas_runtime_config import ROLES, RoleSettings, RuntimeConfig


NOW = 1_800_000_000.0
BASE = "a" * 40
HEAD = "b" * 40
REPAIR = "c" * 40
URL = "https://dev.azure.com/Instablinds/Instablinds/_git/Website"


class FakeProvider:
    def __init__(self):
        self.revision = 7
        self.calls = []
        self.snapshot_overrides = {}
        self.change_after = None

    def inspect(self, ids, **kwargs):
        self.calls.append((ids, kwargs))
        revision = self.revision + int(self.change_after is not None and len(self.calls) >= self.change_after)
        snapshot = {"complete": True, "dependency_complete": True, "observed_at": datetime.fromtimestamp(NOW, timezone.utc).isoformat(),
                    "blockers": [], "items": [{"id": "azdo:Instablinds:Instablinds:17", "revision": revision,
                    "eligible": True, "blockers": [], "dependencies": []}]}
        snapshot.update(deepcopy(self.snapshot_overrides))
        return snapshot


class SimulatedCrash(BaseException):
    pass


class FakeClient:
    def __init__(self):
        self.prs = []
        self.refs = []
        self.calls = []
        self.writes = []
        self.incomplete = False
        self.stale = False
        self.write_failure = None
        self.candidate = HEAD
        self.throttle_slots = 0
        self.throttle = SimpleNamespace(slot=self.slot)

    @contextmanager
    def slot(self):
        self.throttle_slots += 1
        yield lambda seconds: None

    def paged(self, path, **kwargs):
        self.calls.append((path, kwargs))
        self.assert_fresh = kwargs.get("fresh") is True
        return SimpleNamespace(items=deepcopy(self.prs if path.endswith("pullrequests") else self.refs),
                               complete=not self.incomplete, blockers=[],
                               observed_at=getattr(self, "observed_at", datetime.fromtimestamp(NOW - (600 if self.stale else 0), timezone.utc).isoformat()))

    def request(self, method, path, **kwargs):
        kwargs["before_write"]()
        self.writes.append((method, path, deepcopy(kwargs)))
        if self.write_failure == "absent":
            raise TimeoutError("lost response")
        body = kwargs["data"]
        self.prs.append({**deepcopy(body), "pullRequestId": 51, "status": "active",
                         "lastMergeSourceCommit": {"commitId": self.candidate}})
        if self.write_failure == "after":
            raise TimeoutError("lost response after commit")
        if self.write_failure == "crash":
            raise SimulatedCrash()
        return deepcopy(self.prs[-1])


class FakeRunner:
    def __init__(self, packet, client):
        self.packet, self.client = packet, client
        self.head = BASE
        self.calls = []
        self.write_role_evidence = True
        self.write_acceptance_evidence = True
        self.acceptance_exit = 0
        self.review_rejects = 0
        self.outside_scope = False
        self.fail_help = False
        self.push_failure = False
        self.push_race = False
        self.wrong_role_model = False
        self.hooks_path = ""
        self.push_url = URL
        self.direct_push_url = URL
        self.role_schema_version = 1
        self.acceptance_schema_version = 1
        self.usage_tokens = 50

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        result = SimpleNamespace(returncode=0, stdout="", stderr="")
        if argv[0] == "git":
            args = argv[3:]
            if args[:3] == ["remote", "get-url", "origin"]:
                result.stdout = URL + "\n"
            elif args[:3] == ["remote", "get-url", "--push"]:
                result.stdout = self.push_url + "\n"
            elif args == ["config", "--get", "core.hooksPath"]:
                result.stdout = self.hooks_path
                result.returncode = 0 if self.hooks_path else 1
            elif args[:1] == ["-c"] and args[2:5] == ["remote", "get-url", "--push"]:
                result.stdout = self.direct_push_url + "\n"
            elif args[:2] == ["symbolic-ref", "--short"]:
                result.stdout = self.packet["branch"] + "\n"
            elif args[:2] == ["rev-parse", "--verify"]:
                result.stdout = (self.head if args[2] == "HEAD" else BASE) + "\n"
            elif args[:2] == ["diff", "--name-only"] and args[-1] != "HEAD":
                result.stdout = (("docs/escape.md" if self.outside_scope else "src/change.py") + "\0") if self.head != BASE else ""
            elif args and args[0] == "push":
                self.client.refs = [{"name": "refs/heads/" + self.packet["branch"], "objectId": "d" * 40 if self.push_race else self.head}]
                if self.push_failure:
                    raise subprocess.TimeoutExpired(argv, 120)
            return result
        if "--help" in argv:
            result.stdout = "--sandbox --model --output-last-message --json --ephemeral --config --cd"
            result.returncode = int(self.fail_help)
            return result
        if "--version" in argv:
            result.stdout = "codex-cli 0.153.4\n"
            return result
        if argv[:2] == ["codex", "exec"]:
            if self.usage_tokens is not None:
                result.stdout = json.dumps({"type": "turn.completed", "usage": {"input_tokens": self.usage_tokens, "output_tokens": 0}}) + "\n"
            data = json.loads(kwargs["input"].split("\n", 1)[1])
            if data["role"] == "implementation":
                self.head = HEAD
            elif data["role"] == "repair":
                self.head = REPAIR
                self.client.candidate = REPAIR
            decision = "pass"
            if data["role"] == "review" and self.review_rejects:
                self.review_rejects -= 1
                decision = "fail"
            output = Path(argv[argv.index("--output-last-message") + 1])
            if self.write_role_evidence:
                output.write_text(json.dumps({"schema_version": self.role_schema_version, "packet_sha256": data["packet_sha256"],
                    "role": data["role"], "model": "silent-fallback" if self.wrong_role_model else data["model"],
                    "reasoning": data["reasoning"], "candidate_sha": self.head, "decision": decision,
                    "acceptance_ids": data["acceptance_ids"]}), encoding="utf-8")
            return result
        if argv[:2] == ["codex", "sandbox"]:
            environment = kwargs["env"]
            if self.write_acceptance_evidence:
                path = Path(environment["ATLAS_EVIDENCE_DIR"]) / "unit.json"
                path.write_text(json.dumps({"schema_version": self.acceptance_schema_version, "packet_sha256": environment["ATLAS_PACKET_SHA256"],
                    "candidate_sha": environment["ATLAS_CANDIDATE_SHA"], "acceptance_id": "unit-pass",
                    "command_id": "unit", "result": "pass"}), encoding="utf-8")
            result.returncode = self.acceptance_exit
            return result
        raise AssertionError(f"unexpected command {argv}")


class AzureWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.runtime = self.root / "runtime"
        self.workspace = self.runtime / "worktrees" / "item-17"
        self.workspace.mkdir(parents=True)
        (self.workspace / ".git").mkdir()
        self.config = RuntimeConfig(provider="azure-devops", runtime_dir=self.runtime,
            repository={"organization": "Instablinds", "project": "Instablinds", "name": "Website", "url": URL,
                        "base_branch": "develop", "checkout": str(self.workspace)},
            capabilities=frozenset({"read", "local_execute", "draft_pr"}),
            roles={role: RoleSettings("gpt-6-astra", "max", "test") for role in ROLES}, source="fixture")
        self.packet = {"schema_version": 1, "id": "azdo:Instablinds:Instablinds:17", "revision": 7,
                       "repository_url": URL, "base_branch": "develop", "base_commit": BASE,
                       "branch": "feature/atlas-17", "write_scope": ["src"], "task": "Implement reviewed one-file repair",
                       "commands": [{"id": "unit", "argv": ["python3", "-B", "tests/acceptance.py"], "timeout_seconds": 30}],
                       "acceptance": [{"id": "unit-pass", "command_id": "unit", "evidence_file": "unit.json"}],
                       "role_timeout_seconds": 60, "expected_manifest": {"schema_version": 1},
                       "inspection_authority": {"execution_authorized": True, "approval_record": "fixture"}}
        # Tests isolate path policy to a temporary root. Production uses passwd home.
        for name in ("atlas_azure_worker.validate_runtime_path", "atlas_runtime_config.validate_runtime_path"):
            patcher = mock.patch(name, side_effect=lambda path, **kwargs: Path(path).resolve(strict=True))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.provider, self.client = FakeProvider(), FakeClient()
        self.runner = FakeRunner(self.packet, self.client)
        self.worker = worker.AzureWorker(self.config, provider=self.provider, client=self.client, runner=self.runner, clock=lambda: NOW)
        # These regression cases isolate worker behavior from cryptography.
        # AzureWorkerAuthorityTests below exercise the real verifier and signatures.
        self.authority_patcher = mock.patch.object(worker, "verify_grant", side_effect=self.behavioral_authority)
        self.authority_mock = self.authority_patcher.start()
        self.addCleanup(self.authority_patcher.stop)

    @staticmethod
    def behavioral_authority(runtime, envelope, action, bindings, **kwargs):
        if not isinstance(envelope, dict) or type(envelope.get("schema_version")) is not int or envelope["schema_version"] != 1 or envelope.get("actions") != [action]:
            raise worker.AuthorityError("explicitly mocked behavioral authorization does not match")
        if worker.digest({key: envelope.get(key) for key in bindings}) != worker.digest(bindings):
            raise worker.AuthorityError("explicitly mocked behavioral bindings do not match")
        return {"subject": "operator"}

    def auth(self, capability="local_execute"):
        candidate_sha, evidence_sha256 = None, None
        if capability == "draft_pr":
            candidate_sha, evidence_sha256 = HEAD, "e" * 64
            if (self.worker.store.root / "claims.json").exists():
                claim = self.worker._publication_claim(self.packet)
                candidate_sha, evidence_sha256 = claim.get("candidate_sha"), claim.get("evidence_sha256")
        bindings = worker.AzureWorker(self.config, clock=lambda: NOW).authorization_bindings(
            self.packet, capability, candidate_sha=candidate_sha, evidence_sha256=evidence_sha256)
        return {**bindings, "actions": [capability], "approval_record": "mocked behavioral fixture only"}

    def execute(self):
        return self.worker.execute(self.packet, self.auth())

    def publish(self):
        return self.worker.publish(self.packet, self.auth("draft_pr"))

    def test_preview_is_inert_and_reports_all_effective_models(self):
        before = sorted(str(path) for path in self.root.rglob("*"))
        result = self.worker.preview(self.packet)
        self.assertEqual(result["state"], "preview")
        self.assertFalse(result["completion"])
        self.assertEqual(before, sorted(str(path) for path in self.root.rglob("*")))
        self.assertEqual(self.runner.calls, [])
        self.assertEqual(self.provider.calls, [])
        self.assertEqual(self.client.calls, [])
        for role, argv in result["effective_commands"].items():
            self.assertIn(role, ROLES)
            self.assertEqual(argv[argv.index("-m") + 1], "gpt-6-astra")
            self.assertIn('model_reasoning_effort="max"', argv)
            self.assertIn('approval_policy="on-request"', argv)
            self.assertIn("sandbox_workspace_write.network_access=false", argv)
            self.assertNotIn("--full-auto", argv)

    def test_cli_preview_without_python_B_creates_no_bytecode_claim_or_job(self):
        scripts = self.root / "scripts"
        scripts.mkdir()
        for name in ("atlas-agent-azure-worker", "atlas_azure_worker.py", "atlas_runtime_config.py", "atlas_azure_devops.py", "atlas_authority.py"):
            (scripts / name).write_text((ROOT / name).read_text(encoding="utf-8"), encoding="utf-8")
        config_path, packet_path = self.root / "config.json", self.root / "packet.json"
        config_path.write_text(json.dumps({"schema_version": 1, "provider": "azure-devops", "runtime_dir": str(self.runtime),
            "repository": self.config.repository, "capabilities": ["read"], "sandbox": "workspace-write",
            "approval_policy": "on-request", "models": {role: {"model": "gpt-6-astra", "reasoning": "max"} for role in ROLES}}))
        packet_path.write_text(json.dumps(self.packet))
        before = sorted(str(path) for path in self.root.rglob("*"))
        # Simulate the current identity's home inside this isolated subprocess fixture.
        code = ("import pwd,types,sys,runpy; fixture_home=sys.argv[1]; script=sys.argv[2]; "
                "pwd.getpwuid=lambda uid:types.SimpleNamespace(pw_dir=fixture_home,pw_name='fixture'); "
                "sys.path.insert(0,str(__import__('pathlib').Path(script).parent)); sys.argv=sys.argv[2:]; "
                "runpy.run_path(script,run_name='__main__')")
        result = subprocess.run([sys.executable, "-c", code, str(self.root), str(scripts / "atlas-agent-azure-worker"),
            "--config", str(config_path), "--runtime-dir", str(self.runtime), "--packet", str(packet_path), "--dry-run"],
            text=True, capture_output=True, timeout=10, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["inert"])
        self.assertEqual(before, sorted(str(path) for path in self.root.rglob("*")))

    def test_missing_commands_or_acceptance_never_claims_or_completes(self):
        for field in ("commands", "acceptance"):
            with self.subTest(field=field):
                packet = deepcopy(self.packet)
                packet[field] = []
                with self.assertRaises(worker.WorkerBlocked):
                    self.worker.execute(packet, self.auth())
        self.assertFalse((self.runtime / "state").exists())
        self.assertEqual(self.runner.calls, [])

    def test_exact_operation_authorization_required_before_any_process_or_claim(self):
        for auth in (None, self.auth("draft_pr"), {**self.auth(), "packet_sha256": "bad"}, {**self.auth(), "runtime_dir": "/elsewhere"}, {**self.auth(), "schema_version": True}):
            with self.subTest(auth=auth), self.assertRaises(worker.WorkerBlocked):
                self.worker.execute(self.packet, auth)
        self.assertFalse((self.runtime / "state").exists())
        self.assertEqual(self.runner.calls, [])

    def test_model_change_invalidates_prior_authorization_before_any_process(self):
        approved = self.auth()
        self.worker.config = replace(self.config, roles={role: RoleSettings("changed-model", "low", "test") for role in ROLES})
        with self.assertRaisesRegex(worker.WorkerBlocked, "authorization"):
            self.worker.execute(self.packet, approved)
        self.assertEqual(self.runner.calls, [])
        self.assertFalse((self.runtime / "state").exists())

    def test_namespace_base_and_isolated_worktree_are_required(self):
        for field, value in (("id", "17"), ("base_branch", "main"), ("branch", "main"), ("repository_url", "https://github.com/x/y"), ("schema_version", True)):
            packet = {**self.packet, field: value}
            with self.subTest(field=field), self.assertRaises(worker.WorkerBlocked):
                self.worker.preview(packet)
        invalid = replace(self.config, repository={**self.config.repository, "checkout": str(self.root)})
        with self.assertRaises(worker.WorkerBlocked):
            worker.AzureWorker(invalid).preview(self.packet)

    def test_stale_incomplete_dependency_and_authority_reads_block_claims(self):
        for overrides in ({"complete": False}, {"dependency_complete": False}, {"blockers": ["18 edges unapproved"]},
                          {"observed_at": datetime.fromtimestamp(NOW - 400, timezone.utc).isoformat()}):
            self.provider.snapshot_overrides = overrides
            with self.subTest(overrides=overrides), self.assertRaises(worker.WorkerBlocked):
                self.execute()
            self.assertFalse((self.runtime / "state").exists())

    def test_revision_change_after_claim_blocks_before_agent(self):
        self.provider.change_after = 2
        with self.assertRaisesRegex(worker.WorkerBlocked, "revision"):
            self.execute()
        self.assertFalse(any(argv[:2] == ["codex", "exec"] and "--help" not in argv for argv, _ in self.runner.calls))
        self.assertEqual(self.worker.store.get(worker.digest(self.packet))["state"], "blocked")

    def test_successful_process_without_role_evidence_is_blocked(self):
        self.runner.write_role_evidence = False
        with self.assertRaises(worker.WorkerBlocked):
            self.execute()
        self.assertEqual(self.worker.store.get(worker.digest(self.packet))["state"], "blocked")

    def test_successful_validator_without_acceptance_evidence_is_blocked(self):
        self.runner.write_acceptance_evidence = False
        with self.assertRaises(worker.WorkerBlocked):
            self.execute()
        self.assertEqual(self.worker.store.get(worker.digest(self.packet))["state"], "blocked")

    def test_boolean_role_schema_is_not_integer_evidence(self):
        self.runner.role_schema_version = True
        with self.assertRaises(worker.WorkerBlocked):
            self.execute()
        self.assertEqual(self.worker.store.get(worker.digest(self.packet))["state"], "blocked")

    def test_boolean_acceptance_schema_is_not_integer_evidence(self):
        self.runner.acceptance_schema_version = True
        with self.assertRaises(worker.WorkerBlocked):
            self.execute()
        self.assertEqual(self.worker.store.get(worker.digest(self.packet))["state"], "blocked")

    def test_model_fallback_evidence_is_rejected(self):
        self.runner.wrong_role_model = True
        with self.assertRaisesRegex(worker.WorkerBlocked, "configuration"):
            self.execute()

    def test_cli_options_must_be_supported_before_claim(self):
        self.runner.fail_help = True
        with self.assertRaisesRegex(worker.WorkerBlocked, "installed Codex"):
            self.execute()
        self.assertFalse((self.runtime / "state").exists())

    def test_source_scope_violation_blocks_completion(self):
        self.runner.outside_scope = True
        with self.assertRaisesRegex(worker.WorkerBlocked, "outside the reviewed scope"):
            self.execute()

    def test_prepared_candidate_is_not_board_completion_and_validation_is_sandboxed(self):
        result = self.execute()
        self.assertEqual(result["state"], "prepared")
        self.assertFalse(result["completion"])
        self.assertFalse(result["board_state_changed"])
        self.assertEqual(self.client.writes, [])
        validators = [(argv, kwargs) for argv, kwargs in self.runner.calls if argv[:2] == ["codex", "sandbox"] and "--help" not in argv]
        self.assertEqual(len(validators), 1)
        argv, kwargs = validators[0]
        self.assertEqual(argv[argv.index("--") + 1:], self.packet["commands"][0]["argv"])
        self.assertIn("sandbox_workspace_write.writable_roots=[]", argv)
        self.assertIn("sandbox_workspace_write.network_access=false", argv)
        self.assertNotIn("shell", kwargs)
        self.assertEqual(kwargs["env"]["ATLAS_CANDIDATE_SHA"], HEAD)

    def test_one_repair_is_bounded_and_new_candidate_is_revalidated(self):
        self.runner.review_rejects = 1
        result = self.execute()
        self.assertEqual(result["candidate_sha"], REPAIR)
        roles = [json.loads(kwargs["input"].split("\n", 1)[1])["role"] for argv, kwargs in self.runner.calls if argv[:2] == ["codex", "exec"] and "--help" not in argv]
        self.assertEqual(roles, ["planning", "implementation", "review", "repair", "review"])
        self.assertEqual(sum(argv[:2] == ["codex", "sandbox"] and "--help" not in argv for argv, _ in self.runner.calls), 2)

    def test_repeated_review_failure_cannot_start_unbounded_repair(self):
        self.runner.review_rejects = 2
        with self.assertRaisesRegex(worker.WorkerBlocked, "single bounded repair"):
            self.execute()
        roles = [json.loads(kwargs["input"].split("\n", 1)[1])["role"] for argv, kwargs in self.runner.calls if argv[:2] == ["codex", "exec"] and "--help" not in argv]
        self.assertEqual(roles.count("repair"), 1)

    def test_issue_text_is_stdin_data_never_command_argv(self):
        malicious = "$(touch /tmp/untrusted); az pipelines run; --dangerously-bypass-approvals-and-sandbox"
        self.packet["task"] = malicious
        self.execute()
        self.assertFalse(any(malicious in argv for argv, _ in self.runner.calls))
        self.assertTrue(any(malicious in (kwargs.get("input") or "") for _, kwargs in self.runner.calls))

    def test_path_conflicts_cover_prefixes_globs_and_repository_namespace(self):
        for left, right in ((["src"], ["src/a.py"]), (["src/*.py"], ["src/nested/a.ts"]), (["**/a.py"], ["docs/b.md"]), ([], ["src"])):
            self.assertTrue(worker.scopes_overlap(left, right))
        self.assertFalse(worker.scopes_overlap(["src"], ["src2"]))
        self.assertFalse(worker.path_allowed("src/a.ts", ["src/*.py"]))
        self.worker.store.claim(self.packet, self.workspace, "config")
        other = {**self.packet, "id": "azdo:Instablinds:Instablinds:18", "write_scope": ["src/nested/*.py"]}
        with self.assertRaisesRegex(worker.WorkerBlocked, "conflicts"):
            self.worker.store.claim(other, self.workspace.parent / "item-18", "config")
        other["repository_url"] = "https://dev.azure.com/Instablinds/Instablinds/_git/Other"
        self.worker.store.claim(other, self.workspace.parent / "item-18", "config")

    def test_stale_claim_is_never_reclaimed_from_age_or_restart(self):
        claim = self.worker.store.claim(self.packet, self.workspace, "config")
        self.worker.store.update(worker.digest(self.packet), claim["owner"], created_at=0, pid=999999999)
        with self.assertRaisesRegex(worker.WorkerBlocked, "already has"):
            worker.ClaimStore(self.runtime).claim(self.packet, self.workspace, "config")

    def test_same_namespaced_issue_with_different_scope_and_packet_cannot_be_claimed_twice(self):
        self.worker.store.claim(self.packet, self.workspace, "config")
        other = {**self.packet, "task": "different contract", "write_scope": ["docs"]}
        with self.assertRaisesRegex(worker.WorkerBlocked, "namespaced issue"):
            self.worker.store.claim(other, self.workspace.parent / "different", "config")

    def test_cross_process_claim_has_exactly_one_winner(self):
        program = ("import json,sys,pathlib; sys.path.insert(0,sys.argv[1]); import atlas_azure_worker as w\n"
                   "try:\n w.ClaimStore(pathlib.Path(sys.argv[2])).claim(json.loads(sys.argv[3]),pathlib.Path(sys.argv[4]),'config'); print('claimed')\n"
                   "except w.WorkerBlocked:\n print('blocked')\n")
        argv = [sys.executable, "-B", "-c", program, str(ROOT), str(self.runtime), json.dumps(self.packet), str(self.workspace)]
        processes = [subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
        outputs = [process.communicate(timeout=10) for process in processes]
        self.assertEqual([process.returncode for process in processes], [0, 0], outputs)
        self.assertEqual(sorted(out.strip() for out, _ in outputs), ["blocked", "claimed"])

    def test_symlinked_state_and_evidence_do_not_create_outside_files(self):
        outside = self.root / "outside"
        outside.mkdir()
        (self.runtime / "state").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(worker.WorkerBlocked):
            self.worker.store.claim(self.packet, self.workspace, "config")
        self.assertEqual(list(outside.iterdir()), [])
        (self.workspace / ".atlas-worker").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(worker.WorkerBlocked):
            self.worker._evidence_dir(self.workspace, self.packet, create=True)
        self.assertEqual(list(outside.iterdir()), [])

    def test_draft_publication_is_separate_and_duplicate_safe(self):
        self.execute()
        with self.assertRaises(worker.WorkerBlocked):
            self.worker.publish(self.packet, self.auth())
        result = self.publish()
        self.assertEqual(result["state"], "pr_open")
        self.assertFalse(result["completion"])
        self.assertEqual(len(self.client.writes), 1)
        self.assertTrue(self.client.writes[0][2]["data"]["isDraft"])
        self.assertEqual(self.client.writes[0][2]["capability"], "draft_pr")
        self.assertNotIn("completionOptions", self.client.writes[0][2]["data"])
        result = self.publish()
        self.assertTrue(result["reconciled"])
        self.assertEqual(len(self.client.writes), 1)
        pushes = [argv for argv, _ in self.runner.calls if argv[0] == "git" and "push" in argv]
        self.assertEqual(len(pushes), 1)
        self.assertEqual(self.client.throttle_slots, 1)
        self.assertIn("--force-with-lease=refs/heads/feature/atlas-17:", pushes[0])
        self.assertTrue(all(kwargs["fresh"] for _, kwargs in self.client.calls))
        self.assertTrue(all(kwargs.get("pagination") == "skip" for path, kwargs in self.client.calls if path.endswith("pullrequests")))

    def test_lost_success_response_reconciles_without_second_post(self):
        self.execute()
        self.client.write_failure = "after"
        self.assertTrue(self.publish()["reconciled"])
        self.assertEqual(len(self.client.writes), 1)

    def test_crash_after_post_restart_only_reconciles(self):
        self.execute()
        self.client.write_failure = "crash"
        with self.assertRaises(SimulatedCrash):
            self.publish()
        self.worker = worker.AzureWorker(self.config, provider=self.provider, client=self.client, runner=self.runner, clock=lambda: NOW)
        self.assertTrue(self.publish()["reconciled"])
        self.assertEqual(len(self.client.writes), 1)

    def test_uncertain_absent_post_never_replayed_on_restart(self):
        self.execute()
        self.client.write_failure = "absent"
        with self.assertRaises(worker.WorkerBlocked):
            self.publish()
        self.worker = worker.AzureWorker(self.config, provider=self.provider, client=self.client, runner=self.runner, clock=lambda: NOW)
        with self.assertRaisesRegex(worker.WorkerBlocked, "never replay"):
            self.publish()
        self.assertEqual(len(self.client.writes), 1)

    def test_push_timeout_reconciles_matching_created_ref_before_pr(self):
        self.execute()
        self.runner.push_failure = True
        self.assertEqual(self.publish()["state"], "pr_open")
        self.assertEqual(len(self.client.writes), 1)

    def test_concurrent_ref_creation_with_different_head_cannot_create_pr(self):
        self.execute()
        self.runner.push_race = True
        with self.assertRaisesRegex(worker.WorkerBlocked, "remote feature ref differs"):
            self.publish()
        self.assertEqual(self.client.writes, [])

    def test_existing_remote_head_conflict_never_pushes(self):
        self.execute()
        self.client.refs = [{"name": "refs/heads/feature/atlas-17", "objectId": "f" * 40}]
        before = len(self.runner.calls)
        with self.assertRaises(worker.WorkerBlocked):
            self.publish()
        self.assertFalse(any("push" in argv for argv, _ in self.runner.calls[before:]))
        self.assertEqual(self.client.writes, [])

    def test_stale_incomplete_pr_reads_and_revision_conflict_block_publication(self):
        self.execute()
        for attribute in ("incomplete", "stale"):
            setattr(self.client, attribute, True)
            with self.subTest(attribute=attribute), self.assertRaises(worker.WorkerBlocked):
                self.publish()
            setattr(self.client, attribute, False)
        self.provider.revision += 1
        with self.assertRaises(worker.WorkerBlocked):
            self.publish()
        self.assertEqual(self.client.writes, [])
        self.assertFalse(any("push" in argv for argv, _ in self.runner.calls))

    def test_changed_acceptance_file_blocks_publication(self):
        self.execute()
        path = self.workspace / ".atlas-worker" / worker.digest(self.packet) / "unit.json"
        data = json.loads(path.read_text())
        data["candidate_sha"] = "f" * 40
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(worker.WorkerBlocked, "acceptance evidence"):
            self.publish()
        self.assertEqual(self.client.calls, [])

    def test_missing_review_evidence_blocks_publication(self):
        self.execute()
        path = self.workspace / ".atlas-worker" / worker.digest(self.packet) / "review-0.json"
        path.rename(path.with_suffix(".unavailable"))
        with self.assertRaises(worker.WorkerBlocked):
            self.publish()
        self.assertEqual(self.client.writes, [])

    def test_pre_push_hooks_and_changed_push_url_cannot_execute_on_host(self):
        self.execute()
        for attribute, value in (("hooks_path", "/tmp/untrusted"), ("push_url", "https://github.com/x/y"), ("direct_push_url", "https://github.com/x/y")):
            setattr(self.runner, attribute, value)
            with self.subTest(attribute=attribute), self.assertRaises(worker.WorkerBlocked):
                self.worker._publication_git_policy(self.workspace, self.packet)
            setattr(self.runner, attribute, "" if attribute == "hooks_path" else URL)
        hook = self.workspace / ".git" / "hooks" / "pre-push"
        hook.parent.mkdir()
        hook.write_text("#!/bin/sh\nexit 42\n")
        hook.chmod(0o700)
        with self.assertRaisesRegex(worker.WorkerBlocked, "pre-push"):
            self.worker._publication_git_policy(self.workspace, self.packet)
        self.assertFalse(any("push" in argv for argv, _ in self.runner.calls))
        self.assertEqual(self.client.writes, [])

    def test_concurrent_publication_lock_blocks_all_remote_writes(self):
        self.execute()
        with self.worker.store.locked("publication-" + worker.digest(self.packet)):
            with self.assertRaisesRegex(worker.WorkerBlocked, "another process"):
                self.publish()
        self.assertEqual(self.client.writes, [])

    def test_unsafe_command_overrides_are_rejected(self):
        for argv in (["bash", "-c", "echo bypass"], ["codex", "--full-auto"], ["az", "pipelines", "run"],
                     ["python3", "-c", "eval('untrusted')"], ["git", "push", "origin", "main"], ["npm", "test", "--add-dir", "/"]):
            with self.subTest(argv=argv), self.assertRaises(worker.WorkerBlocked):
                worker.validate_command(argv)
        for branch in ("main", "develop", "feature/../main", "feature/x:main", "+feature/x"):
            with self.subTest(branch=branch), self.assertRaises(worker.WorkerBlocked):
                worker.create_only_push_command(self.workspace, HEAD, branch, URL)

    def test_other_identity_and_model_environment_overrides_are_not_inherited(self):
        with mock.patch.dict(os.environ, {"CODEX_HOME": "/home/other/.codex"}):
            with self.assertRaises(worker.WorkerBlocked):
                worker.safe_environment()
        with mock.patch.dict(os.environ, {"MODEL": "unapproved", "CODEX_ARGS": "--full-auto", "BASH_ENV": "/tmp/attack", "GIT_SSH_COMMAND": "attack"}):
            environment = worker.safe_environment()
            self.assertFalse({"MODEL", "CODEX_ARGS", "BASH_ENV", "GIT_SSH_COMMAND"} & environment.keys())


class AzureWorkerAuthorityTests(unittest.TestCase):
    """Direct worker APIs with authenticated synthetic grants and no live tools."""

    behavioral_authority = staticmethod(AzureWorkerTests.behavioral_authority)

    def setUp(self):
        AzureWorkerTests.setUp(self)
        self.authority_patcher.stop()
        self.runtime.chmod(0o700)
        sys.path.insert(0, str(ROOT / "tests" / "fixtures"))
        from authority_fixture import AuthorityFixture
        import atlas_authority
        self.fixture = AuthorityFixture(self.runtime, now=int(NOW))
        patcher = mock.patch.object(atlas_authority, "pwd", SimpleNamespace(
            getpwuid=lambda uid: SimpleNamespace(pw_dir=str(self.root))))
        patcher.start()
        self.addCleanup(patcher.stop)
        # Full dispatcher transport is covered by test_atlas_dispatch; these
        # direct worker cases keep real cryptography and shared budget handling.
        self.transport_patcher = mock.patch("atlas_dispatch.verify_routing_transport", return_value={"verified_fixture": True})
        self.transport_patcher.start()
        self.addCleanup(self.transport_patcher.stop)
        path_patcher = mock.patch("atlas_dispatch.validate_runtime_path", side_effect=lambda path, **kwargs: Path(path).resolve(strict=True))
        path_patcher.start()
        self.addCleanup(path_patcher.stop)

    def grant(self, action="local_execute", *, human_receipts=None, **overrides):
        extras = {}
        if action == "draft_pr":
            claim = self.worker._publication_claim(self.packet)
            extras = {"candidate_sha": claim["candidate_sha"], "evidence_sha256": claim["evidence_sha256"]}
        bindings = self.worker.authorization_bindings(self.packet, action, human_receipts=human_receipts, **extras)
        bindings.update(overrides)
        return self.fixture.grant(action, bindings)

    def prepare(self):
        return self.worker.execute(self.packet, self.grant())

    def revoke(self):
        self.fixture.registry["revoked_grants"] = ["synthetic-test-grant"]
        self.fixture.update_trust()

    def routed(self, *, human_gate=False, signed_human=False, publication_gate=False):
        from atlas_authority import canonical_digest
        from atlas_human_gates import gate_bindings
        from atlas_runtime_config import resolve_routed_config
        from test_atlas_routing import assessment_fixture, gate_fixture, intake_fixture, policy_fixture, source
        import atlas_routing
        self.packet["write_scope"] = ["src/change.py"]
        self.packet["expected_manifest"] = {"schema_version": 1, "organization": "Instablinds", "project": "Instablinds",
                                            "dependencies": {self.packet["id"]: []}}
        self.packet["inspection_authority"]["dependency_contract_sha256"] = worker.digest(self.packet["expected_manifest"])
        intake, policy = intake_fixture(), policy_fixture()
        intake["worker_packet"] = deepcopy(self.packet)
        intake["affected_paths"] = ["src/change.py"]
        intake["evidence"][0] = source("issue", "issue", json.dumps({"id": self.packet["id"], "revision": 7}), revision=7)
        snapshot = json.loads(intake["evidence"][1]["content"])
        snapshot["items"][0]["id"] = self.packet["id"]
        intake["evidence"][1] = source("dependencies", "dependencies", json.dumps(snapshot, sort_keys=True, separators=(",", ":")), revision=7)
        intake["readiness"]["source_sha256"] = intake["evidence"][1]["sha256"]
        intake["evidence"][3] = source("file", "file", "value = 1", "src/change.py")
        policy["repository_url"] = URL
        if human_gate:
            intake["human_gates"] = [gate_fixture(intake, kind="input", owner="operator", stage="before", action="local_execute")]
            if signed_human:
                answer = {"gate_id": "human-review", "response": "Approved this exact bounded input."}
                intake["evidence"].append(source("human-answer:human-review", "issue", json.dumps(answer, sort_keys=True, separators=(",", ":")), revision=7))
        if publication_gate:
            intake["human_gates"].append(gate_fixture(intake, id="publish-taste", kind="taste", owner="operator", stage="before", action="draft_pr"))
        primary = assessment_fixture(intake, policy)
        challenge = assessment_fixture(intake, policy, "challenge")
        decision = atlas_routing.decide_route(intake, policy, primary, challenge, now=NOW)
        self.assertTrue(decision["route_ready"], decision)
        self.fixture.registry["policy_sha256"] = canonical_digest(policy)
        self.fixture.update_trust()
        receipts = []
        if signed_human:
            gate = intake["human_gates"][0]
            receipt = {"gate_id": gate["id"], "decision": "accepted", "response": "Approved this exact bounded input.", "grant": {}}
            context = {"issue_id": self.packet["id"], "issue_revision": self.packet["revision"],
                       "worker_packet_sha256": worker.digest(self.packet), "candidate_sha": None, "action": "local_execute", "policy_sha256": canonical_digest(policy)}
            receipt["grant"] = self.fixture.grant("human_gate", gate_bindings(gate, receipt, context), grant_id="synthetic-input-grant")
            receipts.append(receipt)
        provenance = {"intake": intake, "policy": policy, "assessment": primary, "challenge": challenge,
                      "decision": decision, "human_receipts": receipts}
        self.worker.config = resolve_routed_config(self.config, provenance, now=NOW)
        from atlas_dispatch import _routed_budget
        store, lineage, _, _ = _routed_budget(self.worker.config)
        with store.locked():
            store.write("budget", lineage, {"schema_version": 1, "lineage": lineage, "model_calls": 2,
                "seconds_reserved": 360, "tokens_observed": 100, "usage_complete": True})
        return provenance

    def test_direct_execute_rejects_plain_forged_and_wrong_action_grants_before_effects(self):
        valid = self.grant()
        forged = deepcopy(valid)
        forged["payload"]["bindings"]["packet_sha256"] = "0" * 64
        unknown = deepcopy(valid)
        unknown["issuer"] = "model-invented-issuer"
        typed = self.grant(schema_version=True)
        wrong_action = self.fixture.grant("draft_pr", self.worker.authorization_bindings(self.packet, "local_execute"))
        for envelope in (None, {"approval_record": "I approve", "packet_sha256": worker.digest(self.packet)}, forged, unknown, typed, wrong_action):
            with self.subTest(envelope=envelope is None), self.assertRaises(worker.WorkerBlocked):
                self.worker.execute(self.packet, envelope)
        self.assertEqual(self.runner.calls, [])
        self.assertEqual(self.provider.calls, [])
        self.assertFalse((self.runtime / "state").exists())

    def test_valid_signature_prepares_but_does_not_infer_human_or_board_completion(self):
        prepared = self.prepare()
        self.assertEqual(prepared["state"], "prepared")
        self.assertFalse(prepared["completion"])
        self.assertEqual(self.client.writes, [])

    def test_exact_repository_packet_config_and_runtime_bindings_cannot_be_replayed(self):
        for field, value in (("repository_url", URL + "-different"), ("packet_sha256", "1" * 64),
                             ("effective_config_sha256", "2" * 64), ("runtime_dir", str(self.root)),
                             ("base_commit", "3" * 40), ("base_branch", "main")):
            with self.subTest(field=field), self.assertRaises(worker.WorkerBlocked):
                self.worker.execute(self.packet, self.grant(**{field: value}))
        self.assertEqual(self.runner.calls, [])
        self.assertFalse((self.runtime / "state").exists())

    def test_revocation_after_inspection_is_rechecked_before_claim(self):
        original = self.provider.inspect
        def inspect(*args, **kwargs):
            result = original(*args, **kwargs)
            self.revoke()
            return result
        self.provider.inspect = inspect
        with self.assertRaises(worker.WorkerBlocked):
            self.prepare()
        self.assertFalse((self.runtime / "state").exists())
        self.assertFalse(any(argv[:2] == ["codex", "exec"] and "--help" not in argv for argv, _ in self.runner.calls))

    def test_revocation_between_roles_prevents_implementation(self):
        original = self.runner
        def run(argv, **kwargs):
            result = original(argv, **kwargs)
            if argv[:2] == ["codex", "exec"] and "--help" not in argv:
                self.revoke()
            return result
        self.worker.runner = run
        with self.assertRaises(worker.WorkerBlocked):
            self.prepare()
        phases = [json.loads(kwargs["input"].split("\n", 1)[1])["role"] for argv, kwargs in original.calls if argv[:2] == ["codex", "exec"] and "--help" not in argv]
        self.assertEqual(phases, ["planning"])
        self.assertEqual(original.head, BASE)

    def test_config_change_between_roles_invalidates_existing_grant(self):
        original = self.runner
        def run(argv, **kwargs):
            result = original(argv, **kwargs)
            if argv[:2] == ["codex", "exec"] and "--help" not in argv:
                self.worker.config = replace(self.config, roles={role: RoleSettings("gpt-5.6-terra", "medium", "changed") for role in ROLES})
            return result
        self.worker.runner = run
        with self.assertRaises(worker.WorkerBlocked):
            self.prepare()
        self.assertEqual(original.head, BASE)

    def test_publication_requires_its_own_exact_candidate_and_evidence_grant(self):
        execute_grant = self.grant()
        self.worker.execute(self.packet, execute_grant)
        for envelope in (execute_grant, self.grant("draft_pr", candidate_sha="c" * 40), self.grant("draft_pr", evidence_sha256="0" * 64)):
            with self.assertRaises(worker.WorkerBlocked):
                self.worker.publish(self.packet, envelope)
        self.assertEqual(self.client.writes, [])
        result = self.worker.publish(self.packet, self.grant("draft_pr"))
        self.assertEqual(result["state"], "pr_open")
        self.assertFalse(result["completion"])
        self.assertEqual(len(self.client.writes), 1)

    def test_publication_revoked_during_shared_throttle_wait_never_pushes(self):
        self.prepare()
        authorization = self.grant("draft_pr")
        @contextmanager
        def delayed_slot():
            self.revoke()
            yield lambda seconds: None
        self.client.throttle = SimpleNamespace(slot=delayed_slot)
        with self.assertRaises(worker.WorkerBlocked):
            self.worker.publish(self.packet, authorization)
        self.assertEqual(self.client.writes, [])
        self.assertFalse(any("push" in argv for argv, _ in self.runner.calls))

    def test_changed_trusted_policy_invalidates_previously_valid_grant(self):
        authorization = self.grant()
        self.fixture.registry["policy_sha256"] = "e" * 64
        self.fixture.update_trust()
        with self.assertRaises(worker.WorkerBlocked):
            self.worker.execute(self.packet, authorization)
        self.assertEqual(self.runner.calls, [])

    def test_routed_worker_uses_exact_cheaper_role_map_from_signed_recomputed_decision(self):
        self.routed()
        result = self.prepare()
        models = result["effective_configuration"]["models"]
        self.assertEqual(models["implementation"]["model"], "gpt-5.6-terra")
        self.assertEqual(models["review"]["model"], "gpt-5.6-sol")
        self.assertFalse(result["completion"])

    def test_routed_worker_cannot_override_a_role_or_self_assert_a_different_decision(self):
        self.routed()
        authorization = self.grant()
        original = self.worker.config
        self.worker.config = replace(original, roles={**original.roles, "review": RoleSettings("gpt-5.6-luna", "low", "forged")})
        with self.assertRaises(ValueError):
            self.worker.execute(self.packet, authorization)
        self.worker.config = original
        self.worker.config.routing["decision"]["models"]["review"] = {"model": "gpt-5.6-luna", "reasoning": "low"}
        with self.assertRaises(ValueError):
            self.worker.execute(self.packet, authorization)
        self.assertEqual(self.runner.calls, [])

    def test_synthesized_route_without_actual_dispatcher_transport_cannot_execute(self):
        self.routed()
        authorization = self.grant()
        self.transport_patcher.stop()
        with self.assertRaises(RuntimeError):
            self.worker.execute(self.packet, authorization)
        self.assertEqual(self.runner.calls, [])
        self.assertFalse((self.runtime / "state").exists())

    def test_cli_missing_transport_receipt_returns_structured_block_before_authentication(self):
        self.routed()
        authorization = self.grant()
        self.transport_patcher.stop()
        packet = self.root / "packet.json"
        packet.write_text(json.dumps(self.packet))
        grant = self.root / "grant.json"
        grant.write_text(json.dumps(authorization))
        output = io.StringIO()
        with mock.patch.object(worker, "load_runtime_config", return_value=self.worker.config), mock.patch.object(worker, "AzureWorker", return_value=self.worker), mock.patch("atlas_azure_devops.azure_cli_headers", side_effect=AssertionError("blocked route authenticated")), redirect_stderr(output):
            result = worker.main(["--config", str(self.root / "config.json"), "--runtime-dir", str(self.runtime),
                                  "--packet", str(packet), "--authorization", str(grant), "--execute"])
        self.assertEqual(result, 2)
        self.assertEqual(json.loads(output.getvalue())["state"], "blocked")
        self.assertFalse(json.loads(output.getvalue())["completion"])

    def test_missing_actual_role_usage_stops_after_one_model_call(self):
        from atlas_dispatch import budget_report
        self.routed()
        self.runner.usage_tokens = None
        with self.assertRaisesRegex(worker.WorkerBlocked, "usage is missing"):
            self.prepare()
        budget = budget_report(self.worker.config)
        self.assertFalse(budget["usage_complete"])
        self.assertEqual(budget["model_calls"], 3)  # Two assessed calls plus planning.
        self.assertEqual(self.runner.head, BASE)

    def test_observed_token_overrun_blocks_further_model_calls_and_completion(self):
        self.routed()
        self.runner.usage_tokens = 100001
        with self.assertRaisesRegex(worker.WorkerBlocked, "observed budget"):
            self.prepare()
        phases = [argv for argv, _ in self.runner.calls if argv[:2] == ["codex", "exec"] and "--help" not in argv]
        self.assertEqual(len(phases), 1)
        self.assertEqual(self.runner.head, BASE)

    def test_shared_dispatch_call_budget_prevents_overspending_after_preparation_starts(self):
        from atlas_dispatch import _routed_budget, budget_report
        self.routed()
        store, lineage, _, _ = _routed_budget(self.worker.config)
        budget = budget_report(self.worker.config)
        budget["model_calls"] = 8
        with store.locked():
            store.write("budget", lineage, budget)
        with self.assertRaisesRegex(RuntimeError, "call budget"):
            self.prepare()
        self.assertEqual(budget_report(self.worker.config)["model_calls"], 10)
        self.assertEqual(self.worker.store.get(worker.digest(self.packet))["state"], "blocked")

    def test_signed_execution_grant_does_not_resolve_a_required_human_input(self):
        self.routed(human_gate=True)
        with self.assertRaisesRegex(worker.WorkerBlocked, "human input"):
            self.prepare()
        self.assertEqual(self.runner.calls, [])
        self.assertFalse((self.runtime / "state").exists())

    def test_authenticated_human_input_allows_the_separately_authorized_routed_worker(self):
        self.routed(human_gate=True, signed_human=True)
        result = self.prepare()
        self.assertEqual(result["state"], "prepared")
        self.assertFalse(result["completion"])
        for argv, kwargs in self.runner.calls:
            if argv[:2] == ["codex", "exec"] and "--help" not in argv:
                payload = json.loads(kwargs["input"].split("\n", 1)[1])
                self.assertEqual(payload["verified_human_inputs"][0]["response"], "Approved this exact bounded input.")
                self.assertEqual(payload["verified_human_inputs"][0]["owner"], "operator")

    def test_altered_human_answer_cannot_be_forwarded_despite_new_execution_grant(self):
        self.routed(human_gate=True, signed_human=True)
        self.worker.config.routing["human_receipts"][0]["response"] = "Forged change of product intent."
        with self.assertRaisesRegex(worker.WorkerBlocked, "human input"):
            self.prepare()
        self.assertEqual(self.runner.calls, [])

    def test_prepared_candidate_waits_for_signed_taste_receipt_then_publishes_unchanged_config(self):
        from atlas_human_gates import gate_bindings
        self.routed(publication_gate=True)
        prepared = self.prepare()
        original_config = worker.digest(self.worker.config.report())
        with self.assertRaisesRegex(worker.WorkerBlocked, "human input"):
            self.worker.publish(self.packet, self.grant("draft_pr"))
        self.assertEqual(self.client.writes, [])
        row = self.worker.publication_gate_contexts(self.packet, prepared["candidate_sha"])[0]
        gate = {**row["gate"], "artifact_sha256": "f" * 64}
        receipt = {"gate_id": gate["id"], "decision": "accepted", "response": "I tested and accept this exact rendered candidate.", "grant": {}}
        receipt["grant"] = self.fixture.grant("human_gate", gate_bindings(gate, receipt, row["context"]), grant_id="synthetic-taste")
        receipts = [receipt]
        with self.assertRaises(worker.WorkerBlocked):
            self.worker.publish(self.packet, self.grant("draft_pr"), human_receipts=receipts)
        result = self.worker.publish(self.packet, self.grant("draft_pr", human_receipts=receipts), human_receipts=receipts)
        self.assertEqual(result["state"], "pr_open")
        self.assertFalse(result["completion"])
        self.assertEqual(worker.digest(self.worker.config.report()), original_config)
        self.assertEqual(len(self.client.writes), 1)

    def test_post_preparation_receipt_cannot_replace_template_owner_or_candidate(self):
        from atlas_human_gates import gate_bindings
        self.routed(publication_gate=True)
        self.prepare()
        row = self.worker.publication_gate_contexts(self.packet, HEAD)[0]
        for changed in ({"owner": "someone-else"}, {"candidate_sha": REPAIR}):
            gate = {**row["gate"], **changed}
            receipt = {"gate_id": gate["id"], "decision": "accepted", "response": "Wrong reviewed subject.", "grant": {}}
            context = {**row["context"], "candidate_sha": gate["candidate_sha"]}
            receipt["grant"] = self.fixture.grant("human_gate", gate_bindings(gate, receipt, context), grant_id="synthetic-wrong-taste")
            receipts = [receipt]
            with self.subTest(changed=changed), self.assertRaisesRegex(worker.WorkerBlocked, "human input"):
                self.worker.publish(self.packet, self.grant("draft_pr", human_receipts=receipts), human_receipts=receipts)
        self.assertEqual(self.client.writes, [])

    def test_human_wait_can_resume_two_days_after_expired_execution_grant_with_fresh_publication_authority(self):
        from atlas_human_gates import gate_bindings
        self.routed(publication_gate=True)
        self.prepare()
        later = NOW + 172800
        self.worker.clock = lambda: later
        self.fixture.now = int(later)
        fresh = datetime.fromtimestamp(later, timezone.utc).isoformat()
        self.provider.snapshot_overrides["observed_at"] = fresh
        self.client.observed_at = fresh
        row = self.worker.publication_gate_contexts(self.packet, HEAD)[0]
        receipt = {"gate_id": row["gate"]["id"], "decision": "accepted", "response": "Human review completed after the wait.", "grant": {}}
        receipt["grant"] = self.fixture.grant("human_gate", gate_bindings(row["gate"], receipt, row["context"]), grant_id="later-human")
        receipts = [receipt]
        result = self.worker.publish(self.packet, self.grant("draft_pr", human_receipts=receipts), human_receipts=receipts)
        self.assertEqual(result["state"], "pr_open")
        self.assertFalse(result["completion"])
        model_calls = [argv for argv, _ in self.runner.calls if argv[:2] == ["codex", "exec"] and "--help" not in argv]
        self.assertEqual(len(model_calls), 3)

    def test_historical_routing_does_not_waive_fresh_board_reads(self):
        self.routed()
        self.prepare()
        self.worker.clock = lambda: NOW + 172800
        self.fixture.now = int(NOW + 172800)
        with self.assertRaisesRegex(worker.WorkerBlocked, "stale"):
            self.worker.publish(self.packet, self.grant("draft_pr"))
        self.assertEqual(self.client.writes, [])

    def test_historical_prepared_time_and_provenance_remain_bound_to_current_grant(self):
        self.routed()
        self.prepare()
        self.worker.clock = lambda: NOW + 172800
        self.fixture.now = int(NOW + 172800)
        authorization = self.grant("draft_pr")
        claim = self.worker._publication_claim(self.packet)
        self.worker.store.update(worker.digest(self.packet), claim["owner"], prepared_at=NOW + 1)
        with self.assertRaises(worker.WorkerBlocked):
            self.worker.publish(self.packet, authorization)
        self.assertEqual(self.client.writes, [])

    def test_duplicate_or_nonfinite_cli_authority_fields_are_rejected_inertly(self):
        path = self.root / "untrusted.json"
        for text in ('{"schema":1,"schema":1}', '{"schema":NaN}'):
            path.write_text(text)
            with self.assertRaises(worker.WorkerBlocked):
                worker._load(path)
        self.assertEqual(self.runner.calls, [])


if __name__ == "__main__":
    unittest.main()
