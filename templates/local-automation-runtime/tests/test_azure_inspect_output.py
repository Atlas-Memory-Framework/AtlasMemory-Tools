from __future__ import annotations

import contextlib
import hashlib
import importlib.machinery
import importlib.util
import io
import os
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader("azure_inspect_output_test", str(ROOT / "atlas-agent-azure-inspect"))
spec = importlib.util.spec_from_loader(loader.name, loader)
cli = importlib.util.module_from_spec(spec)
loader.exec_module(cli)

LIMIT = 245760
PRIVATE = "PRIVATE_SENTINEL"
ARGUMENT_ERROR = b'{"complete":false,"eligible_count":0,"error":"Azure inspection arguments are invalid."}\n'
OPERATION_ERROR = (b'{"complete":false,"eligible_count":0,"error":'
                   b'"Azure inspection failed validation or could not complete; no mutation was attempted."}\n')
# Exact compact bytes frozen by exactfixtures.json (sha256
# 72872429ce875ccbb4a673303eb0ac21fc49d8f8e4ced52435ebd26f4d4da86a).
FALLBACK_PINS = {'dry': (1986, '3c550fc3a87f7191ef107b4d70e01fa10b161d55ef0474391dfd888e031e2301'), 'live_repository_not_observed': (1993, '05a110c10abf2847ffcf3276153eeef3516a60518591e27b161631a9e881ad95'), 'live_repository_observed': (1992, 'd2ebb661e46c4dc2cae9005cbbebdeb616d81dad0e973943e21a4cde939292c8'), 'offline': (1995, '4588c5bbd83f724c1664793f37717b002038c33cb587e2a4b97ea6ebf466fc87')}
MODES = (("dry-run", False, "dry"), ("offline-snapshot", False, "offline"),
         ("live-read-only", False, "live_repository_not_observed"),
         ("live-read-only", True, "live_repository_observed"))


def pretty(value):
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n").encode()


class PrivateObject:
    def __repr__(self):
        raise AssertionError("arbitrary repr must never run")

    def __str__(self):
        raise AssertionError("arbitrary str must never run")


