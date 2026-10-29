"""Subprocess checks for explicit discovery without touching a real installation."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "scripts/atlas_daily.py"
REVISION = "a" * 40


class DailyEntryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.checkout = self.root / "checkout"
        (self.checkout / "scripts").mkdir(parents=True)
        self.script = self.checkout / "scripts/atlas_daily.py"
        shutil.copyfile(SOURCE, self.script)
        (self.checkout / ".gitignore").write_text(".atlas-dev.local.json\n")
        self.git("init", "--quiet")
        self.git("add", ".")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "-c", "core.hooksPath=/dev/null", "commit", "--quiet", "-m", "fixture")
        self.head = self.git("rev-parse", "HEAD").strip()
        self.runtime = self.root / "selected runtime"
        self.runtime.mkdir()
        self.state = self.root / "selected state"
        self.cwd = self.root / "foreign cwd"
        self.cwd.mkdir()
        self.config_path = self.checkout / ".atlas-dev.local.json"
        self.config = {"runtime_dir": str(self.runtime), "state_dir": str(self.state),
                       "owner": "operator:fixture", "source_commit": REVISION,
                       "lane": "supervised_in_app", "standalone_enabled": False,
                       "private_extra": "DO_NOT_ECHO_LOCAL_EXTRAS"}
        self.write_config()
        self.text_marker = self.runtime / "source-revision.txt"
        self.text_marker.write_text(REVISION + "\n")
        self.marker_path = self.runtime / "runtime-source.json"
        self.marker_path.write_text(json.dumps(self.config))
        self.native = {"status": "observed", "work_items": [{
            "id": "TASK", "state": "running", "ready": False, "blockers": [],
            "pending_handoff_id": "retained-handoff", "pending_role": "implementation",
            "pending_owner": "operator:fixture",
            "next_action": "recover same invocation/import result"}]}
        self.helper = self.runtime / "atlas_local_dev.py"
        self.set_helper()

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.checkout), *args],
                              capture_output=True, text=True, check=True).stdout

    def write_config(self):
        self.config_path.write_text(json.dumps(self.config))

    def set_helper(self, output=None, exit_code=0):
        output = json.dumps(self.native) if output is None else output
        self.helper.write_text(
            "import sys\n"
            "assert sys.dont_write_bytecode\n"
            "assert sys.argv[1:] == " + repr([
                "--runtime-dir", str(self.runtime), "--state-dir", str(self.state),
                "--owner", self.config["owner"], "status"]) + "\n"
            "print(" + repr(output) + ")\n"
            "raise SystemExit(" + str(exit_code) + ")\n")

    def snapshot(self):
        return {str(path.relative_to(self.root)): (
            "dir" if path.is_dir() else hashlib.sha256(path.read_bytes()).hexdigest())
            for path in self.root.rglob("*")}

    def invoke(self, *args, script=None, expected=0):
        before = self.snapshot()
        result = subprocess.run([sys.executable, "-B", str(script or self.script), *args],
                                cwd=self.cwd, capture_output=True, text=True, timeout=40)
        self.assertEqual(self.snapshot(), before, "discovery changed fixture bytes or paths")
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertNotIn("DO_NOT_ECHO_LOCAL_EXTRAS", result.stdout)
        value = json.loads(result.stdout)
        if expected == 2:
            self.assertTrue(value["error"]["code"])
            self.assertTrue(value["error"]["message"])
        return value

    def test_default_from_foreign_cwd_preserves_native_pending_and_bytes(self):
        # A competing cwd config must never affect the script's default selection.
        (self.cwd / ".atlas-dev.local.json").write_text('{"runtime_dir":"decoy"}')
        self.state.mkdir()
        (self.state / "work-items.json").write_text('{"retained":"queue bytes"}\n')
        value = self.invoke("status")
        self.assertEqual(value["native_status"], self.native)
        identity = value["identity"]
        self.assertEqual(identity["runtime_dir"], str(self.runtime))
        self.assertEqual(identity["state_dir"], str(self.state))
        self.assertEqual(identity["owner"], "operator:fixture")
        self.assertEqual(identity["source_checkout_head"], self.head)
        self.assertEqual(identity["runtime_source_commit"], REVISION)
        self.assertTrue(identity["candidate_drift"])
        self.assertFalse(identity["source_checkout_dirty"])
        self.assertIn("not installed-file integrity", value["qualification_boundary"])

    def test_symlink_entry_uses_resolved_script_checkout(self):
        link = self.cwd / "daily.py"
        link.symlink_to(self.script)
        value = self.invoke(script=link)
        self.assertEqual(value["identity"]["config"], str(self.config_path))
        self.assertFalse(self.state.exists())

    def test_explicit_external_config(self):
        external = self.cwd / "explicit.json"
        self.config_path.rename(external)
        value = self.invoke("--config", str(external), "status")
        self.assertEqual(value["identity"]["config"], str(external))

    def test_missing_default_does_not_fall_back_to_cwd(self):
        self.config_path.rename(self.cwd / ".atlas-dev.local.json")
        self.invoke("status", expected=2)

    def test_missing_explicit_does_not_fall_back_to_default(self):
        self.invoke("--config", str(self.root / "missing.json"), "status", expected=2)

    def test_dirty_checkout_is_reported_without_rejecting_runtime_pin(self):
        self.script.write_text(self.script.read_text() + "\n# reviewed candidate\n")
        value = self.invoke("status")
        self.assertTrue(value["identity"]["source_checkout_dirty"])
        self.assertEqual(value["identity"]["runtime_source_commit"], REVISION)

    def test_strict_bounded_config_failures(self):
        for raw in (b"{}", b"[]", b"{", b"\xff", b" " * 65537,
                    b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}',
                    b'{"x":1e999}', b'{"nested":{"x":1,"x":2}}'):
            with self.subTest(raw=raw[:40]):
                self.config_path.write_bytes(raw)
                self.invoke("status", expected=2)

    def test_invalid_selection(self):
        baseline = dict(self.config)
        for field, value in (("runtime_dir", "relative"), ("state_dir", "relative"),
                             ("runtime_dir", None), ("owner", ""), ("owner", " \t"),
                             ("owner", "operator\nother"), ("owner", " operator"),
                             ("lane", "unattended"), ("standalone_enabled", True),
                             ("standalone_enabled", 0), ("source_commit", "abc")):
            with self.subTest(field=field, value=value):
                self.config = {**baseline, field: value}
                self.write_config()
                self.invoke("status", expected=2)
        self.invoke("--config", "relative.json", "status", expected=2)

    def test_missing_installed_runtime_or_helper(self):
        self.config["runtime_dir"] = str(self.root / "missing")
        self.write_config()
        self.invoke("status", expected=2)
        self.config["runtime_dir"] = str(self.runtime)
        self.write_config()
        self.helper.unlink()
        self.invoke("status", expected=2)

    def test_unencodable_owner_is_sanitized_and_read_only(self):
        self.state.mkdir()
        (self.state / "work-items.json").write_text('{"retained":"queue bytes"}\n')
        for invalid in ("\ud800", "\udfff", "\udc00"):
            with self.subTest(invalid=repr(invalid)):
                self.config["owner"] = "DO_NOT_ECHO_SELECTION" + invalid
                self.write_config()
                # Keep provenance consistent so encoding is the only invalidity.
                self.marker_path.write_text(json.dumps(self.config))
                value = self.invoke("status", expected=2)
                self.assertEqual(value["error"]["code"], "selection")
                self.assertIn("encodable", value["error"]["message"])
                self.assertNotIn("DO_NOT_ECHO_SELECTION", json.dumps(value))

    def test_unencodable_paths_are_sanitized_and_read_only(self):
        self.state.mkdir()
        (self.state / "work-items.json").write_text('{"retained":"queue bytes"}\n')
        baseline = dict(self.config)
        for field in ("runtime_dir", "state_dir"):
            with self.subTest(field=field, location="config"):
                self.config = {**baseline, field: str(self.root / "DO_NOT_ECHO_SELECTION") + "\ud800"}
                self.write_config()
                value = self.invoke("status", expected=2)
                self.assertEqual(value["error"]["code"], "selection")
                self.assertIn("encodable", value["error"]["message"])
                self.assertNotIn("DO_NOT_ECHO_SELECTION", json.dumps(value))
            with self.subTest(field=field, location="marker"):
                self.config = dict(baseline)
                self.write_config()
                self.marker_path.write_text(json.dumps({
                    **baseline, field: str(self.root / "DO_NOT_ECHO_SELECTION") + "\ud800"}))
                value = self.invoke("status", expected=2)
                self.assertEqual(value["error"]["code"], "selection")
                self.assertIn("encodable", value["error"]["message"])
                self.assertNotIn("DO_NOT_ECHO_SELECTION", json.dumps(value))

    def select_unicode_fixture(self, suffix):
        new_runtime = self.root / ("runtime-" + suffix)
        self.runtime.rename(new_runtime)
        self.runtime = new_runtime
        self.state = self.root / ("state-" + suffix)
        self.state.mkdir()
        (self.state / "work-items.json").write_text('{"retained":"queue bytes"}\n')
        self.helper = self.runtime / "atlas_local_dev.py"
        self.marker_path = self.runtime / "runtime-source.json"
        self.config.update(runtime_dir=str(self.runtime), state_dir=str(self.state),
                           owner="operator:" + suffix)
        self.native["work_items"][0]["pending_owner"] = self.config["owner"]
        self.write_config()
        self.marker_path.write_text(json.dumps(self.config))
        self.set_helper()
        value = self.invoke("status")
        for field in ("runtime_dir", "state_dir", "owner"):
            self.assertEqual(value["identity"][field], self.config[field])
        self.assertEqual(value["native_status"], self.native)

    def test_supported_non_ascii_unicode_selection_is_preserved(self):
        self.select_unicode_fixture("caf\u00e9-\u6771\u4eac-\U0001f680")

    def test_supported_filesystem_surrogateescape_selection_is_preserved(self):
        # POSIX surrogateescape round-trips filename/argument bytes. It is not
        # an encoding failure, so do not reject every surrogate indiscriminately.
        try:
            os.fsencode("\udc80")
        except UnicodeError:
            self.skipTest("filesystem encoding does not support this surrogateescape")
        self.select_unicode_fixture("byte-\udc80")

    def test_source_template_is_refused_even_with_markers(self):
        template = self.checkout / "templates/local-automation-runtime"
        template.parent.mkdir()
        shutil.copytree(self.runtime, template)
        self.config["runtime_dir"] = str(template)
        self.write_config()
        self.invoke("status", expected=2)

    def test_each_marker_alone_is_sufficient(self):
        self.marker_path.unlink()
        self.invoke("status")
        self.marker_path.write_text(json.dumps(self.config))
        self.text_marker.unlink()
        self.invoke("status")

    def test_missing_mismatched_or_ambiguous_provenance(self):
        self.text_marker.unlink()
        self.marker_path.unlink()
        self.invoke("status", expected=2)
        self.text_marker.write_text("b" * 40)
        self.invoke("status", expected=2)
        self.marker_path.write_text(json.dumps(self.config))
        self.invoke("status", expected=2)  # agreeing JSON cannot excuse other marker
        self.text_marker.write_text(REVISION)
        self.marker_path.write_text('{"source_commit":"' + REVISION + '","source_commit":"' + REVISION + '"}')
        self.invoke("status", expected=2)

    def test_contradictory_marker_identity(self):
        for field, value in (("runtime_dir", str(self.root)), ("state_dir", str(self.root)),
                             ("owner", "operator:other"), ("lane", "unattended"),
                             ("standalone_enabled", True), ("source_commit", "b" * 40)):
            with self.subTest(field=field):
                self.marker_path.write_text(json.dumps({**self.config, field: value}))
                self.invoke("status", expected=2)

    def test_native_uninitialized_state_is_preserved_without_creating_state(self):
        native = {"status": "uninitialized", "work_items": [], "next_action": "add a task"}
        self.set_helper(json.dumps(native))
        self.assertEqual(self.invoke("status")["native_status"], native)
        self.assertFalse(self.state.exists())

    def test_native_failure_or_malformed_status_is_concrete(self):
        for output, code in (("failure", 2), ("not JSON", 0), ("[]", 0),
                             ('{"status":"observed"}', 0),
                             ('{"status":"observed","work_items":[null]}', 0),
                             ('{"status":[],"work_items":[]}', 0),
                             ('{"status":"observed","work_items":[],"x":NaN}', 0)):
            with self.subTest(output=output):
                self.set_helper(output, code)
                value = self.invoke("status", expected=2)
                self.assertEqual(value["error"]["code"], "native_status")

    def test_only_status_is_exposed(self):
        for command in ("prepare", "import", "add", "update", "dispatch"):
            with self.subTest(command=command):
                self.invoke(command, expected=2)


if __name__ == "__main__":
    unittest.main()
