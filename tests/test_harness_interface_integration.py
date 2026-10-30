"""Real MCP/service/lifecycle joins against a canonical, provider-faked runtime.

The runtime and registry live under the real owned repo/home boundary. No
production method is patched and no account HOME, credentials, provider state,
or live runtime is used. The fake provider rejects every mutating command.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import selectors
import shutil
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "local-automation-runtime"
TERMINAL = {"stopped", "failed", "timed_out", "cancelled"}

FAKE_PROVIDER = '''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
args=sys.argv[1:]
name=Path(sys.argv[0]).name
allowed=name=="gh" and (args[:2] in (["issue","list"],["pr","list"],["repo","view"]))
with open(os.environ["HARNESS_CANARY_AUDIT"],"a",encoding="utf-8") as audit:
    audit.write(json.dumps({"executable":name,"argv":args,"allowed":allowed})+"\\n")
if not allowed:
    print("qualification fixture rejected unexpected command",file=sys.stderr)
    sys.exit(97)
print(json.dumps({"defaultBranchRef":{"name":"main"}} if args[:2]==["repo","view"] else []))
'''


class MCPProcess:
    def __init__(self, registry: Path, environment: dict[str, str], stderr: Path):
        self.error_output = stderr.open("wb")
        self.process = subprocess.Popen(
            [sys.executable, str(ROOT / "scripts/harness_mcp.py"), "--registry", str(registry)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.error_output,
            cwd=ROOT, env=environment,
        )
        self.counter = 0
        self.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "unmocked-qualification-canary", "version": "1.0"}})
        self.notify("notifications/initialized")

    def notify(self, method: str):
        assert self.process.stdin is not None
        self.process.stdin.write((json.dumps({"jsonrpc": "2.0", "method": method}) + "\n").encode())
        self.process.stdin.flush()

    def request(self, method: str, params: dict, timeout: float = 15) -> dict:
        self.counter += 1
        assert self.process.stdin is not None and self.process.stdout is not None
        self.process.stdin.write((json.dumps({"jsonrpc": "2.0", "id": self.counter, "method": method, "params": params}) + "\n").encode())
        self.process.stdin.flush()
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            if not selector.select(timeout):
                raise AssertionError("Actual harness MCP process did not return within the bounded canary wait.")
        line = self.process.stdout.readline()
        if not line:
            raise AssertionError(f"Actual harness MCP process closed its output; returncode={self.process.poll()}")
        response = json.loads(line)
        if response.get("id") != self.counter or "error" in response:
            raise AssertionError(f"Unexpected MCP protocol response: {response}")
        return response["result"]

    def tool(self, name: str, arguments: dict | None = None, timeout: float = 15, *, allow_blocked: bool = False) -> dict:
        result = self.request("tools/call", {"name": name, "arguments": arguments or {}}, timeout)
        if result.get("isError") and not (allow_blocked and result.get("structuredContent", {}).get("status") == "blocked"):
            raise AssertionError(f"Actual {name} failed: {result.get('structuredContent')}")
        return result["structuredContent"]

    def close(self):
        if self.process.stdin is not None and not self.process.stdin.closed:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=5)
        if self.process.stdout is not None:
            self.process.stdout.close()
        self.error_output.close()


class HarnessInterfaceIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = Path(tempfile.mkdtemp(prefix=".harness-interface-canary-", dir=ROOT)).resolve()
        self.runtime = self.fixture / "runtime"
        shutil.copytree(TEMPLATE, self.runtime, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "jobs", "logs", "config.env", "repos.txt", "projects.txt", "codex-home", "authority", ".azure-api", ".azure-dispatch", ".azure-supervisor", "approval-inbox", "worktrees"))
        (self.runtime / "config.env").write_text("AGENT_GITHUB_THROTTLE=false\nAGENT_BASE_BRANCH=main\n", encoding="utf-8")
        (self.runtime / "repos.txt").write_text("fixture/no-work\n", encoding="utf-8")
        (self.runtime / "required-checks.json").write_text("{}\n", encoding="utf-8")
        config = self.fixture / "runtime.json"
        config.write_text(json.dumps({
            "schema_version": 1, "provider": "github", "runtime_dir": str(self.runtime),
            "repository": {"name": "no-work", "url": "https://github.com/fixture/no-work", "base_branch": "main"},
            "capabilities": ["read", "local_execute"],
            "models": {"default": {"model": "qualification-model-never-invoked", "reasoning": "low"}},
            "sandbox": "workspace-write", "approval_policy": "on-request",
        }), encoding="utf-8")
        self.registry = self.fixture / "harness.json"
        self.registry.write_text(json.dumps({"version": 1, "runtimes": [{"id": "qualification", "provider": "github", "runtime_dir": str(self.runtime), "config": str(config)}], "installations": []}), encoding="utf-8")
        binaries = self.fixture / "bin"
        binaries.mkdir()
        for name in ("gh", "codex", "podman", "git", "curl", "wget", "ssh"):
            path = binaries / name
            path.write_text(FAKE_PROVIDER, encoding="utf-8")
            path.chmod(0o755)
        self.audit = self.fixture / "provider-audit.jsonl"
        self.environment = {key: value for key, value in os.environ.items() if not key.startswith(("AGENT_", "TEAMS_"))}
        self.environment.update(PATH=str(binaries) + os.pathsep + os.environ.get("PATH", ""), HARNESS_CANARY_AUDIT=str(self.audit), PYTHONDONTWRITEBYTECODE="1")
        self.clients: list[MCPProcess] = []
        self.run_id: str | None = None
        self.clean_terminal = False

    def client(self) -> MCPProcess:
        client = MCPProcess(self.registry, self.environment, self.fixture / f"mcp-{len(self.clients)}.stderr")
        self.clients.append(client)
        return client

    def snapshot(self) -> dict[str, str]:
        return {path.relative_to(self.fixture).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.fixture.rglob("*") if path.is_file()}

    def tearDown(self):
        cleanup_error = None
        if self.run_id and not self.clean_terminal:
            try:
                client = self.client()
                client.tool("harness_cancel", {"run_id": self.run_id})
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    observed = client.tool("harness_wait", {"run_id": self.run_id, "timeout_seconds": 1})
                    if observed["run"]["status"] in TERMINAL:
                        self.clean_terminal = True
                        break
                    time.sleep(0.05)
                if not self.clean_terminal:
                    cleanup_error = "Canary run did not reach a terminal record after cancellation."
            except Exception as exc:
                cleanup_error = str(exc)
        for client in self.clients:
            client.close()
        if cleanup_error:
            self.fail(f"{cleanup_error} Isolated evidence preserved at {self.fixture}")
        shutil.rmtree(self.fixture)

    def test_actual_mcp_preparation_execution_and_reconnection_with_no_tasks(self):
        first = self.client()
        discovered = first.tool("harness_discover")
        self.assertTrue(discovered["runtimes"][0]["available"])
        self.assertEqual(discovered["runtimes"][0]["id"], "qualification")
        before = self.snapshot()
        prepared = first.tool("harness_prepare", {"runtime_id": "qualification", "options": {"max_minutes": 1}})
        self.assertEqual(prepared["status"], "prepared", prepared.get("blockers"))
        self.assertEqual(before, self.snapshot(), "Actual preparation must leave the isolated fixture unchanged.")
        self.assertFalse(self.audit.exists(), "Preparation must not query even the fake provider.")
        proposal = prepared["proposal"]
        self.assertEqual(proposal["targets"], ["fixture/no-work"])
        self.assertFalse(proposal["effects"]["worker_execution"])
        self.assertFalse(proposal["effects"]["notifications"])
        self.assertFalse(proposal["required_authorization"]["granted"])
        started = first.tool("harness_start", {
            "runtime_id": "qualification", "proposal_id": prepared["proposal_id"],
            "options": {"max_minutes": 1}, "authorization_ref": "qualification:isolated-no-task-canary",
        })
        self.run_id = started["run_id"]
        self.assertTrue(self.run_id.startswith("run-"))
        self.assertFalse(started["read_only"])
        first.close()
        second = self.client()
        deadline = time.monotonic() + 20
        observed = None
        while time.monotonic() < deadline:
            observed = second.tool("harness_wait", {"run_id": self.run_id, "timeout_seconds": 1})
            if observed["run"]["status"] in TERMINAL:
                self.clean_terminal = True
                break
            time.sleep(0.05)
        self.assertTrue(self.clean_terminal, observed)
        self.assertEqual(observed["run"]["status"], "stopped", observed)
        self.assertEqual(observed["run"]["process_exit_code"], 0)
        self.assertFalse(observed["run"]["accepted_progress"])
        self.assertFalse(observed["run"]["completion"])
        self.assertTrue(observed["read_only"])
        state = self.fixture / "runs" / self.run_id / "status.json"
        self.assertTrue(state.is_file())
        self.assertEqual(json.loads(state.read_text())["proposal_id"], prepared["proposal_id"])
        shifts = list((self.runtime / "jobs").glob("shift-*-status.json"))
        self.assertEqual(len(shifts), 1)
        shift = json.loads(shifts[0].read_text())
        self.assertEqual(shift["state"], "complete")
        self.assertEqual(shift["cycles_completed"], 1)
        self.assertEqual(shift["last_returncode"], 0)
        summaries = list((self.runtime / "jobs").glob("unattended-*/unattended-summary.json"))
        self.assertEqual(len(summaries), 1)
        self.assertTrue(self.audit.is_file(), "The actual runtime cycle must have reached fake provider reads.")
        commands = [json.loads(line) for line in self.audit.read_text().splitlines()]
        self.assertTrue(commands)
        self.assertTrue(all(command["allowed"] and command["executable"] == "gh" for command in commands), commands)
        self.assertTrue(any(command["argv"][:2] == ["issue", "list"] for command in commands))
        self.assertTrue(any(command["argv"][:2] == ["pr", "list"] for command in commands))
        self.assertFalse((self.fixture / "runs/qualification.lock").exists())
        inspected = second.tool("harness_inspect", {"runtime_id": "qualification"})
        self.assertEqual(inspected["current_work"], [])
        self.assertTrue(any(item["state"] == "complete" for item in inspected["evidence"]))
        self.assertEqual(inspected["validation"]["status"], "unverified")
        self.assertEqual((self.runtime / "config.env").read_text(), "AGENT_GITHUB_THROTTLE=false\nAGENT_BASE_BRANCH=main\n")
        for log in self.fixture.glob("mcp-*.stderr"):
            self.assertEqual(log.read_bytes(), b"")

    def test_actual_shift_and_unattended_parsers_preserve_prepared_effect_options(self):
        # Compile the real parser functions in an isolated namespace, supplying
        # inert default readers so this check cannot load account shell config.
        common = SimpleNamespace(RUNTIME_DIR=self.runtime, config_int=lambda name, default: default,
                                 config_value=lambda name, default="": default, read_config=lambda: {})

        def functions(name, wanted):
            tree = ast.parse((TEMPLATE / name).read_text())
            body = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
            namespace = {"argparse": argparse, "common": common, "__doc__": "isolated actual parser", "DEFAULT_PROJECT_ITEM_LIMIT": 500, "APPROVED_LABEL": "agent:review-approved"}
            exec(compile(ast.Module(body=body, type_ignores=[]), "<actual-runtime-parser>", "exec"), namespace)
            return namespace

        shift = functions("atlas-agent-shift", {"build_parser", "clean_passthrough_args", "build_unattended_command"})
        inner = functions("atlas-agent-unattended", {"build_parser"})
        client = self.client()
        for options in ({}, {"publish": True}, {"apply": True}, {"review_apply": True}, {"publish": True, "apply": True, "review_apply": True}):
            with self.subTest(options=options):
                result = client.tool("harness_prepare", {"runtime_id": "qualification", "options": options}, allow_blocked=True)
                # Publish cases are correctly blocked by this fixture's absent
                # draft_pr capability; their inert argv can still be parsed.
                argv = result["proposal"]["argv"]
                outer, passthrough = shift["build_parser"]().parse_known_args(argv[1:])
                command = shift["build_unattended_command"](passthrough)
                parsed = inner["build_parser"]().parse_args(command[1:])
                self.assertEqual(outer.cycles, 1)
                self.assertEqual(outer.project_reconcile_every, 0)
                self.assertEqual(parsed.project_reconcile_every, 0)
                self.assertEqual(parsed.cycles, 1)
                self.assertFalse(parsed.worker_notifications)
                self.assertEqual(parsed.execution_targets_file, str(self.runtime / "repos.txt"))
                self.assertEqual(parsed.publish, options.get("publish", False))
                self.assertEqual(parsed.apply, options.get("apply", False))
                self.assertEqual(parsed.review_apply, options.get("review_apply", False))
                self.assertFalse(parsed.merge)
                self.assertFalse(parsed.close_issues)
                self.assertFalse(parsed.post_cycle_summary)
                self.assertFalse(parsed.post_triage_teams_per_repo)
                self.assertEqual(parsed.cleanup_mode, "off")
        self.assertFalse(self.audit.exists())


if __name__ == "__main__":
    unittest.main()