class RenderTests(unittest.TestCase):
    def render(self, report, mode="dry-run", observed=False):
        return cli.render_inspection_report(report, inspection_mode=mode, repository_observed=observed)

    def assert_fallback(self, result, name):
        stdout, stderr, code = result
        size, digest = FALLBACK_PINS[name]
        self.assertEqual((stderr, code), (b"", 0))
        self.assertEqual(len(stdout), size)
        self.assertEqual(hashlib.sha256(stdout).hexdigest(), digest)
        self.assertEqual(stdout.count(b"\n"), 1)
        value = json.loads(stdout)
        self.assertFalse(value["complete"])
        self.assertFalse(value["dependency_complete"])
        repository = value["repository_evidence"]
        self.assertFalse(repository["bindings_complete"])
        self.assertFalse(repository["projection_complete"])
        self.assertTrue(repository["budget"]["report_omitted"])
        self.assertTrue(repository["budget"]["aggregate_truncated"])
        self.assertNotIn(PRIVATE.encode(), stdout)
        self.assertLess(len(stdout) + len(stderr), 262144)
        return value

    def test_exact_and_one_byte_over_in_all_four_variants(self):
        for mode, observed, name in MODES:
            for size in (LIMIT, LIMIT + 1):
                with self.subTest(mode=mode, observed=observed, size=size):
                    report = {"complete": False, "eligible_count": 0,
                              "inspection_mode": mode, "private_padding": ""}
                    report["private_padding"] = "a" * (size - len(pretty(report)))
                    original = pretty(report)
                    self.assertEqual(len(original), size)
                    result = self.render(report, mode, observed)
                    if size == LIMIT:
                        self.assertEqual(result, (original, b"", 0))
                    else:
                        self.assert_fallback(result, name)
                    self.assertEqual(pretty(report), original, "helper mutated input")

    def test_board_config_and_repository_overflow_omit_all_payload(self):
        for field in ("items", "effective_configuration", "repository_evidence"):
            with self.subTest(field=field):
                report = {"inspection_mode": "offline-snapshot", field: [PRIVATE * 20000]}
                self.assert_fallback(self.render(report, "offline-snapshot"), "offline")

    def test_unicode_escaping_and_newline_are_counted(self):
        report = {"inspection_mode": "dry-run", "private_padding": "é" * 45000}
        self.assertLess(len(json.dumps(report, ensure_ascii=False).encode()), LIMIT)
        self.assertGreater(len(pretty(report)), LIMIT)
        self.assert_fallback(self.render(report), "dry")
        small = {"inspection_mode": "dry-run", "value": "😀é\n\t\""}
        self.assertEqual(self.render(small), (pretty(small), b"", 0))

    def test_all_native_json_types_and_shared_acyclic_values_keep_old_bytes(self):
        shared = [None, True, False, 0, -7, 1.25, "é"]
        report = {"inspection_mode": "dry-run", "one": shared, "two": shared, "empty": {}}
        self.assertEqual(self.render(report), (pretty(report), b"", 0))

    def test_invalid_native_values_fail_without_conversion(self):
        class DictSubclass(dict):
            pass
        class StringSubclass(str):
            pass
        cycle = []
        cycle.append(cycle)
        values = [float("nan"), float("inf"), -float("inf"), cycle, PrivateObject(),
                  {1: "private"}, {StringSubclass("key"): 1}, (1, 2), {1, 2}, b"text",
                  "\ud800", {"\udfff": 1}, DictSubclass(a=1), StringSubclass("private")]
        for index, value in enumerate(values):
            with self.subTest(index=index):
                self.assertEqual(self.render({"inspection_mode": "dry-run", "value": value}),
                                 (b"", OPERATION_ERROR, 2))
        self.assertEqual(self.render(DictSubclass(inspection_mode="dry-run")), (b"", OPERATION_ERROR, 2))

    def test_invalid_mode_and_observation_are_strict(self):
        for mode, observed in (("unknown", False), ("dry-run", True), ("offline-snapshot", True),
                               ("dry-run", 0), (PrivateObject(), False), ("dry-run", PrivateObject())):
            self.assertEqual(self.render({"inspection_mode": "dry-run"}, mode, observed),
                             (b"", OPERATION_ERROR, 2))
        for report in ({}, {"inspection_mode": "live-read-only"}, [], None):
            self.assertEqual(self.render(report), (b"", OPERATION_ERROR, 2))

    def test_encoder_and_resource_failures_return_precomputed_error(self):
        for failure in (ValueError(PRIVATE), UnicodeError(PRIVATE), RecursionError(PRIVATE), MemoryError(PRIVATE)):
            with self.subTest(kind=type(failure).__name__), mock.patch.object(cli.json, "dumps", side_effect=failure):
                self.assertEqual(self.render({"inspection_mode": "dry-run"}), (b"", OPERATION_ERROR, 2))
        deep = []
        for _ in range(2000):
            deep = [deep]
        self.assertEqual(self.render({"inspection_mode": "dry-run", "deep": deep}), (b"", OPERATION_ERROR, 2))

    def test_external_stops_are_not_serialized(self):
        for stop in (KeyboardInterrupt, SystemExit):
            with mock.patch.object(cli.json, "dumps", side_effect=stop), self.assertRaises(stop):
                self.render({"inspection_mode": "dry-run"})


