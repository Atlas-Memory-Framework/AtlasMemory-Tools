"""Bounded controller boundaries; external transports alone are synthetic."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import atlas_approval as approval
import atlas_azure_devops as azure
import atlas_azure_reconcile as reconcile
import atlas_dispatch as dispatch
import atlas_supervisor as supervisor
from atlas_authority import canonical_digest
import test_azure_supervisor_evals as fixture
import test_azure_reconcile as board_fixture


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        # Reuse only the independent eval's synthetic environment, never its
        # outcome oracle or a callback that supplies a successful child report.
        self.f = fixture.AzureSupervisorOutcomeEvals("test_supervisor_refresh_signed_responses_and_real_bounded_child_ingestion")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def gate(self, *, kind="input", action="local_execute"):
        f = self.f
        return {"id": "owner-input", "kind": kind, "owner": "operator", "question": "Which label fits this reviewed flow?",
                "stage": "before", "action": action, "artifact_sha256": "e" * 64,
                "candidate_sha": None, "issue_id": f.packet["id"], "issue_revision": f.packet.get("revision", 7)}

    def prepared(self):
        f = self.f
        request = f.pending_execution()
        f.accept(request)
        result = f.supervisor().run(max_cycles=1)
        self.assertEqual(result["items"][0]["state"], "prepared", result)
        self.assertEqual(f.supervisor_state()["operation"]["request_revision"], approval.ApprovalInbox(f.runtime)._current(request)["revision"])
        return f.workspace / ".atlas-worker" / canonical_digest(f.packet)

    def graph(self, *, missing=True):
        f = self.f
        raw = [board_fixture.item(17), board_fixture.item(18)]
        for row in raw:
            row["rev"] = 7
            row["relations"] = []
        manifest = {"schema_version": 1, "organization": "Instablinds", "project": "Instablinds",
                    "dependencies": {f.packet["id"]: [board_fixture.ident(18)] if missing else [], board_fixture.ident(18): []}}
        f.packet["expected_manifest"] = manifest
        f.packet["inspection_authority"]["dependency_contract_sha256"] = canonical_digest(manifest)
        f.client = board_fixture.FakeClient(raw, f.now)
        f.client.clock = lambda: f.now
        f.provider = azure.AzureBoardsProvider(f.client)
        return f.client

    def test_read_capability_is_required_before_state_auth_or_injected_provider(self):
        f = self.f
        f.config = replace(f.config, capabilities=frozenset())
        before = f.files()
        with mock.patch.object(azure, "azure_cli_headers", side_effect=AssertionError("must not authenticate")), \
             mock.patch.object(f.provider, "inspect", side_effect=AssertionError("must not inspect")):
            for mode in ("observe", "run"):
                with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "capability"):
                    getattr(f.supervisor(), mode)()
            self.assertTrue(f.supervisor().preview()["inert"])
        self.assertEqual(f.files(), before)

    def test_partial_draft_reports_missing_commands_and_persisted_report_without_authority(self):
        f = self.f
        f.packet["commands"] = []
        f.packet["acceptance"] = []
        with mock.patch.object(approval, "verify_grant", side_effect=AssertionError("draft must not verify authority")):
            result = f.supervisor().observe(max_cycles=1)
        item = result["items"][0]
        self.assertEqual(item["state"], "draft")
        self.assertIn("worker_packet.commands", item["missing_fields"])
        self.assertIn("worker_packet.acceptance", item["missing_fields"])
        self.assertFalse(item["requests"])
        saved = json.loads(Path(item["intake_report_path"]).read_text())
        self.assertIsNone(saved["intake_report"]["intake"])
        self.assertEqual(saved["intake_report"]["draft"]["worker_packet"]["commands"], [])
        self.assertEqual(f.runner.calls, [])

    def test_human_request_binds_native_filled_packet_and_survives_long_wait(self):
        f = self.f
        del f.packet["schema_version"]
        del f.packet["revision"]
        f.definition["human_gates"] = [self.gate() | {"issue_revision": 7}]
        first = f.supervisor().observe(max_cycles=1)
        self.assertEqual(first["items"][0]["state"], "waiting_human", first)
        self.assertEqual(len(first["requests"]), 1)
        request = first["requests"][0]["request"]
        actual = f.supervisor_state()["intake_report"]["intake"]["worker_packet"]
        self.assertEqual(actual["schema_version"], 1)
        self.assertEqual(actual["revision"], 7)
        self.assertEqual(request["human_gate"]["context"]["worker_packet_sha256"], canonical_digest(actual))
        f.accept(request, response_text="Use Confirm order.")
        before = f.supervisor().observe(max_cycles=1)
        old_intake = f.supervisor_state()["intake_report"]["intake"]
        f.now += 601
        after = f.supervisor().observe(max_cycles=1)
        self.assertEqual(after["items"][0]["state"], "waiting_authority", after)
        human = [row for row in after["requests"] if row["request"]["action"] == "human_gate"][0]
        self.assertEqual(human["request"], request)
        self.assertEqual(human["card"]["revision"], 1)
        self.assertEqual(human["response_status"], "accepted")
        report = f.supervisor_state()["intake_report"]
        self.assertNotEqual(canonical_digest(old_intake), canonical_digest(report["intake"]))
        controller = f.controller(report)
        from atlas_routing import assessment_context
        for role in ("assessment", "challenge"):
            self.assertIn("Use Confirm order.", json.dumps(assessment_context(report["intake"], f.policy, role)))
        self.assertEqual(f.runner.calls, [])
        self.assertEqual(before["items"][0]["state"], "waiting_authority")

    def test_stale_revision_prevents_old_human_card_preparation(self):
        f = self.f
        f.definition["human_gates"] = [self.gate()]
        f.http.raw["rev"] += 1
        result = f.supervisor().observe(max_cycles=1)
        self.assertEqual(result["items"][0]["state"], "draft")
        self.assertEqual(result["requests"], [])
        self.assertFalse((f.runtime / "approval-inbox").exists())

    def test_external_handoff_records_real_receipt_and_never_runs_pipeline(self):
        f = self.f
        f.definition["step"].update(kind="external", action="pipeline_run")
        f.definition["human_gates"] = [self.gate(kind="approval", action="pipeline_run")]
        first = f.supervisor().observe(max_cycles=1)
        self.assertEqual(first["items"][0]["state"], "waiting_human", first)
        f.accept(first["requests"][0]["request"], response_text="The pipeline owner reviewed this candidate; scheduling is human-owned.")
        result = f.supervisor().run(max_cycles=1)
        self.assertEqual(result["items"][0]["state"], "human_evidence_verified", result)
        self.assertFalse(result["completion"])
        self.assertEqual(f.runner.calls, [])
        self.assertNotIn("authorized-child:pipeline_run", result["effects"])

    def test_review_cards_show_concrete_scope_commands_acceptance_and_exact_models(self):
        f = self.f
        request = f.pending_execution()
        details = request["details"]
        self.assertEqual(details["task"], f.packet["task"])
        self.assertEqual(details["commands"], f.packet["commands"])
        self.assertEqual(details["acceptance"], f.packet["acceptance"])
        self.assertEqual(details["write_scope"], f.packet["write_scope"])
        self.assertEqual(details["effective_models"]["implementation"]["model"], "gpt-5.6-terra")
        self.assertEqual(details["effective_models"]["review"]["model"], "gpt-5.6-sol")
        self.assertFalse(details["completion"])

    def test_observe_does_not_consume_accepted_execution_grant(self):
        f = self.f
        request = f.pending_execution()
        f.accept(request)
        roles = f.runner.roles()
        result = f.supervisor().observe(max_cycles=1)
        self.assertEqual(result["items"][0]["state"], "authorized_pending_run", result)
        self.assertEqual(f.runner.roles(), roles)
        self.assertFalse((f.runtime / "state" / "azure-worker" / "claims.json").exists())

    def test_assessment_timeout_admission_never_launches_then_detaches_a_child(self):
        f = self.f
        pending = f.supervisor().observe(max_cycles=1)
        f.accept(f.operation_request(pending, "assess"))
        result = f.supervisor().run(max_cycles=1, max_seconds=599)
        self.assertEqual(result["items"][0]["state"], "blocked", result)
        self.assertIn("time budget", result["items"][0]["blockers"][0])
        self.assertEqual(f.runner.calls, [])
        self.assertNotIn("operation", f.supervisor_state())

    def test_worker_admission_uses_full_approved_timeouts_without_rewriting_packet(self):
        f = self.f
        f.accept(f.pending_execution())
        original = deepcopy(f.packet)
        admission = original["role_timeout_seconds"] * 5 + sum(row["timeout_seconds"] for row in original["commands"]) * 2
        result = f.supervisor().run(max_cycles=1, max_seconds=admission - 1)
        self.assertEqual(result["items"][0]["state"], "blocked", result)
        self.assertEqual(f.runner.roles(), ["assessment", "challenge"])
        self.assertEqual(f.supervisor_state()["intake_report"]["intake"]["worker_packet"], original)
        self.assertFalse((f.runtime / "state" / "azure-worker" / "claims.json").exists())

    def test_deadline_crossed_during_synchronous_read_stops_before_cards_or_models(self):
        f = self.f
        now = [0]
        original = f.provider.inspect
        def slow_read(*args, **kwargs):
            result = original(*args, **kwargs)
            now[0] = 61
            return result
        controller = f.supervisor()
        controller.monotonic = lambda: now[0]
        with mock.patch.object(f.provider, "inspect", side_effect=slow_read):
            result = controller.observe(max_cycles=1, max_seconds=60)
        self.assertEqual(result["items"][0]["state"], "blocked", result)
        self.assertEqual(result["requests"], [])
        self.assertEqual(f.runner.calls, [])
        self.assertIn("synchronous", result["time_enforcement"])

    def test_bounds_cannot_be_widened_or_supplied_as_booleans(self):
        f = self.f
        for limits in ({"max_cycles": True}, {"max_items": 2}, {"max_seconds": 3601}, {"max_cycles": 0}):
            with self.subTest(limits=limits), self.assertRaises(supervisor.SupervisorError):
                f.supervisor().observe(**limits)
        self.assertEqual(f.http.requests, [])
        self.assertFalse((f.runtime / ".azure-supervisor").exists())

    def test_claim_concurrency_rejects_second_controller_before_read(self):
        f = self.f
        first = f.supervisor()
        with first.store.locked(), self.assertRaisesRegex(supervisor.SupervisorError, "another supervisor"):
            f.supervisor().observe()
        self.assertEqual(f.http.requests, [])
        self.assertEqual(f.runner.calls, [])

    def test_state_root_inside_git_or_symlink_is_rejected_before_native_read(self):
        f = self.f
        (f.runtime / ".git").mkdir()
        with self.assertRaisesRegex(supervisor.SupervisorError, "outside Git"):
            f.supervisor().observe()
        (f.runtime / ".git").rmdir()
        target = f.home / "other-state"
        target.mkdir()
        (f.runtime / ".azure-supervisor").symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(supervisor.SupervisorError, "symlink"):
            f.supervisor().observe()
        self.assertEqual(f.http.requests, [])

    def test_malformed_durable_progress_is_blocked_before_child_or_native_read(self):
        f = self.f
        controller = f.supervisor()
        key = "item-" + canonical_digest({"repository_url": f.config.repository["url"], "id": f.packet["id"]})
        with controller.store.locked():
            controller.store.write(key, {"schema_version": 1, "id": f.packet["id"], "child_evidence": None, "unchanged_observations": 0})
        with self.assertRaisesRegex(supervisor.SupervisorError, "progress fields"):
            controller.observe()
        self.assertEqual(f.http.requests, [])

    def test_missing_symlink_or_oversized_acceptance_cannot_keep_prepared_state(self):
        f = self.f
        directory = self.prepared()
        path = directory / "unit.json"
        original = path.read_bytes()
        roles = f.runner.roles()
        target = f.home / "not-evidence.json"
        target.write_bytes(original)
        for mutation in ("missing", "symlink", "oversized"):
            with self.subTest(mutation=mutation):
                path.unlink()
                if mutation == "symlink":
                    path.symlink_to(target)
                elif mutation == "oversized":
                    path.write_bytes(b" " * 2_000_001)
                result = f.supervisor().observe(max_cycles=1)
                self.assertEqual(result["items"][0]["state"], "blocked", result)
                self.assertEqual(f.runner.roles(), roles)
                if path.is_symlink() or path.exists():
                    path.unlink()
                path.write_bytes(original)

    def test_corrupt_role_receipt_cannot_keep_prepared_state(self):
        f = self.f
        directory = self.prepared()
        path = directory / "planning-0.json"
        value = json.loads(path.read_text())
        value["decision"] = "fail"
        path.write_text(json.dumps(value))
        roles = f.runner.roles()
        result = f.supervisor().observe(max_cycles=1)
        self.assertEqual(result["items"][0]["state"], "blocked", result)
        self.assertEqual(f.runner.roles(), roles)

    def test_prepared_observation_does_not_require_expired_execution_grant(self):
        f = self.f
        self.prepared()
        f.now += 172800
        roles = f.runner.roles()
        result = f.supervisor().observe(max_cycles=1)
        self.assertEqual(result["items"][0]["state"], "prepared", result)
        self.assertEqual(f.runner.roles(), roles)

    def test_stale_positive_native_snapshot_cannot_reconfirm_prepared_progress(self):
        f = self.f
        self.prepared()
        snapshot = f.provider.inspect([f.packet["id"]], expected_manifest=f.packet["expected_manifest"], authority=f.packet["inspection_authority"], fresh=True)
        f.now += 301
        roles = f.runner.roles()
        with mock.patch.object(f.provider, "inspect", return_value=snapshot):
            result = f.supervisor().observe(max_cycles=1)
        self.assertEqual(result["items"][0]["state"], "blocked", result)
        self.assertEqual(f.runner.roles(), roles)

    def test_changed_code_identity_cannot_erase_prepared_pin_after_two_resumes(self):
        f = self.f
        self.prepared()
        original = f.supervisor_state()
        identity = f.supervisor()._identity() | {"code_sha256": "d" * 64}
        for _ in range(2):
            controller = f.supervisor()
            with mock.patch.object(controller, "_identity", return_value=identity):
                result = controller.observe(max_cycles=1)
            self.assertEqual(result["items"][0]["state"], "conflict", result)
            self.assertEqual(f.supervisor_state()["code_sha256"], original["code_sha256"])

    def test_native_filled_packet_revision_is_preserved_in_publication_request(self):
        f = self.f
        f.definition["worker_packet"] = deepcopy(f.packet)
        del f.definition["worker_packet"]["revision"]
        f.queue["items"][0]["actions"].append("draft_pr")
        self.prepared()
        result = f.supervisor().observe(max_cycles=1)
        self.assertEqual(result["items"][0]["state"], "waiting_authority", result)
        request = f.operation_request(result, "draft_pr")
        self.assertEqual(request["issue_revision"], 7)
        self.assertEqual(request["details"]["candidate_sha"], "b" * 40)
        self.assertEqual(request["bindings"]["packet_sha256"], canonical_digest(f.packet))
        self.assertNotIn("revision", f.queue["items"][0]["definition"]["worker_packet"])

    def test_fake_success_without_durable_parent_journal_is_uncertain_and_not_replayed(self):
        f = self.f
        pending = f.supervisor().observe(max_cycles=1)
        f.accept(f.operation_request(pending, "assess"))
        with mock.patch.object(dispatch.AzureDispatcher, "assess", return_value={"state": "assessed", "completion": False}) as child:
            first = f.supervisor().run(max_cycles=1)
            second = f.supervisor().run(max_cycles=1)
        self.assertEqual(first["items"][0]["state"], "uncertain", first)
        self.assertEqual(second["items"][0]["state"], "uncertain", second)
        self.assertEqual(child.call_count, 1)
        self.assertEqual(f.runner.calls, [])

    def test_dependency_proposal_reads_real_expanded_fields_and_preserves_human_fields(self):
        f = self.f
        client = self.graph()
        before = deepcopy(client.items)
        result = f.supervisor().observe(max_cycles=1)
        diff = result["items"][0]["dependency_diff"]
        self.assertEqual(diff["preparation_status"], "prepared_unapproved", result)
        self.assertEqual(diff["missing"], [[f.packet["id"], board_fixture.ident(18)]])
        proposal = json.loads(Path(diff["proposal_path"]).read_text())
        self.assertEqual(reconcile.validate_proposal(proposal, now=f.now), diff["proposal_sha256"])
        self.assertEqual(proposal["execution_eligibility"], "blocked")
        self.assertEqual(proposal["operator_owned_tags"], [])
        self.assertEqual(proposal["baseline"][f.packet["id"]]["tags"], "human-tag")
        self.assertEqual(proposal["baseline"][f.packet["id"]]["immutable_fields_sha256"], reconcile.project_item(before[17], "Instablinds", "Instablinds")["immutable_fields_sha256"])
        self.assertNotIn("PRIVATE DESCRIPTION", Path(diff["proposal_path"]).read_text())
        self.assertNotIn("PRIVATE IDENTITY", Path(diff["proposal_path"]).read_text())
        self.assertEqual([operation["path"] for operation in proposal["patches"][0]["json_patch"]], ["/rev", "/relations/-"])
        self.assertEqual(client.items, before)
        self.assertEqual(client.writes, [])
        self.assertEqual(f.runner.calls, [])
        self.assertEqual(result["requests"], [])
        first_sha = diff["proposal_sha256"]
        f.now += 1
        client.now = f.now
        client.observed_at = azure.timestamp(f.now)
        repeat = f.supervisor().observe(max_cycles=1)
        self.assertEqual(repeat["items"][0]["dependency_diff"]["proposal_sha256"], first_sha)

    def test_dependency_proposal_requires_raw_client_and_never_fabricates_hashes(self):
        f = self.f
        self.graph()
        snapshot = f.provider.inspect([f.packet["id"]], expected_manifest=f.packet["expected_manifest"], authority=f.packet["inspection_authority"], fresh=True)
        f.client = None
        f.provider = mock.Mock(spec=["inspect"])
        f.provider.inspect.return_value = snapshot
        result = f.supervisor().observe(max_cycles=1)
        diff = result["items"][0]["dependency_diff"]
        self.assertEqual(diff["preparation_status"], "blocked", result)
        self.assertIn("raw-item client", diff["preparation_blocker"])
        self.assertNotIn("proposal_path", diff)
        self.assertEqual(list((f.runtime / ".azure-supervisor").glob("proposal-*.json")), [])

    def test_exact_signed_board_child_uses_native_revision_and_reconciles_without_replay(self):
        f = self.f
        client = self.graph()
        f.config = replace(f.config, capabilities=f.config.capabilities | {"board_write"})
        del f.packet["revision"]
        initial = f.supervisor().observe(max_cycles=1)
        proposal = json.loads(Path(initial["items"][0]["dependency_diff"]["proposal_path"]).read_text())
        f.queue["items"][0]["proposal"] = proposal
        f.queue["items"][0]["actions"] = ["board_write"]
        pending = f.supervisor().observe(max_cycles=1)
        request = f.operation_request(pending, "board_write")
        self.assertEqual(request["issue_revision"], 7)
        self.assertEqual(request["details"]["board_patches"], proposal["patches"])
        self.assertNotIn("revision", f.packet)
        self.assertEqual(client.writes, [])
        f.accept(request)
        original = reconcile.apply_proposal
        def result_lost(*args, **kwargs):
            original(*args, **kwargs)
            raise TimeoutError("lost completed Board child response")
        with mock.patch.object(reconcile, "apply_proposal", side_effect=result_lost) as apply:
            uncertain = f.supervisor().run(max_cycles=1)
            recovered = f.supervisor().observe(max_cycles=1)
            repeated = f.supervisor().run(max_cycles=1)
        self.assertEqual(uncertain["items"][0]["state"], "uncertain", uncertain)
        self.assertEqual(recovered["items"][0]["state"], "board_reconciled", recovered)
        self.assertEqual(repeated["items"][0]["state"], "board_reconciled", repeated)
        self.assertEqual(apply.call_count, 1)
        self.assertEqual(len(client.writes), 1)
        self.assertEqual(client.items[17]["rev"], 8)
        self.assertEqual(client.items[18]["rev"], 8)
        self.assertEqual(client.items[17]["fields"]["System.Tags"], "human-tag")
        self.assertEqual(client.items[17]["fields"]["System.State"], "To Do")
        self.assertEqual(f.runner.calls, [])
        self.assertFalse(repeated["completion"])
        self.assertEqual(f.supervisor_state()["operation"]["state"], "verified")
        self.assertEqual(f.supervisor_state()["operation"]["request_revision"], pending["requests"][0]["card"]["revision"])

    def test_stale_raw_revision_blocks_proposal_and_retains_precise_missing_diff(self):
        f = self.f
        client = self.graph()
        snapshot = f.provider.inspect([f.packet["id"]], expected_manifest=f.packet["expected_manifest"], authority=f.packet["inspection_authority"], fresh=True)
        client.items[18]["rev"] += 1
        with mock.patch.object(f.provider, "inspect", return_value=snapshot):
            result = f.supervisor().observe(max_cycles=1)
        diff = result["items"][0]["dependency_diff"]
        self.assertEqual(diff["preparation_status"], "blocked", result)
        self.assertIn("revisions changed", diff["preparation_blocker"])
        self.assertEqual(diff["missing"], [[f.packet["id"], board_fixture.ident(18)]])
        self.assertEqual(client.writes, [])

    def test_raw_incomplete_cache_hit_and_missing_endpoint_each_block_proposal(self):
        f = self.f
        client = self.graph()
        snapshot = f.provider.inspect([f.packet["id"]], expected_manifest=f.packet["expected_manifest"], authority=f.packet["inspection_authority"], fresh=True)
        for failure in ("incomplete", "cached", "omitted"):
            raw = azure.ReadCollection(items=list(deepcopy(client.items).values()), complete=True, observed_at=azure.timestamp(f.now))
            if failure == "incomplete":
                raw.complete = False
            elif failure == "cached":
                raw.cache_hit = True
            else:
                raw.items.pop()
            with self.subTest(failure=failure), mock.patch.object(f.provider, "inspect", return_value=snapshot), mock.patch.object(client, "get_work_items", return_value=raw):
                result = f.supervisor().observe(max_cycles=1)
            diff = result["items"][0]["dependency_diff"]
            self.assertEqual(diff["preparation_status"], "blocked", result)
            self.assertNotIn("proposal_path", diff)
        self.assertEqual(client.writes, [])

    def test_two_queue_items_share_one_native_inspection_per_cycle(self):
        f = self.f
        self.graph(missing=False)
        second = deepcopy(f.queue["items"][0])
        second["id"] = board_fixture.ident(18)
        second["definition"]["worker_packet"]["id"] = second["id"]
        f.queue["items"].append(second)
        f.queue["limits"]["max_items"] = 2
        with mock.patch.object(f.provider, "inspect", wraps=f.provider.inspect) as inspect:
            first = f.supervisor().observe(max_cycles=1)
            second_result = f.supervisor().observe(max_cycles=1)
        self.assertEqual(inspect.call_count, 2)
        self.assertEqual(inspect.call_args.args[0], [f.packet["id"], second["id"]])
        self.assertEqual(len(first["items"]), 2)
        self.assertEqual(len(second_result["items"]), 2)  # An unchanged first item cannot starve the second.
        self.assertEqual(second_result["stop_reason"], "two_unchanged_observations")
        self.assertEqual(f.runner.calls, [])

    def test_unsupported_or_duplicate_native_queue_cannot_reach_preview(self):
        f = self.f
        for mutation in ("merge", "duplicate", "other_namespace"):
            queue = deepcopy(f.queue)
            if mutation == "merge":
                queue["items"][0]["actions"] = ["merge"]
            elif mutation == "duplicate":
                queue["items"] *= 2
            else:
                queue["items"][0]["id"] = "azdo:Other:Instablinds:17"
            with self.subTest(mutation=mutation), self.assertRaises(supervisor.SupervisorError):
                supervisor.AzureSupervisor(f.config, f.policy, queue)

    def test_entrypoint_help_without_bytecode_flag_creates_no_files(self):
        f = self.f
        directory = f.home / "source-copy"
        directory.mkdir()
        for source in ROOT.glob("atlas_*.py"):
            shutil.copyfile(source, directory / source.name)
        shutil.copyfile(ROOT / "atlas-agent-azure-supervise", directory / "atlas-agent-azure-supervise")
        before = sorted(str(path.relative_to(directory)) for path in directory.rglob("*"))
        result = subprocess.run([sys.executable, str(directory / "atlas-agent-azure-supervise"), "--help"], capture_output=True, text=True, check=False, timeout=10,
                                env={"PATH": os.environ.get("PATH", ""), "HOME": str(f.home)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--observe", result.stdout)
        self.assertIn("--run", result.stdout)
        self.assertEqual(sorted(str(path.relative_to(directory)) for path in directory.rglob("*")), before)


if __name__ == "__main__":
    unittest.main()
