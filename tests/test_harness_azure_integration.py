"""Actual MCP-to-Azure joins using an isolated runtime and inert inspection.

The fixture has no credentials or enabled model/write capabilities. Every cloud,
model, Git and shell-network executable is replaced by a rejecting audit stub.
These tests establish interface/lifecycle behavior, not live Azure qualification.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from harness_execution import canonical_code_files  # noqa: E402
from test_harness_interface_integration import MCPProcess, TERMINAL  # noqa: E402


REJECT_EXTERNAL = '''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
with open(os.environ["AZURE_INTERFACE_TEST_AUDIT"],"a",encoding="utf-8") as output:
    output.write(json.dumps({"executable":Path(sys.argv[0]).name,"argv":sys.argv[1:]})+"\\n")
print("isolated Azure interface fixture refuses external execution",file=sys.stderr)
sys.exit(97)
'''


class HarnessAzureInterfaceIntegrationTests(unittest.TestCase):
    def setUp(self):
        home = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
        if home not in ROOT.resolve().parents:
            self.skipTest("Actual runtime canary needs a checkout under the current passwd home.")
        self.fixture = Path(tempfile.mkdtemp(prefix=".azure-interface-canary-", dir=ROOT)).resolve()
        self.runtime = self.fixture / "runtime"
        self.runtime.mkdir()
        for name in canonical_code_files(ROOT):
            shutil.copy2(ROOT / "templates/local-automation-runtime" / name, self.runtime / name)
        self.config = self.fixture / "remote.json"
        self.configuration = {
            "schema_version": 1, "provider": "azure-devops", "runtime_dir": str(self.runtime),
            "repository": {"organization": "FixtureOrg", "project": "FixtureProject", "name": "FixtureRepo",
                           "url": "https://dev.azure.com/FixtureOrg/FixtureProject/_git/FixtureRepo", "base_branch": "main"},
            "capabilities": ["read"], "sandbox": "workspace-write", "approval_policy": "on-request",
        }
        self.config.write_text(json.dumps(self.configuration), encoding="utf-8")
        self.registry = self.fixture / "harness.json"
        self.registration = {"id": "azure-fixture", "provider": "azure-devops", "runtime_dir": str(self.runtime), "config": str(self.config)}
        self.registry.write_text(json.dumps({"version": 1, "runtimes": [self.registration], "installations": []}), encoding="utf-8")
        binaries = self.fixture / "bin"
        binaries.mkdir()
        for name in ("az", "gh", "codex", "podman", "git", "curl", "wget", "ssh"):
            program = binaries / name
            program.write_text(REJECT_EXTERNAL, encoding="utf-8")
            program.chmod(0o755)
        self.audit = self.fixture / "external-audit.jsonl"
        self.environment = {key: value for key, value in os.environ.items() if not key.startswith(("AGENT_", "TEAMS_"))}
        self.environment.update(PATH=str(binaries) + os.pathsep + os.environ.get("PATH", ""),
                                AZURE_INTERFACE_TEST_AUDIT=str(self.audit), PYTHONDONTWRITEBYTECODE="1")
        self.clients = []
        self.run_ids = []

    def client(self):
        client = MCPProcess(self.registry, self.environment, self.fixture / f"mcp-{len(self.clients)}.stderr")
        self.clients.append(client)
        return client

    def snapshot(self):
        return {str(path.relative_to(self.fixture)): (path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
                for path in self.fixture.rglob("*") if path.is_file()}

    def raw_tool(self, client, name, arguments):
        return client.request("tools/call", {"name": name, "arguments": arguments})

    def terminal(self, client, run_id):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            result = client.tool("harness_wait", {"run_id": run_id, "timeout_seconds": 1})
            if result["run"]["status"] in TERMINAL:
                return result
            time.sleep(0.05)
        self.fail("The isolated Azure run did not reach a terminal record.")

    def tearDown(self):
        problems = []
        for run_id in self.run_ids:
            try:
                client = self.client()
                observed = client.tool("harness_wait", {"run_id": run_id})
                if observed["run"]["status"] not in TERMINAL:
                    client.tool("harness_cancel", {"run_id": run_id})
                    self.terminal(client, run_id)
            except Exception as exc:
                problems.append(type(exc).__name__)
        for client in self.clients:
            client.close()
        if problems:
            self.fail(f"Fixture cleanup could not verify terminal state; retained at {self.fixture}: {problems}")
        shutil.rmtree(self.fixture)

    def test_real_stdio_azure_read_only_cycle_survives_reconnect_and_projects_result(self):
        first = self.client()
        discovered = first.tool("harness_discover")
        self.assertEqual(discovered["runtimes"][0]["provider"], "azure-devops")
        self.assertTrue(discovered["runtimes"][0]["available"])
        self.assertEqual(discovered["runtimes"][0]["capabilities"], ["read"])
        inspected = first.tool("harness_inspect", {"runtime_id": "azure-fixture"})
        self.assertEqual(inspected["models"], {}, "Read-only Azure setup must not invent a model assignment.")
        before = self.snapshot()
        options = {"ids": [17], "max_minutes": 1}
        prepared = first.tool("harness_prepare", {"runtime_id": "azure-fixture", "options": options})
        self.assertEqual(prepared["status"], "prepared", prepared.get("blockers"))
        self.assertEqual(before, self.snapshot())
        self.assertFalse(self.audit.exists())
        proposal = prepared["proposal"]
        self.assertEqual(proposal["operation"], "azure-inspect")
        self.assertEqual(proposal["required_capabilities"], ["read"])
        self.assertFalse(proposal["effects"]["provider_read"])
        self.assertFalse(proposal["effects"]["remote_comments"])
        self.assertFalse(proposal["required_authorization"]["granted"])
        started = first.tool("harness_start", {
            "runtime_id": "azure-fixture", "operation": "azure-inspect", "proposal_id": prepared["proposal_id"],
            "options": options, "authorization_ref": "qualification:isolated-azure-inspector",
        })
        run_id = started["run_id"]
        self.run_ids.append(run_id)
        first.close()
        observed = self.terminal(self.client(), run_id)
        run = observed["run"]
        self.assertEqual(run["status"], "stopped", run)
        self.assertEqual(run["process_exit_code"], 0)
        self.assertFalse(run["completion"])
        self.assertFalse(run["accepted_progress"])
        result = run["operation_result"]
        self.assertEqual(result["operation"], "azure-inspect")
        self.assertEqual(result["inspection_mode"], "dry-run")
        self.assertFalse(result["complete"])
        self.assertFalse(result["dependency_complete"])
        self.assertEqual(result["eligible_count"], 0)
        self.assertFalse(result["accepted_progress"])
        self.assertFalse(result["completion"])
        self.assertFalse(self.audit.exists(), "An inert Azure inspection must invoke no provider, model or network CLI.")
        self.assertFalse((self.fixture / "runs" / "azure-fixture.lock").exists())
        self.assertNotIn("worker-output.log", json.dumps(result), "MCP returns a projection, not raw output.")

    def test_changed_offline_input_invalidates_proposal_before_state_or_provider_effects(self):
        client = self.client()
        snapshot = self.fixture / "snapshot.json"
        snapshot.write_text(json.dumps({"complete": False, "items": []}), encoding="utf-8")
        options = {"ids": [17], "snapshot": str(snapshot)}
        prepared = client.tool("harness_prepare", {"runtime_id": "azure-fixture", "operation": "azure-inspect", "options": options})
        self.assertEqual(prepared["status"], "prepared")
        snapshot.write_text(json.dumps({"complete": False, "items": [], "changed": True}), encoding="utf-8")
        before = self.snapshot()
        started = self.raw_tool(client, "harness_start", {
            "runtime_id": "azure-fixture", "operation": "azure-inspect", "proposal_id": prepared["proposal_id"],
            "options": options, "authorization_ref": "qualification:stale-input-countercase",
        })
        self.assertTrue(started["isError"])
        self.assertEqual(started["structuredContent"]["error"]["code"], "stale_proposal")
        self.assertFalse((self.fixture / "runs").exists())
        self.assertFalse(self.audit.exists())
        self.assertEqual(before, self.snapshot())

    def test_wrong_provider_never_falls_back_and_missing_write_grant_cannot_start(self):
        self.registry.write_text(json.dumps({"version": 1, "runtimes": [self.registration, {
            "id": "github-fixture", "provider": "github", "runtime_dir": str(self.runtime),
        }], "installations": []}), encoding="utf-8")
        client = self.client()
        before = self.snapshot()
        mismatch = self.raw_tool(client, "harness_prepare", {
            "runtime_id": "github-fixture", "operation": "azure-inspect", "options": {"ids": [17]},
        })
        self.assertTrue(mismatch["isError"])
        self.assertEqual(mismatch["structuredContent"]["error"]["code"], "provider_mismatch")
        blocked = client.tool("harness_prepare", {
            "runtime_id": "azure-fixture", "operation": "github-cycle",
        }, allow_blocked=True)
        self.assertEqual(blocked["status"], "blocked")
        self.assertIn("unsupported_provider_operation", {item["code"] for item in blocked["blockers"]})
        packet = self.fixture / "not-an-authorized-board-proposal.json"
        packet.write_text('{}', encoding="utf-8")
        # Missing the required grant is rejected at the MCP schema boundary.
        with self.assertRaisesRegex(AssertionError, "-32602"):
            client.request("tools/call", {"name": "harness_prepare", "arguments": {
                "runtime_id": "azure-fixture", "operation": "azure-reconcile", "options": {"packet": str(packet)},
            }})
        with self.assertRaisesRegex(AssertionError, "-32602"):
            client.request("tools/call", {"name": "harness_start", "arguments": {
                "runtime_id": "azure-fixture", "operation": "azure-reconcile", "options": {"packet": str(packet)},
                "proposal_id": "sha256:" + "a" * 64, "authorization_ref": "reference-is-not-a-signed-grant",
            }})
        self.assertFalse((self.fixture / "runs").exists())
        self.assertFalse(self.audit.exists())
        self.assertEqual(before, {key: value for key, value in self.snapshot().items() if key != packet.name})

    def test_actual_configuration_preview_requires_selection_and_saves_no_default_target(self):
        client = self.client()
        remote_id = "preview-" + self.fixture.name.strip(".")
        before = self.snapshot()
        missing = client.tool("harness_configure_remote", {
            "remote_id": remote_id, "provider": "azure-devops",
            "repository_url": "https://dev.azure.com/AnotherFixtureOrg/AnotherFixtureProject",
            "apply": True,
        })
        self.assertEqual(missing["status"], "needs_selection")
        self.assertEqual(set(missing["required_fields"]), {"repository_name", "base_branch"})
        self.assertEqual(missing["changed"], [])
        self.assertFalse(missing["applied"])
        self.assertTrue(missing["read_only"])
        preview = client.tool("harness_configure_remote", {
            "remote_id": remote_id, "provider": "azure-devops",
            "repository_url": "https://dev.azure.com/AnotherFixtureOrg/AnotherFixtureProject",
            "repository_name": "ExplicitlyChosenRepo", "base_branch": "chosen-base",
            "runtime_dir": str(self.runtime),
        })
        self.assertEqual(preview["mode"], "preview")
        self.assertTrue(preview["read_only"])
        self.assertEqual(preview["repository"]["name"], "ExplicitlyChosenRepo")
        self.assertEqual(preview["repository"]["base_branch"], "chosen-base")
        self.assertEqual(before, self.snapshot())
        for change in preview["changed"]:
            if change["category"] == "remote_profile":
                self.assertFalse(Path(change["path"]).exists())
        self.assertFalse(self.audit.exists())

    def test_repository_discovery_uses_only_entered_project_and_returns_choices_without_saving(self):
        azure_config = self.fixture / "azure-cli-config"
        azure_config.mkdir(mode=0o700)
        self.environment["AZURE_CONFIG_DIR"] = str(azure_config)
        az = self.fixture / "bin" / "az"
        az.write_text('''#!/usr/bin/env python3
import json,os,sys
args=sys.argv[1:]
expected="https://dev.azure.com/InputOrg/InputProject/_apis/git/repositories?api-version=7.1"
assert args[:3]==["rest","--method","get"]
assert args[args.index("--url")+1]==expected
assert "login" not in args
with open(os.environ["AZURE_INTERFACE_TEST_AUDIT"],"a",encoding="utf-8") as output:
    output.write(json.dumps({"executable":"az","argv":args})+"\\n")
print(json.dumps([{"name":"ChosenRepo","default_branch":"refs/heads/custom-main","id":"ignored-id"}]))
''', encoding="utf-8")
        client = self.client()
        before = self.snapshot()
        result = client.tool("harness_remote_repositories", {"project_url": "https://dev.azure.com/InputOrg/InputProject"})
        self.assertTrue(result["read_only"])
        self.assertEqual(result["repositories"], [{
            "name": "ChosenRepo", "url": "https://dev.azure.com/InputOrg/InputProject/_git/ChosenRepo",
            "default_branch": "refs/heads/custom-main", "base_branch": "custom-main",
        }])
        self.assertEqual(before, {key: value for key, value in self.snapshot().items() if key != self.audit.name})
        calls = [json.loads(line) for line in self.audit.read_text().splitlines()]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["executable"], "az")
        self.assertEqual(calls[0]["argv"][:3], ["rest", "--method", "get"])
        self.assertFalse((self.fixture / "runs").exists())


if __name__ == "__main__":
    unittest.main()