class MainTests(unittest.TestCase):
    assert_fallback = RenderTests.assert_fallback

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="atlas-wrapper-output-", dir="/tmp")
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.config = self.folder / "config.json"
        example = ROOT.parents[1] / "examples/instablinds/local-automation-runtime/config/azure-website.json"
        self.config.write_bytes(example.read_bytes())
        self.snapshot = self.folder / "snapshot.json"
        self.snapshot_value = {"items": [{"id": 17, "rev": 1,
            "fields": {"System.State": "To Do", "System.Title": "Item 17", "System.TeamProject": "Instablinds"},
            "relations": []}], "complete": True, "observed_at": "2020-01-01T00:00:00Z"}
        self.snapshot.write_text(json.dumps(self.snapshot_value))
        self.args = ["--config", str(self.config), "--ids", "17"]
        self.loaded = cli.load_runtime_config(self.config, require_runtime=False)

    def invoke(self, extra=(), *, args=None):
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            code = cli.main(self.args + list(extra) if args is None else args)
        return out.getvalue().encode(), err.getvalue().encode(), code

    def no_network(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(cli, "azure_cli_headers", side_effect=AssertionError("auth called")))
        stack.enter_context(mock.patch.object(cli, "AzureDevOpsClient", side_effect=AssertionError("network called")))

    def fake_live(self, *, report=None, repository=None):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(cli, "load_runtime_config", return_value=self.loaded))
        stack.enter_context(mock.patch.object(cli, "azure_cli_headers", return_value={}))
        client = stack.enter_context(mock.patch.object(cli, "AzureDevOpsClient"))
        provider = stack.enter_context(mock.patch.object(cli, "AzureBoardsProvider")).return_value
        provider.inspect.return_value = {"complete": False, "items": []} if report is None else report
        provider.repository_evidence.return_value = {"complete": False} if repository is None else repository
        return provider, client

    def test_small_dry_default_explicit_and_snapshot_match_legacy_exactly(self):
        self.no_network()
        before = {p.name: p.read_bytes() for p in self.folder.iterdir()}
        dry = {"inspection_mode": "dry-run", "ids": [17], "eligible_count": 0,
               "complete": False, "dependency_complete": False,
               "blockers": ["inspection-not-executed", "execution-authority-not-established"],
               "effects": [], "planned_reads": ["expanded-work-item-closure", "fresh-revision-recheck",
                   "repository", "base-ref", "pull-requests", "policies", "builds", "timelines"],
               "effective_configuration": self.loaded.report()}
        for extra in ([], ["--dry-run"]):
            self.assertEqual(self.invoke(extra), (pretty(dry), b"", 0))
        expected = cli.project_snapshot(self.snapshot_value, organization="Instablinds", project="Instablinds")
        expected.update(inspection_mode="offline-snapshot", effective_configuration=self.loaded.report())
        self.assertEqual(self.invoke(["--snapshot", str(self.snapshot)]), (pretty(expected), b"", 0))
        self.assertEqual({p.name: p.read_bytes() for p in self.folder.iterdir()}, before)
        self.assertEqual(json.loads(pretty(dry))["effective_configuration"]["models"]["implementation"]["model"], "gpt-6-astra")

    def test_snapshot_provenance_spoof_and_board_overflow_use_offline(self):
        self.no_network()
        spoof = {"inspection_mode": "live-read-only", "repository_evidence": {"observed": True},
                 "items": [PRIVATE * 20000]}
        with mock.patch.object(cli, "project_snapshot", return_value=spoof):
            value = self.assert_fallback(self.invoke(["--snapshot", str(self.snapshot)]), "offline")
        self.assertFalse(value["repository_evidence"]["observed"])

    def test_configuration_overflow_is_measured_after_attachment(self):
        self.no_network()
        with mock.patch.object(type(self.loaded), "report", return_value={"private": PRIVATE * 20000}):
            self.assert_fallback(self.invoke(), "dry")
            self.assert_fallback(self.invoke(["--snapshot", str(self.snapshot)]), "offline")

    def test_main_exact_threshold_includes_configuration_and_mode(self):
        self.no_network()
        for size in (LIMIT, LIMIT + 1):
            report = {"items": [], "private_padding": "", "inspection_mode": "offline-snapshot",
                      "effective_configuration": self.loaded.report()}
            report["private_padding"] = "a" * (size - len(pretty(report)))
            expected = pretty(report)
            with mock.patch.object(cli, "project_snapshot", return_value=dict(report)):
                result = self.invoke(["--snapshot", str(self.snapshot)])
            if size == LIMIT:
                self.assertEqual(result, (expected, b"", 0))
            else:
                self.assert_fallback(result, "offline")

    def test_live_incomplete_real_dict_is_observed_and_build_ids_are_forwarded(self):
        provider, client = self.fake_live(report={"items": [PRIVATE * 20000]}, repository={"complete": False})
        self.assert_fallback(self.invoke(["--live-read", "--build-ids", "1,2"]), "live_repository_observed")
        self.assertEqual(provider.repository_evidence.call_args.kwargs["build_ids"], [1, 2])
        self.assertEqual(client.call_args.kwargs["capabilities"], {"read"})

    def test_malformed_repository_response_is_fixed_error_not_fallback(self):
        provider, _ = self.fake_live(report={"items": [PRIVATE * 20000]})
        class DictSubclass(dict):
            pass
        for value in (None, [], "private", PrivateObject(), DictSubclass(complete=False)):
            provider.repository_evidence.return_value = value
            self.assertEqual(self.invoke(["--live-read"]), (b"", OPERATION_ERROR, 2))

    def test_invalid_build_ids_fail_before_repository_or_timeline_request(self):
        provider, _ = self.fake_live()
        self.assertEqual(self.invoke(["--live-read", "--build-ids", PRIVATE]), (b"", OPERATION_ERROR, 2))
        provider.repository_evidence.assert_not_called()

    def test_parser_errors_are_bounded_private_and_do_not_load_config(self):
        private = PRIVATE * 100000
        cases = [[], [private], ["--config", private, "--unknown", private],
                 ["--config", private, "--dry-run", "--live-read"], ["--config"],
                 ["--config", private, "--snapshot", private, "--dry-run"]]
        with mock.patch.object(cli, "load_runtime_config", side_effect=AssertionError("loaded")), \
                mock.patch.object(sys, "argv", [private]):
            for args in cases:
                self.assertEqual(self.invoke(args=args), (b"", ARGUMENT_ERROR, 2))
        self.assertLess(len(ARGUMENT_ERROR), 16384)

    def test_private_operational_errors_and_prints_are_discarded(self):
        failures = [cli.AzureError, cli.RuntimeConfigError, ValueError, TypeError,
                    AttributeError, OSError, RuntimeError, Exception, MemoryError, RecursionError]
        for failure in failures:
            def fail(*args, **kwargs):
                print(PRIVATE * 100000)
                print(PRIVATE * 100000, file=sys.stderr)
                raise failure(PRIVATE * 100000)
            with self.subTest(failure=failure.__name__), mock.patch.object(cli, "load_runtime_config", side_effect=fail):
                self.assertEqual(self.invoke(), (b"", OPERATION_ERROR, 2))
        self.assertLess(len(OPERATION_ERROR), 16384)

    def test_report_and_provider_python_prints_do_not_pollute_json(self):
        original_output = sys.stdout
        provider, _ = self.fake_live()
        def noisy_report():
            print(PRIVATE * 20000)
            print(PRIVATE * 20000, file=sys.stderr)
            return {"models": {}}
        provider.inspect.side_effect = lambda *a, **kw: (noisy_report() and {"complete": False})
        with mock.patch.object(type(self.loaded), "report", side_effect=noisy_report):
            stdout, stderr, code = self.invoke(["--live-read"])
        self.assertEqual((stderr, code), (b"", 0))
        value = json.loads(stdout)
        self.assertEqual(value["inspection_mode"], "live-read-only")
        self.assertNotIn(PRIVATE.encode(), stdout)
        self.assertIs(sys.stdout, original_output)

    def test_failures_at_snapshot_provider_configuration_and_serialization_boundaries(self):
        self.no_network()
        with mock.patch.object(cli, "project_snapshot", side_effect=RuntimeError(PRIVATE)):
            self.assertEqual(self.invoke(["--snapshot", str(self.snapshot)]), (b"", OPERATION_ERROR, 2))
        with mock.patch.object(type(self.loaded), "report", side_effect=RuntimeError(PRIVATE)):
            self.assertEqual(self.invoke(), (b"", OPERATION_ERROR, 2))
        with mock.patch.object(cli.json, "dumps", side_effect=MemoryError(PRIVATE)):
            self.assertEqual(self.invoke(), (b"", OPERATION_ERROR, 2))
        # A fresh fake live context overrides the no-network refusal mocks locally.
        provider, _ = self.fake_live()
        for method in (provider.inspect, provider.repository_evidence):
            method.side_effect = RuntimeError(PRIVATE)
            self.assertEqual(self.invoke(["--live-read"]), (b"", OPERATION_ERROR, 2))
            method.side_effect = None

    def test_discard_sink_retains_no_dependency_text(self):
        sink = cli._DiscardSink()
        self.assertEqual(sink.write(PRIVATE * 100000), len(PRIVATE) * 100000)
        self.assertIsNone(sink.flush())
        self.assertFalse(hasattr(sink, "__dict__"))

    def test_help_is_static_bounded_and_preserves_systemexit_zero(self):
        self.no_network()
        helps = []
        for entry in (lambda: cli.main(["--help"]), lambda: cli.build_parser().parse_args(["--help"])):
            with mock.patch.object(sys, "argv", [PRIVATE * 100000]), \
                    contextlib.redirect_stdout(io.StringIO()) as out, \
                    contextlib.redirect_stderr(io.StringIO()) as err:
                with self.assertRaises(SystemExit) as stopped:
                    entry()
            self.assertEqual(stopped.exception.code, 0)
            self.assertEqual(err.getvalue(), "")
            self.assertLessEqual(len(out.getvalue().encode()), 16384)
            self.assertNotIn(PRIVATE, out.getvalue())
            self.assertIn("usage: atlas-agent-azure-inspect", out.getvalue())
            helps.append(out.getvalue())
        self.assertEqual(*helps)

    def test_foreign_identity_input_is_refused_before_read(self):
        with mock.patch.object(Path, "read_text", side_effect=AssertionError("read attempted")):
            with self.assertRaises(cli.AzureError):
                cli._read_json("/home/a-foreign-identity/private.json")






    def test_external_operational_stops_propagate_and_restore_streams(self):
        for stop in (KeyboardInterrupt, SystemExit):
            with mock.patch.object(cli, "load_runtime_config", side_effect=stop), \
                    contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
                with self.assertRaises(stop):
                    cli.main(self.args)
            self.assertEqual((out.getvalue(), err.getvalue()), ("", ""))


