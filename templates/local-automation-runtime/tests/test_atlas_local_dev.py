from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

RUNTIME = Path(__file__).resolve().parents[1]
SCRIPT = RUNTIME / "atlas_local_dev.py"
spec = importlib.util.spec_from_file_location("local_dev_under_test", SCRIPT)
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


class LocalDevCLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / "state"
        self.runtime = self.root / "installed-runtime"
        self.runtime.mkdir()
        for source in RUNTIME.glob("*.py"):
            shutil.copy2(source, self.runtime / source.name)
        shutil.copytree(RUNTIME / "team-templates", self.runtime / "team-templates")
        # Every CLI restart has active tripwires against provider/model commands,
        # sockets and databases. Only local Git observation is allowed.
        (self.runtime / "sitecustomize.py").write_text('''
import os, sys
open(os.environ["CLI_GUARD_MARKER"], "a").write("guard active\\n")
def guard(event, args):
    if event.startswith("socket.") or event == "sqlite3.connect":
        raise RuntimeError("external effect forbidden in CLI test")
    if event == "subprocess.Popen" and os.path.basename(str(args[0])) != "git":
        raise RuntimeError("non-Git process forbidden in CLI test")
sys.addaudithook(guard)
''')
        self.env = dict(os.environ, PYTHONPATH=str(self.runtime),
                        CLI_GUARD_MARKER=str(self.root / "guard.log"))

    def git(self, checkout, *args):
        return subprocess.run(["git", "-C", str(checkout), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def run_cli(self, *args, owner=None, stdout=subprocess.PIPE):
        command = [sys.executable, "-B", str(self.runtime / SCRIPT.name),
                   "--runtime-dir", str(self.runtime), "--state-dir", str(self.state)]
        if owner:
            command += ["--owner", owner]
        return subprocess.run([*command, *args], stdout=stdout, stderr=subprocess.PIPE,
                              text=True, env=self.env)

    def ok(self, *args, owner=None):
        result = self.run_cli(*args, owner=owner)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def refused(self, *args, owner=None, code=None):
        before = self.snapshot()
        result = self.run_cli(*args, owner=owner)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        error = json.loads(result.stdout)["error"]
        if code:
            self.assertEqual(error["code"], code)
        self.assertEqual(self.snapshot(), before, "refusal mutated queue/job bytes")
        return error

    def snapshot(self):
        if not self.state.exists():
            return {}
        return {str(p.relative_to(self.state)): p.read_bytes()
                for p in self.state.rglob("*") if p.is_file()}

    def write_json(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value))
        return path

    def make_intake(self, ident="WI-CLI", policy="local-luna-unit-v1"):
        checkout = self.root / ("checkout-" + ident)
        checkout.mkdir()
        self.git(checkout, "init", "-q")
        self.git(checkout, "config", "user.email", "test@example.invalid")
        self.git(checkout, "config", "user.name", "Test")
        (checkout / "tracked.txt").write_text("fixture\n")
        self.git(checkout, "add", "tracked.txt")
        self.git(checkout, "commit", "-qm", "fixture")
        revision = self.git(checkout, "rev-parse", "HEAD")
        task = {
            "id": ident, "title": "CLI lifecycle fixture",
            "goal": "Exercise supervised handoffs using synthetic role output only.",
            "acceptance_criteria": ["Reserved results can be captured and replayed exactly."],
            "spec_path": "/reviewed/source-spec.md", "spec_hash": "sha256:" + "a" * 64,
            "scheduler": {"base_branch": revision, "execution_repo": str(checkout),
                          "workflow_kind": "work-item", "team_template": "work-item-change-lifecycle",
                          "write_scope": ["tracked.txt"]},
            "metadata": {"source_plan": {"path": "/reviewed/plan.json", "hash": "b" * 64},
                         "local_execution_v1": {
                "policy_id": policy,
                "role_purposes": {"implementation": "implementation", "test-runner": "validation",
                                  "code-review": "review", "semantic-alignment": "goal-review",
                                  "evidence-rollup": "review"},
                "changed_interfaces": ["local development CLI"],
                "unresolved_questions": [], "complexity_flags": [],
            }},
        }
        if policy == "local-reviewed-unit-v2":
            # Use maintained context/hash APIs to create a synthetic reviewed fixture.
            code = '''
import json, sys, atlas_work_items, atlas_local_sizing
item=json.load(sys.stdin)
contract=item["metadata"]["local_execution_v1"]
contract.update(implementation_model="gpt-6.1-sol", review_model="gpt-6.1-terra")
contract["sizing_review"]={"reviewer":"synthetic independent sizing fixture",
 "rationale":"Coupled adapter integration needs the reviewed stronger route.",
 "subject_sha256":"pending"}
contract["sizing_review"]["subject_sha256"]=atlas_local_sizing.sizing_subject_sha256(atlas_work_items.work_item_context(item))
print(json.dumps(item))
'''
            result = subprocess.run([sys.executable, "-B", "-c", code], input=json.dumps(task),
                                    capture_output=True, text=True, env=self.env, check=True)
            task = json.loads(result.stdout)
        return checkout, revision, self.write_json(ident + ".json", task)

    def prepared(self, policy="local-luna-unit-v1"):
        checkout, revision, task = self.make_intake(policy=policy)
        self.ok("add", "--task", str(task))
        reservation = self.ok("prepare", "--id", "WI-CLI", "--revision", revision)
        return checkout, revision, reservation

    def import_files(self, reservation):
        binding = reservation["binding"]
        assignment = binding["role_assignment"]
        receipt = {"invocation_id": "synthetic-test-" + binding["handoff_id"],
                   "transport": "supervised_in_app", "checkout": binding["checkout"],
                   "revision": binding["revision"], "model": assignment["model"],
                   "reasoning": assignment["reasoning"]}
        payload = copy.deepcopy(reservation["packet"]["result_template"])
        record = payload["role_results"][0]
        record.update(status="complete",
                      outputs={name: "synthetic harness evidence only" for name in record["outputs"]},
                      evidence=["synthetic fixture; no model-quality claim"],
                      notes="transport wiring only")
        if binding["role_id"] == "semantic-alignment":
            record["goal_review"] = {"verdict": "pass", "reason": "Synthetic fixture satisfies harness criteria.",
                                    "evidence": ["synthetic lifecycle fixture"]}
        prefix = binding["role_id"]
        result = self.root / (prefix + "-original-result.json")
        result.write_bytes(b'\n  ' + json.dumps(payload).encode() + b'\n')
        return (self.write_json("reservation.json", reservation),
                self.write_json("receipt.json", receipt), result)

    def import_args(self, paths):
        reservation, receipt, result = paths
        return ("import", "--reservation", str(reservation), "--host-receipt", str(receipt),
                "--result", str(result))

    def test_status_missing_and_existing_are_read_only(self):
        self.assertEqual(self.ok("status")["status"], "uninitialized")
        self.assertFalse(self.state.exists())
        self.state.mkdir()
        path = self.state / "work-items.json"
        raw = b'{"version":1,"work_items":[]}\n'
        path.write_bytes(raw)
        before = self.snapshot()
        self.assertEqual(self.ok("status")["status"], "observed")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(path.read_bytes(), raw)
        self.assertFalse((self.state / "work-items.json.lock").exists())

    def test_status_terminal_draft_blocked_prerequisites_and_pending_precedence(self):
        _, _, intake = self.make_intake()
        task = json.loads(intake.read_text())
        items = []
        for state in ("done", "failed", "cancelled", "superseded", "draft", "blocked", "ready"):
            item = copy.deepcopy(task)
            item.update(id="WI-" + state, status=state, lifecycle={"state": state})
            if state in {"draft", "blocked"}:
                item["scheduler"].update(blockers=["operator must verify route"], depends_on=["WI-missing"])
            if state == "blocked":
                item["result"] = {"status": "blocked", "summary": "review found a gap",
                                  "evidence": {"goal_acceptance": {"verdict": "fail", "reason": "missing check"}}}
            items.append(item)
        self.state.mkdir()
        path = self.state / "work-items.json"
        path.write_text(json.dumps({"version": 1, "work_items": items}))
        before = self.snapshot()
        rows = {row["state"]: row for row in self.ok("status")["work_items"]}
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(rows["done"]["next_action"], "no further action; inspect retained evidence if needed")
        for state in ("failed", "cancelled", "superseded"):
            self.assertIn("explicit recovery or successor", rows[state]["next_action"])
            self.assertNotIn("prepare", rows[state]["next_action"])
        for state in ("draft", "blocked"):
            self.assertFalse(rows[state]["ready"])
            self.assertIn("blocker: operator must verify route", rows[state]["blockers"])
            self.assertIn("missing dependency: WI-missing", rows[state]["blockers"])
            self.assertIn("resolve listed prerequisites", rows[state]["next_action"])
        self.assertIn("not ready: draft", rows["draft"]["blockers"])
        self.assertIn("goal review fail: missing check", rows["blocked"]["blockers"])
        self.assertTrue(rows["ready"]["ready"])
        self.assertEqual(rows["ready"]["next_action"], "prepare")
        items[0]["supervised_handoff_v1"] = {"pending": {"binding": {"role_id": "implementation"}}}
        path.write_text(json.dumps({"version": 1, "work_items": items}))
        before = self.snapshot()
        row = self.ok("status")["work_items"][0]
        self.assertEqual(row["next_action"], "recover same invocation/import result")
        self.assertEqual(self.snapshot(), before)

    def test_status_prerequisites_survive_uncertainty_and_authority_early_returns(self):
        _, _, intake = self.make_intake()
        task = json.loads(intake.read_text())
        items = [
            {"id": "WI-open", "status": "ready"},
            {"id": "WI-accepted", "status": "done"},
        ]
        # A done work-item dependency without its required goal acceptance is
        # still open. Status must use the scheduler's acceptance semantics.
        unaccepted = copy.deepcopy(task)
        unaccepted.update(id="WI-unaccepted", status="done", lifecycle={"state": "done"})
        items.append(unaccepted)
        active = copy.deepcopy(task)
        active.update(id="WI-active", status="running", lifecycle={"state": "running"})
        items.append(active)
        expected = {}
        for state in ("draft", "blocked"):
            for gate in ("uncertainty", "authority"):
                item = copy.deepcopy(task)
                ident = "WI-" + state + "-" + gate
                item.update(id=ident, status=state, lifecycle={"state": state})
                item["scheduler"].update(
                    blockers=["operator must verify route"],
                    depends_on=["WI-missing", "WI-open", "WI-unaccepted", "WI-accepted"])
                item["metadata"]["local_execution_v1"]["unresolved_questions"] = ["synthetic sizing prerequisite"]
                if gate == "uncertainty":
                    item["process_uncertainty"] = {"status": "unresolved", "invocation_id": "synthetic-worker-7"}
                    diagnostic = "unresolved worker process uncertainty: synthetic-worker-7"
                else:
                    item["metadata"]["provider"] = "azure-devops"
                    diagnostic = "Azure records require the Azure worker and its authority gates"
                if state == "blocked":
                    # Preserve the execution record even when the provider's
                    # uncertainty/authority gate takes diagnostic precedence.
                    item["result"] = {"status": "blocked", "summary": "retained execution diagnostic"}
                items.append(item)
                expected[ident] = (state, diagnostic)
        self.state.mkdir()
        path = self.state / "work-items.json"
        path.write_text(json.dumps({"version": 1, "work_items": items}))
        jobs = self.state / "jobs"
        jobs.mkdir()
        (jobs / "original-worker-bytes.bin").write_bytes(b"synthetic retained bytes\x00\n")
        before = self.snapshot()
        rows = {row["id"]: row for row in self.ok("status")["work_items"]}
        self.assertEqual(self.snapshot(), before, "status changed queue/job bytes")
        self.assertFalse((self.state / "work-items.json.lock").exists())
        for ident, (state, diagnostic) in expected.items():
            row = rows[ident]
            self.assertEqual(row["state"], state)
            self.assertFalse(row["ready"])
            self.assertEqual(row["blockers"][0], diagnostic)
            self.assertIn("blocker: operator must verify route", row["blockers"])
            self.assertIn("missing dependency: WI-missing", row["blockers"])
            self.assertIn("open dependency: WI-open", row["blockers"])
            self.assertIn("open dependency: WI-unaccepted", row["blockers"])
            self.assertNotIn("open dependency: WI-accepted", row["blockers"])
            self.assertTrue(any(value.startswith("local sizing: decomposition_required:")
                                for value in row["blockers"]))
            self.assertIn("active scope conflict: WI-active", row["blockers"])
            self.assertEqual(len(row["blockers"]), len(set(row["blockers"])))
            self.assertIn("resolve listed prerequisites", row["next_action"])

    def test_intake_preserves_source_and_refuses_duplicate_and_runtime_fields(self):
        checkout, revision, path = self.make_intake()
        task = json.loads(path.read_text())
        for field in ("status", "evidence", "claim", "lifecycle", "result", "pending", "accepted"):
            for container in (None, "metadata", "scheduler"):
                candidate = copy.deepcopy(task)
                (candidate if container is None else candidate[container])[field] = {}
                bad = self.write_json("owned.json", candidate)
                self.refused("add", "--task", str(bad), code="task_shape")
        self.assertFalse(self.state.exists())
        self.ok("add", "--task", str(path))
        item = json.loads((self.state / "work-items.json").read_text())["work_items"][0]
        self.assertEqual(item["scheduler"], task["scheduler"])
        self.assertEqual(item["metadata"], task["metadata"])
        self.assertEqual(item["spec_hash"], task["spec_hash"])
        self.assertEqual(item["status"], "ready")
        self.assertEqual(len(item["evidence"]), 1)
        self.refused("add", "--task", str(path), code="duplicate")

    def test_intake_qualification_and_template_refusals(self):
        checkout, revision, path = self.make_intake()
        task = json.loads(path.read_text())
        variants = []
        for field, value in (("base_branch", "main"), ("execution_repo", "relative"),
                             ("team_template", "missing")):
            candidate = copy.deepcopy(task)
            candidate["scheduler"][field] = value
            variants.append(candidate)
        candidate = copy.deepcopy(task)
        candidate["metadata"]["local_execution_v1"]["role_purposes"].pop("test-runner")
        variants.append(candidate)
        candidate = copy.deepcopy(task)
        candidate["goal"] = "done"
        variants.append(candidate)
        for candidate in variants:
            self.refused("add", "--task", str(self.write_json("bad.json", candidate)))
        self.assertFalse(self.state.exists())

    def test_intake_refuses_template_without_independent_goal_gate(self):
        checkout, revision, task = self.make_intake()
        template_path = self.runtime / "team-templates" / "work-item-change-lifecycle.json"
        template = json.loads(template_path.read_text())
        for role in template["roles"]:
            role["goal_gate"] = False
        template_path.write_text(json.dumps(template))
        self.refused("add", "--task", str(task), code="task_qualification")
        self.assertFalse(self.state.exists())

    def test_malformed_unreadable_nonregular_and_oversized_input(self):
        path = self.root / "bad.json"
        for raw in (b'{"id":"private-first","id":"private-second"}', b'{"secret":NaN}',
                    b'{"secret":1e999}', b'[]', b'{', b'\xff', b'{}' + b' ' * 65535):
            path.write_bytes(raw)
            error = self.refused("add", "--task", str(path))
            self.assertNotIn("private", json.dumps(error))
        self.refused("add", "--task", str(self.root / "missing"))
        self.refused("add", "--task", str(self.root))
        fifo = self.root / "fifo"
        os.mkfifo(fifo)
        self.refused("add", "--task", str(fifo))
        self.assertFalse(self.state.exists())

    def test_pending_prepare_replay_and_status(self):
        checkout, revision, reservation = self.prepared()
        before = self.snapshot()
        self.assertEqual(self.ok("prepare", "--id", "WI-CLI", "--revision", revision), reservation)
        self.assertEqual(self.snapshot(), before)
        row = self.ok("status")["work_items"][0]
        self.assertEqual(row["pending_handoff_id"], reservation["binding"]["handoff_id"])
        self.assertEqual(row["pending_role"], "implementation")
        self.assertEqual(row["pending_owner"], "operator:atlas-daily-dev")
        self.assertEqual(self.snapshot(), before)
        self.refused("prepare", "--id", "WI-CLI", "--revision", "a" * 40, code="revision")
        self.refused("prepare", "--id", "WI-CLI", "--revision", revision,
                     owner="operator:foreign", code="pending_conflict")

    def test_prepare_output_loss_recovers_original_reservation(self):
        checkout, revision, path = self.make_intake()
        self.ok("add", "--task", str(path))
        # /dev/full produces an actual stdout write failure after persisted reservation.
        with open("/dev/full", "w") as sink:
            failed = self.run_cli("prepare", "--id", "WI-CLI", "--revision", revision, stdout=sink)
        self.assertNotEqual(failed.returncode, 0)
        payload = json.loads((self.state / "work-items.json").read_text())
        pending = payload["work_items"][0]["supervised_handoff_v1"]["pending"]
        before = self.snapshot()
        recovered = self.ok("prepare", "--id", "WI-CLI", "--revision", revision)
        self.assertEqual(recovered["binding"], pending["binding"])
        self.assertEqual(self.snapshot(), before)

    def test_global_pending_refuses_other_item_before_claim(self):
        first_checkout, revision, first = self.make_intake()
        second_checkout, second_revision, second = self.make_intake("WI-OTHER")
        self.ok("add", "--task", str(first))
        self.ok("add", "--task", str(second))
        self.ok("prepare", "--id", "WI-CLI", "--revision", revision)
        self.refused("prepare", "--id", "WI-OTHER", "--revision", second_revision,
                     code="pending_conflict")
        other = json.loads((self.state / "work-items.json").read_text())["work_items"][1]
        self.assertEqual(other["status"], "ready")
        self.assertNotIn("claim", other)

    def test_competing_real_prepare_is_rechecked_inside_maintained_claim(self):
        _, first_revision, first = self.make_intake("WI-FIRST")
        _, second_revision, second = self.make_intake("WI-SECOND")
        self.ok("add", "--task", str(first))
        self.ok("add", "--task", str(second))
        # Enter a real competing preparation after the CLI's first pending scan
        # but before claim takes its lock. No queue fields are hand-edited.
        code = '''
import pathlib, sys
import atlas_local_dev as cli, atlas_work_items as wi, atlas_supervised_handoff as handoff
runtime, state, first_revision, second_revision = sys.argv[1:]
original_claim = wi.AtlasWorkItemOperationProvider.claim
triggered = False
def competing_prepare(self, operation):
    global triggered
    if not triggered:
        triggered = True
        items = {wi.item_id(item): item for item in self.store.load()["work_items"]}
        assert original_claim(self, self.project(items["WI-FIRST"], items)) is not None
        worker = wi.LocalCommandOperationWorker(
            command=None, jobs_dir=pathlib.Path(state)/"jobs",
            templates_dir=pathlib.Path(runtime)/"team-templates")
        reservation = handoff.prepare_handoff(
            self, worker, source_id="WI-FIRST", expected_revision=first_revision)
        print("COMPETING_PENDING=" + reservation["binding"]["handoff_id"], file=sys.stderr)
    return original_claim(self, operation)
wi.AtlasWorkItemOperationProvider.claim = competing_prepare
raise SystemExit(cli.main([
    "--runtime-dir", runtime, "--state-dir", state,
    "prepare", "--id", "WI-SECOND", "--revision", second_revision]))
'''
        result = subprocess.run(
            [sys.executable, "-B", "-c", code, str(self.runtime), str(self.state),
             first_revision, second_revision], env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["error"]["code"], "claim")
        items = {item["id"]: item for item in
                 json.loads((self.state / "work-items.json").read_text())["work_items"]}
        pending = items["WI-FIRST"]["supervised_handoff_v1"]["pending"]
        self.assertIn("COMPETING_PENDING=" + pending["binding"]["handoff_id"], result.stderr)
        self.assertEqual(items["WI-SECOND"]["status"], "ready")
        self.assertNotIn("claim", items["WI-SECOND"])
        self.assertEqual(len(items["WI-SECOND"]["evidence"]), 1)
        self.assertNotIn("supervised_handoff_v1", items["WI-SECOND"])
        before = self.snapshot()
        replay = self.ok("prepare", "--id", "WI-FIRST", "--revision", first_revision)
        self.assertEqual(replay["binding"], pending["binding"])
        self.assertEqual(replay["packet"], pending["packet"])
        self.assertEqual(self.snapshot(), before)

    def test_resume_owned_running_claim_and_refuse_foreign_claim(self):
        checkout, revision, path = self.make_intake()
        self.ok("add", "--task", str(path))
        # Simulate a restart between maintained claim and prepare, using the actual API.
        code = '''
import sys, atlas_work_items as w
s=w.AtlasWorkItemStore(sys.argv[1]); p=w.AtlasWorkItemOperationProvider(s,claimed_by="operator:atlas-daily-dev")
i=s.load()["work_items"][0]
assert p.claim(p.project(i)) is not None
'''
        subprocess.run([sys.executable, "-B", "-c", code, str(self.state / "work-items.json")],
                       env=self.env, check=True, capture_output=True)
        self.refused("prepare", "--id", "WI-CLI", "--revision", revision,
                     owner="operator:foreign", code="claim")
        self.assertEqual(self.ok("prepare", "--id", "WI-CLI", "--revision", revision)["status"], "prepared")

    def test_import_refuses_wrong_owner_receipt_packet_and_artifacts(self):
        checkout, revision, reservation = self.prepared()
        paths = self.import_files(reservation)
        self.refused(*self.import_args(paths), owner="operator:foreign")
        receipt = json.loads(paths[1].read_text())
        for key, value in (("transport", "other"), ("model", "other"), ("revision", "a" * 40)):
            changed = {**receipt, key: value}
            self.write_json("receipt.json", changed)
            self.refused(*self.import_args(paths))
        self.write_json("receipt.json", {**receipt, "extra": "unsupported"})
        self.refused(*self.import_args(paths))
        self.write_json("receipt.json", receipt)
        for field in ("packet", "binding", "artifacts"):
            changed = copy.deepcopy(reservation)
            changed[field]["changed"] = True
            self.write_json("reservation.json", changed)
            self.refused(*self.import_args(paths))
        self.write_json("reservation.json", reservation)
        self.assertEqual(self.ok(*self.import_args(paths))["status"], "accepted")

    def test_import_and_accepted_replay_after_pending_removal_and_head_change(self):
        checkout, revision, reservation = self.prepared("local-reviewed-unit-v2")
        self.assertEqual(reservation["binding"]["role_assignment"]["model"], "gpt-6.1-sol")
        paths = self.import_files(reservation)
        paths[2].write_bytes(paths[2].read_bytes().ljust(65536, b" "))
        original = paths[2].read_bytes()
        accepted = self.ok(*self.import_args(paths))
        self.assertEqual(accepted["status"], "accepted")
        self.assertEqual(Path(accepted["original_result_path"]).read_bytes(), original)
        item = json.loads((self.state / "work-items.json").read_text())["work_items"][0]
        self.assertNotIn("pending", item["supervised_handoff_v1"])
        (checkout / "later.txt").write_text("advance HEAD\n")
        self.git(checkout, "add", "later.txt")
        self.git(checkout, "commit", "-qm", "advance")
        before = self.snapshot()
        self.assertEqual(self.ok(*self.import_args(paths))["status"], "duplicate")
        self.assertEqual(self.snapshot(), before)
        self.refused(*self.import_args(paths), owner="operator:foreign", code="claim_owner")
        paths[2].write_bytes(b" " + original[1:])
        self.refused(*self.import_args(paths), code="replay_conflict")
        paths[2].write_bytes(original)
        receipt = json.loads(paths[1].read_text())
        self.write_json("receipt.json", {**receipt, "invocation_id": "different-invocation"})
        self.refused(*self.import_args(paths), code="replay_conflict")
        self.write_json("receipt.json", receipt)
        changed = copy.deepcopy(reservation)
        changed["packet"]["label"] = "changed"
        self.write_json("reservation.json", changed)
        self.refused(*self.import_args(paths), code="reservation")
        self.write_json("reservation.json", reservation)
        for raw in (b'{}' + b' ' * 65535, b'{"role_results":[],"role_results":[]}', b'{"x":Infinity}'):
            paths[2].write_bytes(raw)
            self.refused(*self.import_args(paths))

    def test_live_return_refuses_advanced_head_without_import_writes(self):
        checkout, revision, reservation = self.prepared()
        paths = self.import_files(reservation)
        (checkout / "later.txt").write_text("unexpected checkout advance\n")
        self.git(checkout, "add", "later.txt")
        self.git(checkout, "commit", "-qm", "advance during pending")
        self.refused(*self.import_args(paths), code="revision")
        self.refused("prepare", "--id", "WI-CLI", "--revision", revision, code="revision")

    def test_template_results_refuse_malformed_shapes_without_changing_state(self):
        _, _, reservation = self.prepared()
        paths = self.import_files(reservation)
        valid = json.loads(paths[2].read_bytes())
        variants = {"bare-record": valid["role_results"][0]}
        for name, mutate in (
            ("nested-output", lambda r: r["outputs"].update(change_summary={"detail": "nested"})),
            ("evidence-output-list", lambda r: r["outputs"].update(evidence=["misplaced"])),
            ("wrong-role", lambda r: r.update(role_id="test-runner")),
        ):
            payload = copy.deepcopy(valid)
            mutate(payload["role_results"][0])
            variants[name] = payload
        for name, payload in variants.items():
            bad = self.write_json(name + "-original-result.json", payload)
            self.refused(*self.import_args((*paths[:2], bad)),
                         code="role" if name == "wrong-role" else "result_shape")
        original = paths[2].read_bytes()
        accepted = self.ok(*self.import_args(paths))
        self.assertEqual(Path(accepted["original_result_path"]).read_bytes(), original)

    def test_unexpected_string_evidence_output_is_imported_but_blocks_workflow(self):
        _, _, reservation = self.prepared()
        paths = self.import_files(reservation)
        payload = json.loads(paths[2].read_bytes())
        payload["role_results"][0]["outputs"]["evidence"] = "misplaced string"
        candidate = self.write_json("evidence-output-string-original-result.json", payload)
        original = candidate.read_bytes()
        accepted = self.ok(*self.import_args((*paths[:2], candidate)))
        self.assertEqual(accepted["status"], "accepted")
        self.assertEqual(accepted["item_status"], "blocked")
        self.assertEqual(Path(accepted["original_result_path"]).read_bytes(), original)
        runs = list((self.state / "jobs").glob("supervised-import-*/team-run.json"))
        self.assertEqual(len(runs), 1)
        result = json.loads(runs[0].read_text())["role_results"]["implementation"]
        self.assertIn("unexpected output(s): evidence", result["contract_issues"])

    def test_all_roles_use_maintained_lifecycle_without_external_execution(self):
        checkout, revision, reservation = self.prepared()
        seen = []
        for _ in range(5):
            seen.append(reservation["binding"]["role_id"])
            packet = reservation["packet"]
            template = packet["result_template"]
            record = template["role_results"][0]
            self.assertEqual(set(template), {"role_results"})
            self.assertEqual(len(template["role_results"]), 1)
            self.assertEqual(record["role_id"], packet["role_id"])
            self.assertEqual(record["status"], "blocked")
            self.assertEqual(record["outputs"], {name: "" for name in packet["must_produce"]})
            self.assertEqual(record["goal_review"],
                             {"verdict": "inconclusive", "reason": "", "evidence": []}
                             if packet["goal_gate"] else None)
            self.assertIn("exactly one record", packet["result_instructions"])
            self.assertIn("STRING values", packet["result_instructions"])
            self.assertIn("record level", packet["result_instructions"])
            packet_hash = hashlib.sha256(json.dumps(
                packet, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                allow_nan=False).encode()).hexdigest()
            self.assertEqual(reservation["binding"]["packet_hash"], packet_hash)
            paths = self.import_files(reservation)
            for path in paths[:2]:
                shutil.copy2(path, self.root / (packet["role_id"] + "-" + path.name))
            original = paths[2].read_bytes()
            accepted = self.ok(*self.import_args(paths))
            self.assertEqual(Path(accepted["original_result_path"]).read_bytes(), original)
            if accepted["item_status"] == "done":
                break
            reservation = self.ok("prepare", "--id", "WI-CLI", "--revision", revision)
        self.assertEqual(seen, ["implementation", "test-runner", "code-review",
                                "semantic-alignment", "evidence-rollup"])
        self.assertEqual(accepted["item_status"], "done")
        before = self.snapshot()
        self.assertIn("no further action", self.ok("status")["work_items"][0]["next_action"])
        self.assertEqual(self.snapshot(), before)
        self.assertTrue((self.root / "guard.log").read_text().startswith("guard active"))
        self.assertFalse(list(self.runtime.rglob("__pycache__")))

    def test_bounded_read_limits_actual_stream_before_parse(self):
        stream = mock.MagicMock()
        stream.__enter__.return_value = stream
        stream.fileno.return_value = 99
        stream.read.return_value = b"x" * 65537
        with mock.patch.object(cli.os, "open", return_value=99), \
             mock.patch.object(cli.os, "fdopen", return_value=stream), \
             mock.patch.object(cli.os, "fstat", return_value=mock.Mock(st_mode=0o100644)):
            with self.assertRaises(cli.CLIError):
                cli.bounded_read("growing-file.json")
        stream.read.assert_called_once_with(65537)

    def test_missing_explicit_runtime_cannot_fall_back_to_source_modules(self):
        (self.runtime / "atlas_local_sizing.py").unlink()
        self.refused("status", code="runtime")
        self.assertFalse(self.state.exists())

    def test_argument_errors_are_structured(self):
        self.refused("prepare", "--id", "WI-CLI", code="arguments")


if __name__ == "__main__":
    unittest.main()
