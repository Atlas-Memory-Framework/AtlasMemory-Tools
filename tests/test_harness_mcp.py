from __future__ import annotations

import io
import json
import os
import pwd
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import harness_mcp  # noqa: E402


class FakeService:
    def discover(self) -> dict:
        return {"schema_version": "atlas-tools.harness.v1", "read_only": True, "runtimes": [{"id": "test"}]}

    def inspect(self, runtime_id: str) -> dict:
        return {"read_only": True, "runtime_id": runtime_id, "work": [], "status": "unknown"}

    def installation_status(self, target: str, harness: str = "codex") -> dict:
        return {"read_only": True, "target": target, "harness": harness, "status": "stale"}


def request(method: str, params: dict | None = None, request_id: int = 1) -> dict:
    message = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    return message


def initialize(server: harness_mcp.MCPServer, version: str = "2025-06-18") -> dict:
    result = server.handle(request("initialize", {
        "protocolVersion": version,
        "capabilities": {},
        "clientInfo": {"name": "harness-test-client", "version": "1.0.0"},
    }))
    server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
    return result


class MCPAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = harness_mcp.MCPServer(FakeService())

    def test_negotiates_only_supported_protocol_and_declares_only_tools(self) -> None:
        response = initialize(self.server, "2099-01-01")
        self.assertEqual(response["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(response["result"]["capabilities"], {"tools": {"listChanged": False}})
        self.assertIn("harness_discover", response["result"]["instructions"])
        self.assertEqual(self.server.handle(request("ping"))["result"], {})

    def test_initialization_and_notification_are_required(self) -> None:
        self.assertEqual(self.server.handle(request("tools/list"))["error"]["code"], -32002)
        self.assertEqual(self.server.handle(request("initialize", {}))["error"]["code"], -32602)
        initialize(self.server)
        self.assertEqual(self.server.handle(request("initialize", {}))["error"]["code"], -32600)

    def test_tool_catalog_has_accurate_effect_annotations_and_closed_schemas(self) -> None:
        initialize(self.server)
        tools = self.server.handle(request("tools/list"))["result"]["tools"]
        self.assertEqual({tool["name"] for tool in tools}, {
            "harness_discover", "harness_inspect", "harness_installation_status",
            "harness_prepare", "harness_start", "harness_wait", "harness_cancel",
            "harness_remote_repositories", "harness_configure_remote",
        })
        for tool in tools:
            self.assertFalse(tool["inputSchema"]["additionalProperties"])
            mutating = tool["name"] in {"harness_start", "harness_cancel", "harness_configure_remote"}
            self.assertEqual(tool["annotations"]["readOnlyHint"], not mutating)
            self.assertEqual(tool["annotations"]["destructiveHint"], tool["name"] in {"harness_start", "harness_cancel"})
            self.assertEqual(tool["annotations"]["openWorldHint"], tool["name"] in {"harness_start", "harness_remote_repositories"})

    def test_each_tool_has_matching_structured_and_text_results(self) -> None:
        initialize(self.server)
        cases = [
            ("harness_discover", {}),
            ("harness_inspect", {"runtime_id": "test"}),
            ("harness_installation_status", {"target": "/tmp/project"}),
            ("harness_installation_status", {"target": "/tmp/project", "harness": "claude"}),
        ]
        for name, arguments in cases:
            with self.subTest(name=name, arguments=arguments):
                result = self.server.handle(request("tools/call", {"name": name, "arguments": arguments}))["result"]
                self.assertEqual(json.loads(result["content"][0]["text"]), result["structuredContent"])
                self.assertFalse(result["isError"])
                self.assertTrue(result["structuredContent"]["read_only"])

    def test_invalid_tool_inputs_are_protocol_errors(self) -> None:
        initialize(self.server)
        cases = [
            {"name": "execute", "arguments": {}},
            {"name": "harness_discover", "arguments": {"command": "touch anything"}},
            {"name": "harness_inspect", "arguments": {}},
            {"name": "harness_inspect", "arguments": {"runtime_id": ""}},
            {"name": "harness_inspect", "arguments": {"runtime_id": 1}},
            {"name": "harness_inspect", "arguments": []},
            {"name": "harness_inspect", "arguments": {"runtime_id": "x" * 201}},
            {"name": "harness_installation_status", "arguments": {"target": "/tmp/x", "harness": "unknown"}},
            {"name": "harness_discover", "arguments": {}, "unknown": True},
        ]
        for params in cases:
            with self.subTest(params=params):
                self.assertEqual(self.server.handle(request("tools/call", params))["error"]["code"], -32602)
        self.assertEqual(self.server.handle(request("tools/list", {"cursor": "unavailable"}))["error"]["code"], -32602)
        self.assertEqual(self.server.handle(request("unknown"))["error"]["code"], -32601)

    def test_unexpected_errors_never_reveal_exception_or_traceback(self) -> None:
        class BrokenService(FakeService):
            def inspect(self, runtime_id: str) -> dict:
                raise OSError("SECRET_VALUE_123 config.env TOKEN_PASSWORD")

        self.server = harness_mcp.MCPServer(BrokenService())
        initialize(self.server)
        response = self.server.handle(request("tools/call", {"name": "harness_inspect", "arguments": {"runtime_id": "test"}}))
        self.assertTrue(response["result"]["isError"])
        self.assertEqual(response["result"]["structuredContent"]["error"]["code"], "operation_failed")
        self.assertNotIn("SECRET_VALUE", json.dumps(response))
        self.assertNotIn("Traceback", json.dumps(response))

    def test_nested_option_types_bounds_and_unknown_keys_are_rejected_before_routing(self) -> None:
        initialize(self.server)
        invalid = [
            {"max_minutes": True}, {"max_minutes": 0}, {"max_minutes": 31}, {"max_minutes": 1.0},
            {"cycles": False}, {"cycles": 0}, {"cycles": 4}, {"max_per_repo": 3},
            {"publish": 1}, {"apply": "true"}, {"review_apply": None},
            {"command": "touch hidden"}, {"merge": True}, {"argv": []},
            {"nested": {"command": "anything"}}, [], None,
        ]
        with patch("harness_execution.HarnessExecution") as execution, patch("harness_runs.HarnessRuns") as runs:
            for options in invalid:
                for name, required in [
                    ("harness_prepare", {"runtime_id": "test"}),
                    ("harness_start", {"runtime_id": "test", "proposal_id": "sha256:" + "a" * 64, "authorization_ref": "chat:decision"}),
                ]:
                    with self.subTest(options=options, name=name):
                        response = self.server.handle(request("tools/call", {"name": name, "arguments": {**required, "options": options}}))
                        self.assertEqual(response["error"]["code"], -32602)
            execution.assert_not_called()
            runs.assert_not_called()

    def test_prepare_routes_exact_options_and_keeps_authority_ungranted(self) -> None:
        initialize(self.server)
        prepared = {"read_only": True, "status": "prepared", "proposal_id": "sha256:" + "a" * 64,
                    "proposal": {"required_authorization": {"granted": False}}}
        with patch("harness_execution.HarnessExecution") as execution:
            execution.return_value.prepare.return_value = prepared
            options = {"max_minutes": 30, "cycles": 3, "max_per_repo": 2, "publish": False, "apply": True, "review_apply": False}
            response = self.server.handle(request("tools/call", {"name": "harness_prepare", "arguments": {"runtime_id": "test", "options": options}}))
            execution.assert_called_once_with(self.server.service)
            execution.return_value.prepare.assert_called_once_with("test", None, options)
            self.assertEqual(response["result"]["structuredContent"], prepared)
            self.assertFalse(response["result"]["isError"])
            self.assertEqual(json.loads(response["result"]["content"][0]["text"]), prepared)
            self.assertFalse(response["result"]["structuredContent"]["proposal"]["required_authorization"]["granted"])
        with patch("harness_execution.HarnessExecution") as execution:
            execution.return_value.prepare.return_value = prepared
            self.server.handle(request("tools/call", {"name": "harness_prepare", "arguments": {"runtime_id": "test"}}))
            execution.return_value.prepare.assert_called_once_with("test", None, None)

    def test_azure_prepare_and_start_route_the_explicit_named_operation(self) -> None:
        initialize(self.server)
        options = {"ids": [17, 23], "build_ids": [41], "live_read": True, "max_minutes": 2}
        with patch("harness_execution.HarnessExecution") as execution:
            execution.return_value.prepare.return_value = {"status": "prepared", "read_only": True}
            result = self.server.handle(request("tools/call", {"name": "harness_prepare", "arguments": {
                "runtime_id": "azure-test", "operation": "azure-inspect", "options": options,
            }}))
            execution.return_value.prepare.assert_called_once_with("azure-test", "azure-inspect", options)
            self.assertFalse(result["result"]["isError"])
        with patch("harness_runs.HarnessRuns") as runs:
            runs.return_value.start.return_value = {"read_only": False, "run_id": "run-fixture"}
            result = self.server.handle(request("tools/call", {"name": "harness_start", "arguments": {
                "runtime_id": "azure-test", "proposal_id": "sha256:" + "a" * 64,
                "operation": "azure-inspect", "options": options, "authorization_ref": "test:approved-read",
            }}))
            runs.return_value.start.assert_called_once_with(
                "azure-test", "sha256:" + "a" * 64, options, "test:approved-read", operation="azure-inspect",
            )
            self.assertFalse(result["result"]["isError"])

    def test_azure_arrays_and_operation_specific_fields_are_validated_before_routing(self) -> None:
        initialize(self.server)
        invalid = [
            {"ids": []}, {"ids": [True]}, {"ids": [0]}, {"ids": [1.5]}, {"ids": "17"},
            {"ids": [1] * 201}, {"build_ids": [2**31]}, {"live_read": 1},
            {"ids": [17], "publish": True}, {"packet": "/tmp/x.json"},
            {"ids": [17], "command": "arbitrary"},
        ]
        with patch("harness_execution.HarnessExecution") as execution:
            for options in invalid:
                with self.subTest(options=options):
                    reply = self.server.handle(request("tools/call", {"name": "harness_prepare", "arguments": {
                        "runtime_id": "azure-test", "operation": "azure-inspect", "options": options,
                    }}))
                    self.assertEqual(reply["error"]["code"], -32602)
            for operation in ["azure-worker", "azure-publish", "azure-reconcile"]:
                with self.subTest(operation=operation):
                    reply = self.server.handle(request("tools/call", {"name": "harness_prepare", "arguments": {
                        "runtime_id": "azure-test", "operation": operation, "options": {"packet": "/tmp/packet.json"},
                    }}))
                    self.assertEqual(reply["error"]["code"], -32602)
            execution.assert_not_called()

    def test_remote_configuration_and_discovery_route_caller_inputs_without_defaults(self) -> None:
        initialize(self.server)
        arguments = {"remote_id": "chosen-name", "provider": "azure-devops",
                     "repository_url": "https://dev.azure.com/ExampleOrg/ExampleProject",
                     "repository_name": "SelectedRepo", "base_branch": "feature-base", "apply": False,
                     "capabilities": ["read"], "models": {"default": {"model": "reviewed-model", "reasoning": "high"}}}
        with patch("harness_remotes.HarnessRemotes") as remotes:
            remotes.return_value.configure.return_value = {"read_only": True, "mode": "preview", "status": "ready"}
            remotes.return_value.repositories.return_value = {"read_only": True, "repositories": [{"name": "SelectedRepo"}]}
            result = self.server.handle(request("tools/call", {"name": "harness_configure_remote", "arguments": arguments}))
            remotes.return_value.configure.assert_called_once_with(**arguments)
            self.assertTrue(result["result"]["structuredContent"]["read_only"])
            result = self.server.handle(request("tools/call", {"name": "harness_remote_repositories", "arguments": {
                "project_url": arguments["repository_url"],
            }}))
            remotes.return_value.repositories.assert_called_once_with(arguments["repository_url"])
            self.assertFalse(result["result"]["isError"])

    def test_remote_setup_rejects_credentials_unknown_model_fields_and_wrong_types(self) -> None:
        initialize(self.server)
        base = {"remote_id": "chosen", "provider": "azure-devops",
                "repository_url": "https://dev.azure.com/ExampleOrg/ExampleProject/_git/Repo"}
        invalid = [
            {"token": "do-not-persist"}, {"apply": "true"}, {"apply": 1},
            {"capabilities": ["read", "read"]}, {"capabilities": ["root"]}, {"capabilities": "read"},
            {"models": {"default": {"model": "x", "reasoning": "high", "api_key": "forbidden"}}},
            {"models": {"default": {"model": 2, "reasoning": "high"}}},
            {"models": {"default": {"model": "x", "reasoning": "invalid"}}},
            {"models": {"unknown": {"model": "x", "reasoning": "high"}}},
        ]
        with patch("harness_remotes.HarnessRemotes") as remotes:
            for values in invalid:
                with self.subTest(values=values):
                    reply = self.server.handle(request("tools/call", {"name": "harness_configure_remote", "arguments": {**base, **values}}))
                    self.assertEqual(reply["error"]["code"], -32602)
            remotes.assert_not_called()

    def test_lifecycle_tools_route_exact_arguments_and_report_results_without_completion_inference(self) -> None:
        initialize(self.server)
        options = {"max_minutes": 1, "cycles": 1, "publish": False}
        digest = "sha256:" + "b" * 64
        cases = [
            ("harness_start", {"runtime_id": "test", "proposal_id": digest, "options": options, "authorization_ref": "chat:decision"},
             "start", ("test", digest, options, "chat:decision")),
            ("harness_wait", {"run_id": "run-fixture", "cursor": 4, "timeout_seconds": 30}, "wait", ("run-fixture", 4, 30)),
            ("harness_wait", {"run_id": "run-fixture"}, "wait", ("run-fixture", None, 0)),
            ("harness_cancel", {"run_id": "run-fixture"}, "cancel", ("run-fixture",)),
        ]
        for name, arguments, method, expected in cases:
            with self.subTest(name=name), patch("harness_runs.HarnessRuns") as runs:
                self.server.runs = None
                result = {"read_only": name == "harness_wait", "run_id": "run-fixture", "run": {"status": "stopped", "accepted_progress": False, "completion": False}}
                getattr(runs.return_value, method).return_value = result
                response = self.server.handle(request("tools/call", {"name": name, "arguments": arguments}))
                runs.assert_called_once_with(self.server.service)
                getattr(runs.return_value, method).assert_called_once_with(*expected)
                self.assertEqual(response["result"]["structuredContent"], result)
                self.assertFalse(response["result"]["isError"])
                self.assertFalse(response["result"]["structuredContent"]["run"]["completion"])

    def test_lifecycle_input_errors_do_not_reach_run_controller(self) -> None:
        initialize(self.server)
        cases = [
            ("harness_start", {"runtime_id": "test", "proposal_id": "sha256:" + "a" * 64}),
            ("harness_start", {"runtime_id": "test", "proposal_id": "short", "authorization_ref": "chat:x"}),
            ("harness_start", {"runtime_id": "test", "proposal_id": "sha256:" + "a" * 64, "authorization_ref": ""}),
            ("harness_wait", {"run_id": "run-fixture", "cursor": True}),
            ("harness_wait", {"run_id": "run-fixture", "cursor": -1}),
            ("harness_wait", {"run_id": "run-fixture", "timeout_seconds": 31}),
            ("harness_wait", {"run_id": "run-fixture", "timeout_seconds": 0.1}),
            ("harness_cancel", {"run_id": "run-fixture", "pid": 100}),
            ("harness_cancel", {"run_id": ""}),
            ("harness_prepare", {"runtime_id": "test", "operation": "shell"}),
        ]
        with patch("harness_runs.HarnessRuns") as runs, patch("harness_execution.HarnessExecution") as execution:
            for name, arguments in cases:
                with self.subTest(name=name, arguments=arguments):
                    response = self.server.handle(request("tools/call", {"name": name, "arguments": arguments}))
                    self.assertEqual(response["error"]["code"], -32602)
            runs.assert_not_called()
            execution.assert_not_called()

    def test_lifecycle_failures_do_not_claim_no_effects_and_never_return_raw_error_text(self) -> None:
        initialize(self.server)
        for name, arguments, method in [
            ("harness_start", {"runtime_id": "test", "proposal_id": "sha256:" + "a" * 64, "authorization_ref": "chat:x"}, "start"),
            ("harness_cancel", {"run_id": "run-fixture"}, "cancel"),
        ]:
            with self.subTest(name=name), patch("harness_runs.HarnessRuns") as runs:
                self.server.runs = None
                getattr(runs.return_value, method).side_effect = OSError("SECRET_WORKER_LOG_BODY password=bad")
                response = self.server.handle(request("tools/call", {"name": name, "arguments": arguments}))["result"]
                self.assertTrue(response["isError"])
                self.assertFalse(response["structuredContent"]["read_only"])
                rendered = json.dumps(response)
                self.assertNotIn("SECRET_WORKER_LOG_BODY", rendered)
                self.assertNotIn("password=bad", rendered)
                self.assertNotIn("no action", rendered.lower())
                self.assertNotIn("no runtime action", rendered.lower())
                self.assertIn("durable run state", rendered)

    def test_same_session_reuses_lifecycle_controller_across_start_wait_cancel(self) -> None:
        initialize(self.server)
        with patch("harness_runs.HarnessRuns") as runs:
            runs.return_value.start.return_value = {"run_id": "run-fixture", "read_only": False}
            runs.return_value.wait.return_value = {"run_id": "run-fixture", "read_only": True}
            runs.return_value.cancel.return_value = {"run_id": "run-fixture", "read_only": False}
            for name, arguments in [
                ("harness_start", {"runtime_id": "test", "proposal_id": "sha256:" + "a" * 64, "authorization_ref": "chat:x"}),
                ("harness_wait", {"run_id": "run-fixture"}),
                ("harness_cancel", {"run_id": "run-fixture"}),
            ]:
                response = self.server.handle(request("tools/call", {"name": name, "arguments": arguments}))
                self.assertFalse(response["result"]["isError"])
            runs.assert_called_once_with(self.server.service)
            runs.return_value.start.assert_called_once()
            runs.return_value.wait.assert_called_once()
            runs.return_value.cancel.assert_called_once()

    def test_domain_blockers_are_tool_errors_and_preserve_safe_guidance(self) -> None:
        from harness_service import HarnessServiceError

        initialize(self.server)
        with patch("harness_execution.HarnessExecution") as execution:
            execution.return_value.prepare.return_value = {"read_only": True, "status": "blocked", "blockers": [{"code": "missing_execution_capability"}]}
            response = self.server.handle(request("tools/call", {"name": "harness_prepare", "arguments": {"runtime_id": "test"}}))["result"]
            self.assertTrue(response["isError"])
            self.assertEqual(response["structuredContent"]["blockers"][0]["code"], "missing_execution_capability")
        with patch("harness_runs.HarnessRuns") as runs:
            runs.return_value.wait.side_effect = HarnessServiceError("unknown_run", "Use a run ID returned by start.")
            response = self.server.handle(request("tools/call", {"name": "harness_wait", "arguments": {"run_id": "run-fixture"}}))["result"]
            self.assertTrue(response["isError"])
            self.assertEqual(response["structuredContent"]["error"]["code"], "unknown_run")

    def test_notifications_do_not_get_responses(self) -> None:
        initialize(self.server)
        for method in ["notifications/initialized", "notifications/cancelled", "anything"]:
            self.assertIsNone(self.server.handle({"jsonrpc": "2.0", "method": method}))

    def test_invalid_jsonrpc_envelopes(self) -> None:
        for message in [[], {}, {"jsonrpc": "1.0", "id": 1, "method": "ping"},
                        {"jsonrpc": "2.0", "id": True, "method": "ping"},
                        {"jsonrpc": "2.0", "id": None, "method": "ping"},
                        {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": []}]:
            with self.subTest(message=message):
                self.assertEqual(self.server.handle(message)["error"]["code"], -32600)

    def test_parse_errors_are_recoverable_and_stdout_is_protocol_only(self) -> None:
        source = io.BytesIO(b'not json\n{"jsonrpc":"2.0","id":1,"method":"ping"}\n')
        output = io.BytesIO()
        self.assertEqual(harness_mcp.serve(FakeService(), source, output), 0)
        results = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(results[0]["error"]["code"], -32700)
        self.assertEqual(results[1]["result"], {})

    def test_nan_and_oversized_frames_are_rejected(self) -> None:
        output = io.BytesIO()
        harness_mcp.serve(FakeService(), io.BytesIO(b'{"id":NaN}\n'), output)
        self.assertEqual(json.loads(output.getvalue())["error"]["code"], -32700)
        output = io.BytesIO()
        self.assertEqual(harness_mcp.serve(FakeService(), io.BytesIO(b"x" * (harness_mcp.MAX_MESSAGE_BYTES + 1)), output), 1)
        self.assertEqual(json.loads(output.getvalue())["error"]["code"], -32700)

    def test_large_results_are_bounded_without_partial_invalid_json(self) -> None:
        class HugeService(FakeService):
            def discover(self) -> dict:
                return {"large": "x" * (harness_mcp.MAX_RESULT_BYTES + 1)}

        server = harness_mcp.MCPServer(HugeService())
        initialize(server)
        result = server.handle(request("tools/call", {"name": "harness_discover"}))["result"]
        self.assertTrue(result["isError"])
        self.assertEqual(result["structuredContent"]["error"]["code"], "result_too_large")
        self.assertLess(len(json.dumps(result)), 2000)


class MCPSubprocessTests(unittest.TestCase):
    def test_successful_inspect_through_real_stdio(self) -> None:
        identity_home = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
        if identity_home not in ROOT.resolve().parents:
            self.skipTest("Successful runtime fixture requires a checkout inside the current passwd home.")
        with tempfile.TemporaryDirectory(prefix=".mcp-fixture-", dir=ROOT) as temp:
            root = Path(temp)
            runtime = root / "runtime"
            jobs = runtime / "jobs"
            jobs.mkdir(parents=True)
            (jobs / "shift-fixture-status.json").write_text(json.dumps({"state": "stopped", "shift_id": "fixture", "updated_at": "2026-01-01T00:00:00Z"}), encoding="utf-8")
            registry = root / "registry.json"
            registry.write_text(json.dumps({"version": 1, "runtimes": [{"id": "fixture", "provider": "github", "runtime_dir": str(runtime)}]}), encoding="utf-8")
            before = {str(p): (p.stat().st_mtime_ns, p.read_bytes()) for p in root.rglob("*") if p.is_file()}
            messages = [
                request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "subprocess-test", "version": "1.0"}}, 1),
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                request("tools/call", {"name": "harness_inspect", "arguments": {"runtime_id": "fixture"}}, 2),
                request("tools/call", {"name": "harness_prepare", "arguments": {"runtime_id": "fixture"}}, 3),
            ]
            process = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "harness_mcp.py"), "--registry", str(registry)],
                input="".join(json.dumps(message) + "\n" for message in messages),
                text=True, capture_output=True, timeout=15, cwd=root,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            replies = [json.loads(line) for line in process.stdout.splitlines()]
            result = replies[1]["result"]
            self.assertFalse(result["isError"], result)
            self.assertEqual(result["structuredContent"]["runtime"]["id"], "fixture")
            self.assertEqual(result["structuredContent"]["evidence"][0]["state"], "stopped")
            prepared = replies[2]["result"]
            self.assertTrue(prepared["isError"])
            self.assertTrue(prepared["structuredContent"]["read_only"])
            self.assertEqual(prepared["structuredContent"]["status"], "blocked")
            self.assertIn("missing_execution_capability", {item["code"] for item in prepared["structuredContent"]["blockers"]})
            self.assertFalse(prepared["structuredContent"]["proposal"]["required_authorization"]["granted"])
            self.assertEqual(before, {str(p): (p.stat().st_mtime_ns, p.read_bytes()) for p in root.rglob("*") if p.is_file()})

    def test_real_stdio_handshake_discover_and_inspect_are_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.json"
            registry.write_text(json.dumps({"version": 1, "runtimes": [], "installations": []}), encoding="utf-8")
            before = {str(p): (p.stat().st_mtime_ns, p.read_bytes()) for p in root.rglob("*") if p.is_file()}
            messages = [
                request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "subprocess-test", "version": "1.0"}}, 1),
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                request("tools/list", {}, 2),
                request("tools/call", {"name": "harness_discover", "arguments": {}}, 3),
                request("tools/call", {"name": "harness_inspect", "arguments": {"runtime_id": "missing"}}, 4),
                request("tools/call", {"name": "execute", "arguments": {"command": "touch should-not-exist"}}, 5),
            ]
            process = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "harness_mcp.py"), "--registry", str(registry)],
                input="".join(json.dumps(message) + "\n" for message in messages),
                text=True, capture_output=True, timeout=15, cwd=root,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(process.stderr, "")
            replies = [json.loads(line) for line in process.stdout.splitlines()]
            self.assertEqual([reply["id"] for reply in replies], [1, 2, 3, 4, 5])
            self.assertEqual(replies[0]["result"]["protocolVersion"], "2025-06-18")
            self.assertFalse(replies[2]["result"]["isError"], replies[2])
            self.assertTrue(replies[2]["result"]["structuredContent"]["read_only"])
            self.assertTrue(replies[3]["result"]["isError"])
            self.assertEqual(replies[4]["error"]["code"], -32602)
            after = {str(p): (p.stat().st_mtime_ns, p.read_bytes()) for p in root.rglob("*") if p.is_file()}
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
