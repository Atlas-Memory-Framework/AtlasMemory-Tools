from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
from dataclasses import replace
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import atlas_azure_reconcile as reconcile
from atlas_azure_devops import AzureError, AzureRevisionConflict, AzureUncertainWrite, ReadCollection, timestamp


ORG = PROJECT = "Instablinds"
PROJECT_GUID = "11111111-2222-3333-4444-555555555555"
OTHER_GUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def ident(number):
    return f"azdo:{ORG}:{PROJECT}:{number}"


def relation(number, kind=reconcile.PREDECESSOR, **attributes):
    return {"rel": kind, "url": f"https://dev.azure.com/{ORG}/_apis/wit/workItems/{number}", "attributes": attributes}


def project_guid_urls(items, alias=PROJECT_GUID):
    """Synthetic native self/relation shape; no live item payload is persisted."""
    for row in items:
        row["url"] = f"https://dev.azure.com/{ORG}/{alias}/_apis/wit/workItems/{row['id']}"
        for link in row["relations"]:
            if link["rel"] in {reconcile.PREDECESSOR, reconcile.SUCCESSOR}:
                number = link["url"].rsplit("/", 1)[1]
                link["url"] = f"https://dev.azure.com/{ORG}/{alias}/_apis/wit/workItems/{number}"


def item(number, **fields):
    return {
        "id": number, "rev": 3,
        "fields": {"System.State": "To Do", "System.TeamProject": PROJECT, "System.Tags": "human-tag",
                   "System.AssignedTo": {"displayName": "PRIVATE IDENTITY", "uniqueName": "DO NOT PERSIST"},
                   "System.Description": "PRIVATE DESCRIPTION", **fields},
        "relations": [relation(3, "System.LinkTypes.Hierarchy-Reverse")],
    }


def spec(changes, dependencies=(), owned=("atlas:prepared",)):
    return {"operator_owned_tags": list(owned), "approved_dependencies": [{"issue_id": ident(target), "predecessor": ident(prerequisite)} for target, prerequisite in dependencies], "changes": changes}


class FakeClient:
    """Model Azure's atomic revision test and reciprocal revision increments."""

    organization = ORG
    project = PROJECT

    def __init__(self, items, now):
        self.items = {row["id"]: deepcopy(row) for row in items}
        self.now = now
        self.reads = []
        self.writes = []
        self.outcomes = []
        self.read_hook = None
        self.before_patch = None
        self.complete = True
        self.observed_at = timestamp(now)

    def get_work_items(self, ids, *, fresh=False):
        assert fresh, "reconciliation must bypass cached reads"
        self.reads.append(list(ids))
        if self.read_hook:
            self.read_hook(self)
        return ReadCollection(items=[deepcopy(self.items[number]) for number in ids if number in self.items], complete=self.complete, blockers=[], observed_at=self.observed_at)

    def request_response(self, method, path, *, data, query, capability, fresh, headers, before_write):
        assert method == "PATCH" and capability == "board_write" and fresh
        assert headers["Content-Type"] == "application/json-patch+json"
        number = int(path.rsplit("/", 1)[1])
        if self.before_patch:
            self.before_patch(self, number)
        before_write()
        self.writes.append((number, deepcopy(data)))
        outcome = self.outcomes.pop(0) if self.outcomes else "ok"
        if outcome == "uncertain_absent":
            raise AzureUncertainWrite()
        if outcome == "conflict" or self.items[number]["rev"] != data[0]["value"]:
            raise AzureRevisionConflict(412)
        assert data[0]["op"] == "test" and data[0]["path"] == "/rev"
        for operation in data[1:]:
            if operation["path"].startswith("/fields/"):
                self.items[number]["fields"][operation["path"].split("/", 2)[2]] = operation["value"]
            elif operation["path"] == "/relations/-":
                predecessor = int(operation["value"]["url"].rsplit("/", 1)[1])
                self.items[number]["relations"].append(relation(predecessor, name="Predecessor", isLocked=False))
                if outcome != "missing_reciprocal":
                    self.items[predecessor]["relations"].append(relation(number, reconcile.SUCCESSOR, name="Successor", isLocked=False))
                    self.items[predecessor]["rev"] += 1
            else:
                raise AssertionError("unexpected mutation")
        self.items[number]["rev"] += 1
        if outcome in {"uncertain_accepted", "missing_reciprocal"}:
            raise AzureUncertainWrite()
        return None


class AzureReconcileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.runtime = Path(self.temporary.name)
        self.now = time.time()
        self.items = [item(16), item(17), item(18)]
        self.client = FakeClient(self.items, self.now)
        self.config = reconcile.RuntimeConfig(provider="azure-devops", runtime_dir=self.runtime,
            repository={"organization": ORG, "project": PROJECT, "name": "Website", "base_branch": "develop",
                        "url": "https://dev.azure.com/Instablinds/Instablinds/_git/Website"},
            capabilities=frozenset({"read", "board_write"}), roles={}, source="explicit-test-fixture")
        from atlas_runtime_config import ROLES, RoleSettings
        self.config = replace(self.config, roles={role: RoleSettings("gpt-6-astra", "max", "test") for role in ROLES})
        # Existing reconciliation regressions explicitly isolate authorization.
        # AzureReconcileAuthorityTests below use real signatures and public trust.
        self.authority_patcher = mock.patch.object(reconcile, "verify_grant", side_effect=self.behavioral_authority)
        self.authority_mock = self.authority_patcher.start()
        self.addCleanup(self.authority_patcher.stop)
        self.human_authority_patcher = mock.patch("atlas_human_gates.verify_grant", return_value={"subject": "operator"})
        self.human_authority_patcher.start()
        self.addCleanup(self.human_authority_patcher.stop)

    @staticmethod
    def behavioral_authority(runtime, envelope, action, bindings, **kwargs):
        if not isinstance(envelope, dict) or envelope.get("action") != action or reconcile.canonical_sha256(envelope.get("bindings")) != reconcile.canonical_sha256(bindings):
            raise reconcile.AuthorityError("explicitly mocked behavioral authority does not match")
        return {"subject": "operator"}

    def proposal(self, changes=None, dependencies=(), items=None):
        return reconcile.build_proposal(
            {"complete": True, "observed_at": self.now, "items": items or self.items},
            spec(changes or [{"issue_id": ident(16), "add_tags": ["atlas:prepared"]}], dependencies),
            ORG, PROJECT, now=self.now,
        )

    def apply(self, proposal, **kwargs):
        # The provider module separately tests actual passwd-home path ownership.
        with mock.patch.object(reconcile, "validate_runtime_path", return_value=self.runtime):
            return reconcile.apply_proposal(proposal, self.client, runtime_dir=self.runtime,
                                            authorized_sha256=kwargs.pop("authorized_sha256", reconcile.canonical_sha256(proposal)),
                                            capabilities=kwargs.pop("capabilities", {"read", "board_write"}),
                                            config=kwargs.pop("config", self.config),
                                            authorization=kwargs.pop("authorization", {"action": "board_write", "bindings": reconcile.authorization_bindings(proposal, self.config, self.runtime)}),
                                            clock=lambda: self.now, **kwargs)

    def config_file(self):
        path = self.runtime / "config.json"
        path.write_text(json.dumps({
            "schema_version": 1, "provider": "azure-devops", "capabilities": ["read", "board_write"],
            "repository": {"organization": ORG, "project": PROJECT, "name": "Website", "base_branch": "develop", "url": "https://dev.azure.com/Instablinds/Instablinds/_git/Website"},
            "models": {"default": {"model": "gpt-6-astra", "reasoning": "max"}},
            "sandbox": "workspace-write", "approval_policy": "on-request",
        }))
        return path

    def closure(self, *, commands=None, status="passed", scope="release"):
        release = {"environment": "Staging", "pipeline_definition_id": 8, "run_id": 202,
                   "source_version": "1" * 40, "artifact_sha256": "2" * 64, "package_sha256": "3" * 64,
                   "assets_sha256": "4" * 64, "database_revision": "schema-7"}
        artifact = {"schema_version": 1, "kind": "acceptance", "issue_id": ident(16), "scope": scope,
                    "status": status, "candidate": "1" * 40, "contract_sha256": "a" * 64,
                    "check": "authenticated-storefront", "acceptance_satisfied": True, "release": release,
                    "commands": commands if commands is not None else [{"argv": ["python3", "qualify.py"], "executed": True, "exit_code": 0}]}
        evidence_dir = self.runtime / "evidence"
        evidence_dir.mkdir(exist_ok=True)
        artifact_path = evidence_dir / "qualification.json"
        artifact_path.write_text(json.dumps(artifact))
        evidence_hash = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        acceptance = {"issue_id": ident(16), "status": "accepted", "scope": scope, "candidate": "1" * 40,
                      "contract_sha256": "a" * 64, "required_checks": ["authenticated-storefront"],
                      "evidence": [{"check": "authenticated-storefront", "path": "evidence/qualification.json", "sha256": evidence_hash}],
                      "human_accepted": True, "release": release}
        acceptance["human_gate"] = {"id": "release-acceptance", "kind": "test", "owner": "operator",
                                    "question": "Do the recorded tests accept this exact release candidate?",
                                    "stage": "before", "action": "completion", "issue_id": ident(16), "issue_revision": 3,
                                    "candidate_sha": "1" * 40, "artifact_sha256": reconcile.acceptance_contract_sha256(acceptance)}
        acceptance["human_receipt"] = {"gate_id": "release-acceptance", "decision": "accepted", "response": "Reviewed fixture acceptance", "grant": {"mocked_human_gate": True}}
        return {"issue_id": ident(16), "state_transition": {"to_state": "Done", "acceptance": acceptance}}, artifact_path

    def test_proposal_and_receipt_never_persist_raw_description_or_identity(self):
        proposal = self.proposal()
        result = self.apply(proposal)
        serialized = json.dumps(proposal) + json.dumps(result) + next((self.runtime / "azure-reconcile").glob("*.json")).read_text()
        for private in ("PRIVATE DESCRIPTION", "PRIVATE IDENTITY", "DO NOT PERSIST", "System.AssignedTo", "System.Description"):
            self.assertNotIn(private, serialized)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["execution_eligibility"], "blocked")
        self.assertFalse(result["release_completion_inferred"])

    def test_exact_tags_patch_preserves_assignee_state_epic_and_unrelated_tags(self):
        original = deepcopy(self.client.items[16])
        self.apply(self.proposal())
        expected = deepcopy(original)
        expected["rev"] += 1
        expected["fields"]["System.Tags"] = "human-tag; atlas:prepared"
        self.assertEqual(self.client.items[16], expected)
        self.assertEqual(self.client.writes[0][1], [{"op": "test", "path": "/rev", "value": 3}, {"op": "add", "path": "/fields/System.Tags", "value": "human-tag; atlas:prepared"}])

    def test_serial_dependency_patches_include_reciprocal_revision_increment(self):
        proposal = self.proposal([
            {"issue_id": ident(16), "add_predecessors": [ident(17)]},
            {"issue_id": ident(17), "add_predecessors": [ident(18)]},
        ], [(16, 17), (17, 18)])
        self.assertEqual([row["json_patch"][0]["value"] for row in proposal["patches"]], [3, 4])
        result = self.apply(proposal)
        self.assertEqual(result["status"], "applied")
        self.assertEqual([self.client.items[number]["rev"] for number in (16, 17, 18)], [4, 5, 4])
        self.assertTrue(all(set(read) == {16, 17, 18} for read in self.client.reads))

    def test_existing_native_dependencies_are_idempotent_and_not_added_twice(self):
        self.items[0]["relations"].append(relation(17))
        self.items[1]["relations"].append(relation(16, reconcile.SUCCESSOR))
        self.client = FakeClient(self.items, self.now)
        proposal = self.proposal([{"issue_id": ident(16), "add_predecessors": [ident(17)]}], [(16, 17)])
        self.assertEqual(proposal["patches"], [])
        self.assertEqual(self.apply(proposal)["status"], "no_changes")
        self.assertEqual(self.client.writes, [])

    def test_dependency_addition_cannot_expand_beyond_the_exact_approved_edges(self):
        with self.assertRaisesRegex(reconcile.ReconcileError, "authorization"):
            self.proposal([{"issue_id": ident(16), "add_predecessors": [ident(17), ident(18)]}], [(16, 17)])
        self.assertEqual(self.client.writes, [])

    def test_namespace_cycles_and_incomplete_reciprocal_snapshots_fail_closed(self):
        with self.assertRaisesRegex(reconcile.ReconcileError, "namespace"):
            self.proposal([{"issue_id": "azdo:Other:Instablinds:16"}])
        with self.assertRaisesRegex(reconcile.ReconcileError, "cycle"):
            self.proposal([{"issue_id": ident(16), "add_predecessors": [ident(17)]}, {"issue_id": ident(17), "add_predecessors": [ident(16)]}], [(16, 17), (17, 16)])
        self.items[0]["relations"].append(relation(17))
        with self.assertRaisesRegex(reconcile.ReconcileError, "reciprocal"):
            self.proposal()

    def test_operator_owned_tag_allowlist_and_exact_patch_integrity(self):
        with self.assertRaisesRegex(reconcile.ReconcileError, "ownership"):
            self.proposal([{"issue_id": ident(16), "remove_tags": ["human-tag"]}])
        proposal = self.proposal()
        proposal["patches"][0]["json_patch"].append({"op": "add", "path": "/fields/System.AssignedTo", "value": "Someone"})
        with self.assertRaisesRegex(reconcile.ReconcileError, "exact patches"):
            self.apply(proposal)
        self.assertFalse((self.runtime / "azure-reconcile").exists())

    def test_apply_needs_exact_separate_authorization_before_any_local_changes(self):
        proposal = self.proposal()
        for kwargs in ({"authorized_sha256": "0" * 64}, {"capabilities": {"read"}}, {"capabilities": {"board_write"}}):
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(reconcile.ReconcileError, "capabilities"):
                self.apply(proposal, **kwargs)
        self.assertEqual(self.client.reads, [])
        self.assertEqual(list(self.runtime.iterdir()), [])

    def test_stale_proposal_and_fresh_reads_with_missing_items_or_old_timestamps(self):
        proposal = self.proposal()
        proposal["observed_at"] -= 1000
        with self.assertRaisesRegex(reconcile.ReconcileError, "stale"):
            self.apply(proposal)
        proposal = self.proposal()
        self.client.complete = False
        with self.assertRaisesRegex(reconcile.ReconcileError, "complete"):
            self.apply(proposal)
        self.client.complete = True
        self.client.observed_at = timestamp(self.now - 30)
        with self.assertRaisesRegex(reconcile.ReconcileError, "fresh"):
            self.apply(proposal)
        self.client.observed_at = timestamp(self.now)
        del self.client.items[18]
        with self.assertRaisesRegex(reconcile.ReconcileError, "omitted"):
            self.apply(proposal)
        self.assertEqual(self.client.writes, [])

    def test_unexpanded_snapshot_and_cross_project_endpoint_are_rejected(self):
        del self.items[0]["relations"]
        with self.assertRaisesRegex(reconcile.ReconcileError, "expanded relations"):
            self.proposal()
        self.items[0]["relations"] = [relation(17)]
        self.items[1]["fields"]["System.TeamProject"] = "Other"
        with self.assertRaisesRegex(reconcile.ReconcileError, "configured project"):
            self.proposal()

    def test_verified_native_project_guid_relations_preserve_exact_revision_and_human_fields(self):
        self.items[0]["relations"].append(relation(17, name="Predecessor", comment="human relation note"))
        self.items[1]["relations"].append(relation(16, reconcile.SUCCESSOR, name="Successor"))
        project_guid_urls(self.items)
        self.client = FakeClient(self.items, self.now)
        original = deepcopy(self.client.items)
        proposal = self.proposal()
        projection = proposal["baseline"][ident(16)]
        dependency = next(row for row in projection["relations"] if row["kind"] == "predecessor")
        self.assertEqual(dependency["target"], ident(17))
        self.assertEqual(dependency["sha256"], reconcile.canonical_sha256(self.items[0]["relations"][-1]))
        self.assertEqual(projection["revision"], 3)
        result = self.apply(proposal)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(self.client.writes[0][1][0], {"op": "test", "path": "/rev", "value": 3})
        expected = deepcopy(original)
        expected[16]["rev"] += 1
        expected[16]["fields"]["System.Tags"] = "human-tag; atlas:prepared"
        self.assertEqual(self.client.items, expected)
        self.assertNotIn("PRIVATE DESCRIPTION", json.dumps(proposal))
        self.assertEqual(result["execution_eligibility"], "blocked")

    def test_guid_native_baseline_accepts_revision_tested_addition_with_org_scoped_readback(self):
        project_guid_urls(self.items)
        self.client = FakeClient(self.items, self.now)
        proposal = self.proposal([{"issue_id": ident(16), "add_predecessors": [ident(17)]}], [(16, 17)])
        result = self.apply(proposal)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(self.client.items[16]["rev"], 4)
        self.assertEqual(self.client.items[17]["rev"], 4)
        self.assertEqual(self.client.items[16]["fields"]["System.Tags"], "human-tag")
        self.assertEqual(len(self.client.writes), 1)
        self.assertEqual(self.client.writes[0][1][0]["path"], "/rev")

    def test_guid_relation_requires_exact_self_verified_project_alias(self):
        self.items[0]["relations"].append(relation(17))
        self.items[1]["relations"].append(relation(16, reconcile.SUCCESSOR))
        project_guid_urls(self.items)
        for change in (lambda rows: rows[0].pop("url"),
                       lambda rows: rows[0]["relations"][-1].update(url=f"https://dev.azure.com/{ORG}/{OTHER_GUID}/_apis/wit/workItems/17")):
            with self.subTest(change=change):
                changed = deepcopy(self.items)
                change(changed)
                with self.assertRaises(reconcile.ReconcileError):
                    self.proposal(items=changed)
        self.assertEqual(self.client.writes, [])

    def test_guid_self_url_cannot_substitute_organization_item_kind_or_item_id(self):
        project_guid_urls(self.items)
        urls = [f"https://dev.azure.com/Other/{PROJECT_GUID}/_apis/wit/workItems/16",
                f"https://dev.azure.com/{ORG}/{PROJECT_GUID}/_apis/wit/queries/16",
                f"https://dev.azure.com/{ORG}/{PROJECT_GUID}/_apis/wit/workItems/17",
                f"https://dev.azure.com/{ORG}/{PROJECT_GUID}/_apis/wit/workItems/16?unreviewed=1"]
        for url in urls:
            with self.subTest(url=url):
                changed = deepcopy(self.items)
                changed[0]["url"] = url
                with self.assertRaises(reconcile.ReconcileError):
                    self.proposal(items=changed)

    def test_mixed_project_guids_in_a_complete_named_project_snapshot_are_rejected(self):
        project_guid_urls(self.items)
        self.items[1]["url"] = self.items[1]["url"].replace(PROJECT_GUID, OTHER_GUID)
        with self.assertRaises(reconcile.ReconcileError):
            self.proposal()
        self.assertEqual(self.client.writes, [])

    def test_project_guid_is_bound_across_proposal_and_fresh_readback(self):
        project_guid_urls(self.items)
        self.client = FakeClient(self.items, self.now)
        proposal = self.proposal()
        project_guid_urls(list(self.client.items.values()), OTHER_GUID)
        with self.assertRaises(reconcile.ReconcileError):
            self.apply(proposal)
        self.assertEqual(self.client.writes, [])

    def test_mixed_project_guids_during_fresh_read_are_rejected_before_patch(self):
        project_guid_urls(self.items)
        self.client = FakeClient(self.items, self.now)
        proposal = self.proposal()
        self.client.items[17]["url"] = self.client.items[17]["url"].replace(PROJECT_GUID, OTHER_GUID)
        with self.assertRaises(reconcile.ReconcileError):
            self.apply(proposal)
        self.assertEqual(self.client.writes, [])

    def test_guid_relation_never_replaces_target_team_project_or_reciprocal_read_checks(self):
        self.items[0]["relations"].append(relation(17))
        self.items[1]["relations"].append(relation(16, reconcile.SUCCESSOR))
        project_guid_urls(self.items)
        changed = deepcopy(self.items)
        changed[1]["fields"]["System.TeamProject"] = "Other"
        with self.assertRaises(reconcile.ReconcileError):
            self.proposal(items=changed)
        changed = deepcopy(self.items)
        changed[1]["relations"] = []
        with self.assertRaises(reconcile.ReconcileError):
            self.proposal(items=changed)

    def test_human_change_before_apply_does_not_get_overwritten(self):
        proposal = self.proposal()
        self.client.items[16]["fields"]["System.Tags"] += "; human-later"
        self.client.items[16]["rev"] += 1
        with self.assertRaisesRegex(reconcile.ReconcileError, "stale"):
            self.apply(proposal)
        self.assertEqual(self.client.writes, [])
        self.assertIn("human-later", self.client.items[16]["fields"]["System.Tags"])

    def test_bare_revision_drift_is_rejected_even_if_fields_are_unchanged(self):
        proposal = self.proposal()
        self.client.items[16]["rev"] += 1
        with self.assertRaisesRegex(reconcile.ReconcileError, "stale"):
            self.apply(proposal)
        self.assertEqual(self.client.writes, [])

    def test_concurrent_human_edit_after_last_read_hits_rev_test_and_never_replays(self):
        proposal = self.proposal()
        def human_edit(client, number):
            client.items[number]["fields"]["System.State"] = "In Progress"
            client.items[number]["rev"] += 1
        self.client.before_patch = human_edit
        with self.assertRaisesRegex(reconcile.ReconcileError, "revision conflict"):
            self.apply(proposal)
        self.client.before_patch = None
        with self.assertRaisesRegex(reconcile.ReconcileError, "conflicted"):
            self.apply(proposal)
        self.assertEqual(len(self.client.writes), 1)
        self.assertEqual(self.client.items[16]["fields"]["System.State"], "In Progress")

    def test_unknown_accepted_write_reconciles_both_ends_without_replay(self):
        proposal = self.proposal([{"issue_id": ident(16), "add_predecessors": [ident(17)]}], [(16, 17)])
        self.client.outcomes = ["uncertain_accepted"]
        self.assertEqual(self.apply(proposal)["status"], "applied")
        self.assertEqual(self.apply(proposal)["status"], "already_applied")
        self.assertEqual(len(self.client.writes), 1)
        self.assertEqual(len(self.client.items[16]["relations"]), 2)
        self.assertEqual(len(self.client.items[17]["relations"]), 2)

    def test_unknown_absent_write_returns_blocked_and_requires_a_new_apply_call(self):
        proposal = self.proposal()
        self.client.outcomes = ["uncertain_absent"]
        self.assertEqual(self.apply(proposal)["status"], "uncertain_unapplied")
        self.assertEqual(len(self.client.writes), 1)
        self.assertEqual(self.client.items[16]["rev"], 3)
        self.assertEqual(self.apply(proposal)["status"], "applied")
        self.assertEqual(len(self.client.writes), 2)
        self.assertEqual(self.client.items[16]["rev"], 4)

    def test_restart_after_write_before_readback_reconciles_pending_intent(self):
        proposal = self.proposal()
        def crash_after_write(client):
            if client.writes:
                raise AzureError("simulated read failure")
        self.client.read_hook = crash_after_write
        with self.assertRaises(AzureError):
            self.apply(proposal)
        self.client.read_hook = None
        self.assertEqual(self.apply(proposal)["status"], "already_applied")
        self.assertEqual(len(self.client.writes), 1)

    def test_unknown_write_with_missing_reciprocal_read_never_reports_success(self):
        proposal = self.proposal([{"issue_id": ident(16), "add_predecessors": [ident(17)]}], [(16, 17)])
        self.client.outcomes = ["missing_reciprocal"]
        with self.assertRaisesRegex(reconcile.ReconcileError, "reciprocal"):
            self.apply(proposal)
        with self.assertRaisesRegex(reconcile.ReconcileError, "reciprocal"):
            self.apply(proposal)
        self.assertEqual(len(self.client.writes), 1)

    def test_successful_write_with_unrelated_side_effect_is_not_marked_verified(self):
        proposal = self.proposal()
        def unexpected_rule(client):
            if client.writes:
                client.items[16]["fields"]["System.AssignedTo"] = "changed-by-rule"
        self.client.read_hook = unexpected_rule
        with self.assertRaisesRegex(reconcile.ReconcileError, "preserved human field"):
            self.apply(proposal)
        receipt = json.loads(next((self.runtime / "azure-reconcile").glob("*.json")).read_text())
        self.assertEqual(receipt["entries"][0]["status"], "conflict")

    def test_known_server_derived_counts_do_not_invalidate_preserved_field_proof(self):
        proposal = self.proposal()
        def update_counts(client):
            if client.writes:
                client.items[16]["fields"]["System.RelatedLinkCount"] = 2
        self.client.read_hook = update_counts
        self.assertEqual(self.apply(proposal)["status"], "applied")

    def test_existing_relation_attributes_cannot_be_silently_replaced(self):
        proposal = self.proposal()
        def unexpected_relation_edit(client):
            if client.writes:
                client.items[16]["relations"][0]["attributes"] = {"comment": "human edit"}
        self.client.read_hook = unexpected_relation_edit
        with self.assertRaisesRegex(reconcile.ReconcileError, "existing relation"):
            self.apply(proposal)

    def test_release_closure_requires_immutable_matching_acceptance_artifact(self):
        change, _ = self.closure()
        self.apply(self.proposal([change]))
        self.assertEqual(self.client.items[16]["fields"]["System.State"], "Done")
        self.assertEqual(self.client.writes[0][1][-1]["path"], "/fields/System.State")

    def test_local_worker_prepared_and_pr_open_states_never_close_release_issue(self):
        for status in ("prepared", "pr_open"):
            with self.subTest(status=status):
                change, _ = self.closure(status=status)
                with self.assertRaisesRegex(reconcile.ReconcileError, "actual acceptance"):
                    self.apply(self.proposal([change]))
        self.assertEqual(self.client.writes, [])
        self.assertEqual(self.client.items[16]["fields"]["System.State"], "To Do")

    def test_missing_commands_evidence_hash_drift_and_missing_artifact_block_closure(self):
        change, path = self.closure(commands=[])
        with self.assertRaisesRegex(reconcile.ReconcileError, "commands"):
            self.apply(self.proposal([change]))
        change, path = self.closure()
        proposal = self.proposal([change])
        path.write_text("{}")
        with self.assertRaisesRegex(reconcile.ReconcileError, "hash changed"):
            self.apply(proposal)
        path.unlink()
        with self.assertRaisesRegex(reconcile.ReconcileError, "unavailable"):
            self.apply(proposal)
        self.assertEqual(self.client.writes, [])

    def test_implementation_scope_and_missing_release_bindings_cannot_close(self):
        change, _ = self.closure(scope="implementation")
        with self.assertRaisesRegex(reconcile.ReconcileError, "accepted release"):
            self.proposal([change])
        change, _ = self.closure()
        del change["state_transition"]["acceptance"]["release"]["run_id"]
        with self.assertRaises(reconcile.ReconcileError):
            self.proposal([change])
        change, _ = self.closure()
        change["state_transition"]["to_state"] = "Resolved"
        with self.assertRaisesRegex(reconcile.ReconcileError, "terminal"):
            self.proposal([change])

    def test_evidence_environment_or_candidate_mismatch_rejects_completion(self):
        change, path = self.closure()
        artifact = json.loads(path.read_text())
        artifact["release"]["environment"] = "Production"
        path.write_text(json.dumps(artifact))
        change["state_transition"]["acceptance"]["evidence"][0]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        change["state_transition"]["acceptance"]["human_gate"]["artifact_sha256"] = reconcile.acceptance_contract_sha256(change["state_transition"]["acceptance"])
        with self.assertRaisesRegex(reconcile.ReconcileError, "actual acceptance"):
            self.apply(self.proposal([change]))

    def test_concurrent_reconciler_fails_busy_without_wait_or_write(self):
        directory = self.runtime / "azure-reconcile"
        directory.mkdir(mode=0o700)
        fd = os.open(directory / ".lock", os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with self.assertRaisesRegex(reconcile.ReconcileError, "another Board reconciliation"):
            self.apply(self.proposal())
        self.assertEqual(self.client.reads, [])
        self.assertEqual(self.client.writes, [])

    def test_state_directory_and_receipt_symlinks_never_write_through(self):
        outside = self.runtime / "outside"
        outside.mkdir()
        (self.runtime / "azure-reconcile").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(reconcile.ReconcileError, "symlink"):
            self.apply(self.proposal())
        self.assertEqual(list(outside.iterdir()), [])
        (self.runtime / "azure-reconcile").unlink()
        (self.runtime / "azure-reconcile").mkdir(mode=0o700)
        target = outside / "untouched.json"
        target.write_text("unchanged")
        packet = self.proposal()
        (self.runtime / "azure-reconcile" / f"{reconcile.canonical_sha256(packet)}.json").symlink_to(target)
        with self.assertRaisesRegex(reconcile.ReconcileError, "private file"):
            self.apply(packet)
        self.assertEqual(target.read_text(), "unchanged")

    def test_preview_never_constructs_client_authenticates_or_creates_runtime_state(self):
        config = self.config_file()
        packet = self.runtime / "proposal.json"
        packet.write_text(json.dumps(self.proposal()))
        before = {str(path.relative_to(self.runtime)): path.read_bytes() for path in self.runtime.rglob("*") if path.is_file()}
        output = io.StringIO()
        with mock.patch("atlas_azure_devops.AzureDevOpsClient", side_effect=AssertionError("preview constructed client")), mock.patch("atlas_azure_devops.azure_cli_headers", side_effect=AssertionError("preview accessed credentials")), redirect_stdout(output):
            self.assertEqual(reconcile.main(["--config", str(config), "--packet", str(packet), "--dry-run"]), 0)
        after = {str(path.relative_to(self.runtime)): path.read_bytes() for path in self.runtime.rglob("*") if path.is_file()}
        self.assertEqual(after, before)
        preview = json.loads(output.getvalue())
        self.assertEqual(preview["mode"], "preview")
        self.assertEqual(preview["configuration"]["models"]["review"]["model"], "gpt-6-astra")

    def test_ordinary_cli_preview_creates_no_bytecode_or_other_files(self):
        script_dir = self.runtime / "isolated-template"
        script_dir.mkdir()
        for filename in ("atlas-agent-azure-reconcile", "atlas_azure_reconcile.py", "atlas_runtime_config.py", "atlas_azure_devops.py", "atlas_authority.py"):
            shutil.copyfile(ROOT / filename, script_dir / filename)
        config = self.config_file()
        packet = self.runtime / "proposal.json"
        packet.write_text(json.dumps(self.proposal()))
        before = sorted(str(path.relative_to(self.runtime)) for path in self.runtime.rglob("*"))
        environment = {key: value for key, value in os.environ.items() if key not in {"PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX"}}
        result = subprocess.run([sys.executable, str(script_dir / "atlas-agent-azure-reconcile"), "--config", str(config), "--packet", str(packet)], capture_output=True, text=True, env=environment, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(sorted(str(path.relative_to(self.runtime)) for path in self.runtime.rglob("*")), before)

    def test_foreign_input_path_rejected_before_filesystem_read(self):
        with mock.patch.object(Path, "resolve", side_effect=AssertionError("foreign path was resolved")):
            with self.assertRaisesRegex(reconcile.ReconcileError, "identity"):
                reconcile._read_local_json("/home/another-identity/private.json")

    def test_cli_invalid_apply_hash_and_contradictory_preview_never_authenticate(self):
        config_path = self.config_file()
        config = replace(reconcile.load_runtime_config(config_path, require_runtime=False), runtime_dir=self.runtime)
        packet = self.runtime / "proposal.json"
        packet.write_text(json.dumps(self.proposal()))
        with mock.patch.object(reconcile, "load_runtime_config", return_value=config), mock.patch("atlas_azure_devops.azure_cli_headers", side_effect=AssertionError("invalid request authenticated")):
            for flags in (["--apply", "--authorize-packet-sha256", "0" * 64], ["--apply", "--dry-run", "--authorize-packet-sha256", "0" * 64]):
                with self.subTest(flags=flags), redirect_stdout(io.StringIO()):
                    self.assertEqual(reconcile.main(["--config", str(config_path), "--packet", str(packet), *flags]), 2)
        self.assertFalse((self.runtime / "azure-reconcile").exists())

    def test_acceptance_artifact_symlink_cannot_read_outside_the_runtime(self):
        change, artifact_path = self.closure()
        with tempfile.TemporaryDirectory() as other_directory:
            outside = Path(other_directory) / "qualification.json"
            outside.write_bytes(artifact_path.read_bytes())
            artifact_path.unlink()
            artifact_path.symlink_to(outside)
            with self.assertRaisesRegex(reconcile.ReconcileError, "runtime identity boundary"):
                self.apply(self.proposal([change]))
        self.assertEqual(self.client.writes, [])

    def test_altered_receipt_cannot_claim_verified_completion_or_resume_writes(self):
        proposal = self.proposal()
        self.apply(proposal)
        receipt = next((self.runtime / "azure-reconcile").glob("*.json"))
        stored = json.loads(receipt.read_text())
        del stored["entries"][0]["after"]
        receipt.write_text(json.dumps(stored))
        with self.assertRaisesRegex(reconcile.ReconcileError, "verified reciprocal"):
            self.apply(proposal)
        self.assertEqual(len(self.client.writes), 1)

    def test_slow_fresh_read_cannot_outlive_proposal_authority_before_patch(self):
        proposal = self.proposal()
        def delayed_read(client):
            if len(client.reads) == 2:
                self.now += 1000
                client.observed_at = timestamp(self.now)
        self.client.read_hook = delayed_read
        with self.assertRaisesRegex(reconcile.ReconcileError, "stale"):
            self.apply(proposal)
        self.assertEqual(self.client.writes, [])

    def test_boolean_release_ids_cannot_impersonate_authorized_integer_ids(self):
        change, artifact_path = self.closure()
        acceptance = change["state_transition"]["acceptance"]
        acceptance["release"].update(pipeline_definition_id=1, run_id=1)
        artifact = json.loads(artifact_path.read_text())
        artifact["release"].update(pipeline_definition_id=True, run_id=True)
        artifact_path.write_text(json.dumps(artifact))
        acceptance["evidence"][0]["sha256"] = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        acceptance["human_gate"]["artifact_sha256"] = reconcile.acceptance_contract_sha256(acceptance)
        with self.assertRaisesRegex(reconcile.ReconcileError, "actual acceptance"):
            self.apply(self.proposal([change]))
        self.assertEqual(self.client.writes, [])
        self.assertEqual(self.client.items[16]["fields"]["System.State"], "To Do")


class AzureReconcileAuthorityTests(unittest.TestCase):
    """Real signed grants at the direct Board API; only Azure is simulated."""

    behavioral_authority = staticmethod(AzureReconcileTests.behavioral_authority)
    proposal = AzureReconcileTests.proposal
    closure = AzureReconcileTests.closure

    def setUp(self):
        AzureReconcileTests.setUp(self)
        self.authority_patcher.stop()
        self.human_authority_patcher.stop()
        self.root = self.runtime
        self.runtime = self.root / "runtime"
        self.runtime.mkdir(mode=0o700)
        self.config = replace(self.config, runtime_dir=self.runtime)
        sys.path.insert(0, str(ROOT / "tests" / "fixtures"))
        from authority_fixture import AuthorityFixture
        import atlas_authority
        self.fixture = AuthorityFixture(self.runtime, now=int(self.now))
        patcher = mock.patch.object(atlas_authority, "pwd", SimpleNamespace(
            getpwuid=lambda uid: SimpleNamespace(pw_dir=str(self.root))))
        patcher.start()
        self.addCleanup(patcher.stop)

    def grant(self, proposal, **bindings):
        subject = reconcile.authorization_bindings(proposal, self.config, self.runtime)
        subject.update(bindings)
        return self.fixture.grant("board_write", subject)

    def apply(self, proposal, **kwargs):
        kwargs.setdefault("authorization", self.grant(proposal))
        return AzureReconcileTests.apply(self, proposal, **kwargs)

    def revoke(self):
        self.fixture.registry["revoked_grants"] = ["synthetic-test-grant"]
        self.fixture.update_trust()

    def accepted_closure(self):
        from atlas_human_gates import gate_bindings
        change, path = self.closure()
        acceptance = change["state_transition"]["acceptance"]
        context = {"issue_id": ident(16), "issue_revision": 3, "candidate_sha": acceptance["candidate"],
                   "worker_packet_sha256": reconcile.acceptance_contract_sha256(acceptance), "action": "completion"}
        receipt = acceptance["human_receipt"]
        receipt["grant"] = self.fixture.grant("human_gate", gate_bindings(acceptance["human_gate"], receipt, context),
                                               grant_id="synthetic-human-acceptance")
        return change, path

    def test_plain_hash_forged_or_unbound_grants_cannot_enter_direct_apply(self):
        proposal = self.proposal()
        forged = self.grant(proposal)
        forged["payload"]["bindings"]["proposal_sha256"] = "a" * 64
        typed = self.grant(proposal, schema_version=True)
        for grant in (None, {"approval_record": "approved", "packet_sha256": reconcile.canonical_sha256(proposal)},
                      forged, typed, self.grant(proposal, repository_url="https://dev.azure.com/Instablinds/Instablinds/_git/Other")):
            with self.subTest(grant=grant is None), self.assertRaises(reconcile.ReconcileError):
                self.apply(proposal, authorization=grant)
        self.assertEqual(self.client.writes, [])
        self.assertEqual(self.client.reads, [])
        self.assertFalse((self.runtime / "azure-reconcile").exists())

    def test_direct_apply_requires_configuration_even_with_a_signed_matching_hash(self):
        proposal = self.proposal()
        with self.assertRaises(reconcile.ReconcileError):
            self.apply(proposal, config=None)
        self.assertEqual(self.client.reads, [])
        self.assertFalse((self.runtime / "azure-reconcile").exists())

    def test_signed_board_grant_applies_exact_patch_and_remains_non_dispatchable(self):
        result = self.apply(self.proposal(), authorized_sha256=None)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["execution_eligibility"], "blocked")
        self.assertFalse(result["release_completion_inferred"])
        self.assertEqual(len(self.client.writes), 1)

    def test_configuration_and_proposal_drift_invalidate_previously_signed_apply(self):
        proposal = self.proposal()
        grant = self.grant(proposal)
        changed_config = replace(self.config, repository={**self.config.repository, "base_branch": "main"})
        with self.assertRaises(reconcile.ReconcileError):
            self.apply(proposal, config=changed_config, authorization=grant)
        changed = self.proposal([{"issue_id": ident(17), "add_tags": ["atlas:prepared"]}])
        with self.assertRaises(reconcile.ReconcileError):
            self.apply(changed, authorization=grant)
        self.assertEqual(self.client.writes, [])

    def test_revoked_grant_after_throttle_wait_stops_patch_without_replay(self):
        proposal = self.proposal()
        self.client.before_patch = lambda client, number: self.revoke()
        with self.assertRaises(reconcile.ReconcileError):
            self.apply(proposal)
        self.assertEqual(self.client.writes, [])
        self.assertEqual(self.client.items[16]["rev"], 3)

    def test_revocation_between_serial_patches_stops_remaining_changes(self):
        proposal = self.proposal([{"issue_id": ident(16), "add_tags": ["atlas:prepared"]},
                                  {"issue_id": ident(17), "add_tags": ["atlas:prepared"]}])
        def after_first(client):
            if client.writes:
                self.revoke()
        self.client.read_hook = after_first
        with self.assertRaises(reconcile.ReconcileError):
            self.apply(proposal)
        self.assertEqual(len(self.client.writes), 1)
        self.assertEqual(self.client.items[17]["rev"], 3)

    def test_generic_board_grant_cannot_substitute_for_independent_human_acceptance(self):
        change, _ = self.closure()
        proposal = self.proposal([change])
        with self.assertRaisesRegex(reconcile.ReconcileError, "human testing"):
            self.apply(proposal)
        self.assertEqual(self.client.writes, [])
        self.assertFalse((self.runtime / "azure-reconcile").exists())

    def test_two_independent_signed_grants_allow_exact_release_acceptance(self):
        change, _ = self.accepted_closure()
        result = self.apply(self.proposal([change]))
        self.assertEqual(result["status"], "applied")
        self.assertEqual(self.client.items[16]["fields"]["System.State"], "Done")

    def test_human_receipt_requires_enrolled_owner_and_unrevoked_acceptance(self):
        change, _ = self.accepted_closure()
        self.fixture.registry["issuers"]["test-operator"]["actions"].remove("human_gate")
        self.fixture.update_trust()
        with self.assertRaisesRegex(reconcile.ReconcileError, "human testing"):
            self.apply(self.proposal([change]))
        self.assertEqual(self.client.writes, [])

    def test_human_receipt_cannot_be_replayed_for_changed_release_artifacts(self):
        change, _ = self.accepted_closure()
        acceptance = change["state_transition"]["acceptance"]
        acceptance["release"]["run_id"] += 1
        acceptance["human_gate"]["artifact_sha256"] = reconcile.acceptance_contract_sha256(acceptance)
        with self.assertRaisesRegex(reconcile.ReconcileError, "human testing"):
            self.apply(self.proposal([change]))
        self.assertEqual(self.client.writes, [])

    def test_human_acceptance_revocation_is_rechecked_immediately_before_patch(self):
        change, _ = self.accepted_closure()
        def revoke_human(client, number):
            self.fixture.registry["revoked_grants"] = ["synthetic-human-acceptance"]
            self.fixture.update_trust()
        self.client.before_patch = revoke_human
        with self.assertRaisesRegex(reconcile.ReconcileError, "human testing"):
            self.apply(self.proposal([change]))
        self.assertEqual(self.client.writes, [])

    def test_signed_cli_apply_is_verified_before_azure_authentication(self):
        proposal = self.proposal()
        packet = self.root / "proposal.json"
        packet.write_text(json.dumps(proposal))
        authorization = self.root / "untrusted-grant.json"
        authorization.write_text(json.dumps({"approval_record": "self-asserted"}))
        with mock.patch.object(reconcile, "load_runtime_config", return_value=self.config), mock.patch("atlas_azure_devops.azure_cli_headers", side_effect=AssertionError("invalid grant authenticated")), redirect_stdout(io.StringIO()):
            result = reconcile.main(["--config", str(self.root / "config.json"), "--runtime-dir", str(self.runtime),
                                     "--packet", str(packet), "--authorization", str(authorization), "--apply"])
        self.assertEqual(result, 2)
        self.assertEqual(self.client.writes, [])
        self.assertFalse((self.runtime / "azure-reconcile").exists())


if __name__ == "__main__":
    unittest.main()