def fixture_environment():
    return {key: value for key, value in os.environ.items()
            if key not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")}


def owned_grant(text, closefd=True):
    return cli.grant_owned_stream(text, terminal_close=True, all_aliases=True,
        descriptor_exclusive=True, stable_exclusive_use=True,
        expected_closefd=closefd, byte_preserving_ascii=True)


class PublicationAdmissionTests(unittest.TestCase):
    def test_exact_lf_threshold_fallback_error_and_help_bytes(self):
        for mode, observed, name in MODES:
            for size in (LIMIT, LIMIT + 1):
                report = {"inspection_mode": mode, "items": [0] * 10000, "padding": ""}
                report["padding"] = "a" * (size - len(pretty(report)))
                prepared = cli.render_inspection_report(report, inspection_mode=mode, repository_observed=observed)
                self.assertEqual((prepared[1], prepared[2]), (b"", 0))
                for newline in ("\n", "\r\n", "\r", "", None):
                    with self.subTest(mode=mode, observed=observed, size=size, newline=newline):
                        out, err = io.StringIO(newline=newline), io.StringIO()
                        before = io.StringIO.__getstate__(out)
                        context = cli.publication_context(out, err)
                        with mock.patch.object(cli, "_construct_report", return_value=prepared):
                            code = cli.main(["--config", "mock"], publication=context)
                        if newline == "\n":
                            self.assertEqual(code, 0)
                            self.assertEqual(out.getvalue().encode(), prepared[0])
                            self.assertLessEqual(len(out.getvalue().encode()), LIMIT)
                            json.loads(out.getvalue())
                            if size == LIMIT:
                                self.assertEqual(prepared[0], pretty(report))
                            else:
                                self.assertEqual((len(prepared[0]), hashlib.sha256(prepared[0]).hexdigest()), FALLBACK_PINS[name])
                        else:
                            self.assertEqual(code, 2)
                            self.assertEqual(io.StringIO.__getstate__(out), before)
                        self.assertEqual(err.getvalue(), "")
                        self.assertFalse(out.closed)
        for route in ("argument", "operation", "help"):
            for newline in ("\n", "\r\n", "\r", "", None):
                out, err = io.StringIO(newline=newline), io.StringIO(newline=newline)
                before = (io.StringIO.__getstate__(out), io.StringIO.__getstate__(err))
                context = cli.publication_context(out, err)
                with mock.patch.object(cli, "_construct_report", side_effect=RuntimeError(PRIVATE)):
                    if route == "help" and newline == "\n":
                        with self.assertRaises(SystemExit) as stopped:
                            cli.main(["--help"], publication=context)
                        self.assertEqual(stopped.exception.code, 0)
                        self.assertEqual(out.getvalue(), cli.build_parser().format_help())
                        self.assertLessEqual(len(out.getvalue().encode()), 16384)
                        self.assertEqual(err.getvalue(), "")
                    else:
                        code = cli.main([] if route == "argument" else ["--help"] if route == "help" else ["--config", "mock"], publication=context)
                        self.assertEqual(code, 2)
                        if newline == "\n":
                            self.assertEqual(out.getvalue(), "")
                            self.assertEqual(err.getvalue().encode(), ARGUMENT_ERROR if route == "argument" else OPERATION_ERROR)
                        else:
                            self.assertEqual((io.StringIO.__getstate__(out), io.StringIO.__getstate__(err)), before)
                self.assertFalse(out.closed)
                self.assertFalse(err.closed)

    def test_memory_refusal_preserves_content_position_hooks_and_both_channels(self):
        for variant in ("prefilled-zero", "prefilled-end", "gap", "getter", "write", "closed", "runtime"):
            for target in ("out", "err"):
                out, err = io.StringIO(), io.StringIO()
                selected = out if target == "out" else err
                calls = []
                if variant.startswith("prefilled"):
                    io.StringIO.write(selected, PRIVATE)
                    if variant.endswith("zero"):
                        io.StringIO.seek(selected, 0)
                if variant == "gap":
                    io.StringIO.seek(selected, 7)
                if variant in ("getter", "write"):
                    setattr(selected, "__getstate__" if variant == "getter" else "write", lambda *a: calls.append("hook"))
                if variant == "closed":
                    io.StringIO.close(selected)
                before = None if selected.closed else io.StringIO.__getstate__(selected)
                with mock.patch.object(cli, "_construct_report", side_effect=AssertionError("must preflight before operations")) as construct:
                    with mock.patch.object(cli, "_QUALIFIED_MEMORY_RUNTIME", ("unqualified", (0, 0, 0))) if variant == "runtime" else contextlib.nullcontext():
                        self.assertEqual(cli.main(["--config", "mock"], publication=cli.publication_context(out, err)), 2)
                    construct.assert_not_called()
                self.assertEqual(calls, [])
                if not selected.closed:
                    self.assertEqual(io.StringIO.__getstate__(selected), before)
                self.assertEqual((err if target == "out" else out).getvalue(), "")
        out, err = io.StringIO(), io.StringIO()
        context = cli.publication_context(out, err)
        with mock.patch.object(cli, "_construct_report", return_value=(b'{}\n', b'', 0)):
            self.assertEqual(cli.main(["--config", "mock"], publication=context), 0)
            before = out.getvalue()
            self.assertEqual(cli.main(["--config", "mock"], publication=context), 2)
        self.assertEqual(out.getvalue(), before)
        self.assertFalse(out.closed)
        with self.assertRaises(cli._PublicationFailure):
            cli.build_parser(publication=context).parse_args(["--help"])

    def test_unowned_custom_and_instance_hooks_refuse_without_callbacks(self):
        calls = []
        class Hostile:
            def __getattribute__(self, name):
                calls.append("lookup")
                raise AssertionError(PRIVATE)
        class MemorySubclass(io.StringIO):
            pass
        class HostileMeta(type):
            def __getattribute__(self, name):
                calls.append("metaclass")
                raise AssertionError(PRIVATE)
        class MetaInstance(metaclass=HostileMeta):
            pass
        for stream in (Hostile(), MetaInstance(), MemorySubclass(), io.BytesIO()):
            with self.assertRaises(cli._PublicationRefused):
                owned_grant(stream)
            context = cli.publication_context(stream, io.StringIO())
            with mock.patch.object(cli, "_construct_report", return_value=(b'{}\n', b'', 0)):
                self.assertEqual(cli.main(["--config", "mock"], publication=context), 2)
            with self.assertRaises(cli._PublicationFailure):
                cli.build_parser(publication=context).parse_args(["--help"])
        self.assertEqual(calls, [])
        for layer, key in (("text", "write"), ("text", "flush"), ("text", "close"), ("buffer", "flush"), ("raw", "close"), ("raw", "flush"), ("raw", "write"), ("raw", "closed")):
            read_fd, write_fd = os.pipe()
            os.close(read_fd)
            raw = io.FileIO(write_fd, "wb")
            buffer = io.BufferedWriter(raw)
            text = io.TextIOWrapper(buffer, encoding="ascii", newline="\n")
            target = {"text": text, "buffer": buffer, "raw": raw}[layer]
            attributes = object.__getattribute__(target, "__dict__")
            attributes[key] = lambda *a: calls.append("shadow")
            try:
                with self.assertRaises(cli._PublicationRefused):
                    owned_grant(text)
            finally:
                attributes.pop(key, None)
                io.FileIO.close(raw)
        self.assertEqual(calls, [])

    def test_grant_is_explicit_bound_and_literal_and_no_production_raw_subclasses(self):
        read_fd, write_fd = os.pipe()
        os.close(read_fd)
        raw = io.FileIO(write_fd, "wb")
        text = io.TextIOWrapper(io.BufferedWriter(raw), encoding="ascii", newline="\n")
        try:
            with mock.patch.object(cli, "_construct_report", return_value=(b'{}\n', b'', 0)):
                self.assertEqual(cli.main(["--config", "mock"], publication=cli.publication_context(text, io.StringIO())), 2)
            self.assertFalse(raw.closed)
            for kwargs in ({}, {"terminal_close": True}, {"terminal_close": 1, "all_aliases": True, "descriptor_exclusive": True, "stable_exclusive_use": True, "expected_closefd": True, "byte_preserving_ascii": True}):
                with self.assertRaises(cli._PublicationRefused):
                    cli.grant_owned_stream(text, **kwargs)
            with self.assertRaises(cli._PublicationRefused):
                owned_grant(text, False)
            grant = owned_grant(text)
            with self.assertRaises(cli._PublicationRefused):
                cli._admit_target(io.StringIO(), grant)
            self.assertFalse(raw.closed)
        finally:
            io.FileIO.close(raw)
        class Raw(io.RawIOBase):
            def writable(self): return True
            def write(self, data): return len(data)
        raw = Raw()
        text = io.TextIOWrapper(io.BufferedWriter(raw), encoding="ascii")
        try:
            with self.assertRaises(cli._PublicationRefused):
                owned_grant(text, False)
        finally:
            io.RawIOBase.close(raw)


TRANSPORT_CHILD = r"""
import gc,importlib.machinery,importlib.util,io,json,os,sys
from unittest import mock
wrapper,kind,route,audit_path=sys.argv[1:]
audit_fd=os.open(audit_path,os.O_WRONLY|os.O_APPEND|os.O_CREAT,0o600)
def audit(event,**values):os.write(audit_fd,(json.dumps({'event':event,**values})+'\n').encode())
loader=importlib.machinery.SourceFileLoader('actual_source_transport',wrapper)
spec=importlib.util.spec_from_loader(loader.name,loader);cli=importlib.util.module_from_spec(spec);loader.exec_module(cli)
class BrokenRaw(io.RawIOBase):
 def writable(self):return True
 def write(self,data):
  audit('raw-write')
  if kind=='interrupt':raise KeyboardInterrupt
  if kind=='systemexit':raise SystemExit(99)
  if kind=='partial':os.write(1,bytes(data[:1]))
  raise OSError('PRIVATE_RAW_TRANSPORT_SENTINEL')
stack=[]
if kind.startswith('fileio'):
 closefd=kind!='fileio-false';r,w=os.pipe();os.close(r)
 raw=io.FileIO(w,'wb',closefd=closefd)
 if kind=='fileio-error':os.close(w)
else:
 raw=BrokenRaw();closefd=False
 def shape(text):
  assert type(text) is io.TextIOWrapper
  b=io.TextIOWrapper.buffer.__get__(text);assert type(b) is io.BufferedWriter
  assert io.BufferedWriter.raw.__get__(b) is raw and type(raw) is BrokenRaw
  assert object.__getattribute__(text,'__dict__')=={} and object.__getattribute__(b,'__dict__')=={} and object.__getattribute__(raw,'__dict__')=={}
  return b,raw
 def close(r):
  audit('raw-close')
  if kind=='uncertain':raise OSError('PRIVATE_CLOSE_UNCERTAIN')
  io.RawIOBase.close(r)
 # Explicit trusted qualification fixture patches; never a production flag/path.
 if kind!='borrowed':
  for name,value in [('_owned_shape',shape),('_raw_closefd',lambda r:False),('_raw_closed',lambda r:io.IOBase.closed.__get__(r)),('_close_raw',close)]:
   patch=mock.patch.object(cli,name,value);patch.start();stack.append(patch)
text=io.TextIOWrapper(io.BufferedWriter(raw),encoding='ascii',newline='\n')
if kind=='borrowed':text.write('CALLER_PENDING')
grant=None if kind=='borrowed' else cli.grant_owned_stream(text,terminal_close=True,all_aliases=True,descriptor_exclusive=True,stable_exclusive_use=True,expected_closefd=closefd,byte_preserving_ascii=True)
out,err=(sys.stdout,text) if route in ('argument','operation') else (text,sys.stderr)
if route=='aliased':out=err=text
if route=='original':sys.__stdout__=text;sys.__stderr__=text
if route=='saved':saved=text
if route=='shared':
 second=io.TextIOWrapper(io.BufferedWriter(raw),encoding='ascii');second.write('ALIAS_PENDING');sys.stderr=second;err=second
if route in ('argument','operation'):sys.stderr=text
else:sys.stdout=text
ctx=cli.publication_context(out,err,stdout_grant=grant if out is text else None,stderr_grant=grant if err is text else None)
cli._construct_report=lambda args:(b'',cli._OPERATION_ERROR,2) if route=='operation' else ((json.dumps({'complete':False,'padding':'a'*50000}).encode()+b'\n',b'',0) if kind=='large' else (b'{"complete":false}\n',b'',0))
args=[] if route=='argument' else ['--help'] if route in ('help','parser') else ['--config','mocked-no-read']
try:
 if route=='parser':
  try:cli.build_parser(publication=ctx).parse_args(args)
  except cli._PublicationFailure:code=2
 else:code=cli.main(args,publication=ctx)
except (KeyboardInterrupt,SystemExit) as stop:
 if kind not in ('interrupt','systemexit'):raise
 assert grant.close_attempts==0 and grant.state=='ready';audit('external-stop')
 io.RawIOBase.close(raw);raise SystemExit(0)
assert code==2
if kind=='healthy-stderr':sys.stderr.write('CALLER_CONTINUES\n');sys.stderr.flush()
if grant is not None:
 audit('grant',state=grant.state,close_attempts=grant.close_attempts,closed=raw.closed)
 assert grant.close_attempts==1
 if kind=='uncertain':assert grant.state=='closure-uncertain' and not raw.closed
 else:assert grant.state=='closed-confirmed' and raw.closed and text.closed
if route=='saved':
 try:saved.flush()
 except ValueError:pass
 else:raise AssertionError('saved alias replay')
 del saved
if kind.startswith('fileio'):
 try:os.fstat(w);descriptor_open=True
 except OSError:descriptor_open=False
 assert descriptor_open is (not closefd)
 audit('descriptor',open=descriptor_open,closefd=closefd)
 if descriptor_open:os.close(w)
# Immediate release and real shutdown both matter; active original aliases remain.
del ctx,out,err,text,raw,grant
if route=='shared':del second
gc.collect();audit('after-gc')
raise SystemExit(code)
"""


class RealPublicationProcessTests(unittest.TestCase):
    def test_real_source_owned_and_fixture_shutdown_matrix(self):
        cases = [("fixture", route) for route in ("normal", "help", "parser", "argument", "operation", "aliased", "original", "saved", "shared")]
        cases += [(kind, route) for kind in ("fileio", "fileio-false", "fileio-error") for route in ("normal", "help", "argument", "parser")]
        cases += [("large", "normal"), ("healthy-stderr", "normal"), ("partial", "normal"), ("interrupt", "normal"), ("systemexit", "normal"), ("uncertain", "normal"), ("borrowed", "normal")]
        with tempfile.TemporaryDirectory(prefix="atlas-source-transport-", dir="/tmp") as temp:
            for index, (kind, route) in enumerate(cases):
                with self.subTest(kind=kind, route=route):
                    audit = Path(temp) / f"{index}.jsonl"
                    result = subprocess.run([sys.executable, "-B", "-c", TRANSPORT_CHILD,
                        str(ROOT / "atlas-agent-azure-inspect"), kind, route, str(audit)],
                        cwd=temp, env=fixture_environment(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
                    events = [json.loads(line) for line in audit.read_bytes().splitlines()]
                    if kind in ("uncertain", "borrowed"):
                        self.assertIn(result.returncode, (2, 120))
                        self.assertIn(b"PRIVATE_RAW_TRANSPORT_SENTINEL", result.stderr)
                        if kind == "uncertain":
                            self.assertIn("closure-uncertain", [event.get("state") for event in events])
                        continue  # Deliberately unqualified outcomes, never clean passes.
                    if kind in ("interrupt", "systemexit"):
                        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b"", b""))
                        self.assertIn("external-stop", [event["event"] for event in events])
                        continue
                    self.assertEqual((result.returncode, result.stdout, result.stderr),
                                     (2, b"{" if kind == "partial" else b"", b"CALLER_CONTINUES\n" if kind == "healthy-stderr" else b""))
                    if kind in ("fixture", "partial", "large", "healthy-stderr"):
                        self.assertEqual(sum(event["event"] == "raw-write" for event in events), 1)
                        self.assertEqual(sum(event["event"] == "raw-close" for event in events), 1)

    def test_dedicated_actual_cli_normal_help_and_broken_pipes(self):
        with tempfile.TemporaryDirectory(prefix="atlas-owned-cli-", dir="/tmp") as temp:
            config = Path(temp) / "provider.json"
            config.write_bytes((ROOT.parents[1] / "examples/instablinds/local-automation-runtime/config/azure-website.json").read_bytes())
            normal = [sys.executable, "-B", str(ROOT / "atlas-agent-azure-inspect"), "--config", str(config), "--ids", "17"]
            before = config.read_bytes()
            result = subprocess.run(normal, cwd=temp, env=fixture_environment(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
            self.assertEqual((result.returncode, result.stderr), (0, b""))
            value = json.loads(result.stdout)
            self.assertEqual(value["inspection_mode"], "dry-run")
            self.assertEqual(value["effective_configuration"]["models"]["implementation"]["model"], "gpt-6-astra")
            help_args = normal[:3] + ["--help"]
            help_result = subprocess.run(help_args, cwd=temp, env=fixture_environment(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
            self.assertEqual((help_result.returncode, help_result.stderr), (0, b""))
            self.assertEqual(help_result.stdout.decode(), cli.build_parser().format_help())
            for args, failing in ((normal, "stdout"), (help_args, "stdout"), (normal[:3], "stderr")):
                read_fd, write_fd = os.pipe()
                os.close(read_fd)
                try:
                    broken = subprocess.run(args, cwd=temp, env=fixture_environment(),
                        stdout=write_fd if failing == "stdout" else subprocess.PIPE,
                        stderr=write_fd if failing == "stderr" else subprocess.PIPE, timeout=15)
                finally:
                    os.close(write_fd)
                self.assertEqual(broken.returncode, 2)
                self.assertEqual(broken.stderr if failing == "stdout" else broken.stdout, b"")
            self.assertEqual(config.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
