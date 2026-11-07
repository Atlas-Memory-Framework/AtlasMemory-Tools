"""Offline source-admission fixtures; no host dispatch or build authority evidence."""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from types import MappingProxyType
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import atlas_local_sizing as sizing
import atlas_work_items as wi

ROLES = [dict(role_id=role["role_id"], goal_gate=role["goal_gate"])
         for role in sizing._SUPERVISOR_ROLES]


def intake():
    return {
        "id": "V3-TEST-ONE", "title": "Scoped authority fixture",
        "goal": "Reject a forged trusted actor in one fixed source contract.",
        "acceptance_criteria": ["The command contract rejects imported actor authority."],
        "spec_path": "/reviewed/frozen-spec.md", "spec_hash": "sha256:" + "d" * 64,
        "scheduler": {"execution_repo": "/isolated/checkout", "base_branch": "a" * 40,
                      "workflow_kind": "work-item", "team_template": "work-item-change-lifecycle",
                      "write_scope": ["src/command.py"], "depends_on": ["ACCEPTED-PARENT"],
                      "validation": ["Run the bounded authority-negative fixture."]},
        "metadata": {"manifest_leaf_id": "V3-TEST-ONE", "package_id": "fixture/V3-TEST-ONE",
                     "package_hash": "sha256:" + "c" * 64,
                     "source_plan": {"path": "/reviewed/plan.md", "hash": "sha256:" + "b" * 64},
                     "local_execution_v1": {
            "policy_id": sizing.SOURCE_REVIEWED_POLICY_ID,
            "implementation_model": "gpt-6.1-sol", "review_model": "gpt-6.1-terra",
            "role_purposes": {role["role_id"]: role["purpose"] for role in sizing._SUPERVISOR_ROLES},
            "changed_interfaces": ["fixed trusted command contract"],
            "unresolved_questions": [], "complexity_flags": ["security_or_authority"],
            "sizing_review": {"reviewer": "independent synthetic fixture",
                              "rationale": "This exact one-contract fixture fits the bounded source route.",
                              "subject_sha256": "pending"},
        }},
    }


def context_for(item):
    context = wi.work_item_context(item)
    contract = context["local_execution_v1"]
    contract["sizing_review"]["subject_sha256"] = sizing.sizing_subject_sha256(context)
    return context


def record_for(context):
    return MappingProxyType({
        "semantic_context_sha256": sizing.semantic_subject_sha256(context),
        "complexity_flags": tuple(context["local_execution_v1"]["complexity_flags"]),
        "review_evidence": (MappingProxyType({"artifact": "synthetic-security-review.json",
                                             "sha256": "e" * 64}),),
    })


class SourceReviewedAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.context = context_for(intake())
        self.registry = {self.context["package_id"]: record_for(self.context)}
        self.patch = mock.patch.object(sizing, "SOURCE_REVIEWED_UNITS_V3", MappingProxyType(self.registry))
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def resign(self, context):
        context["local_execution_v1"]["sizing_review"]["subject_sha256"] = sizing.sizing_subject_sha256(context)

    def test_exact_source_disposition_retains_flags_and_binds_full_sizing_subject(self):
        result = sizing.qualify(self.context, ROLES)
        self.assertEqual(result["status"], "qualified")
        self.assertEqual(result["policy_version"], 3)
        self.assertEqual(result["observed_counts"]["complexity_flags"], 1)
        disposition = result["source_reviewed_admission"]
        self.assertEqual(disposition["sizing_subject_sha256"], sizing.sizing_subject_sha256(self.context))
        self.assertEqual(disposition["complexity_flags"], ["security_or_authority"])
        for role in ROLES:
            self.assertEqual(sizing.qualify(self.context, [role])["status"], "qualified")

    def test_all_existing_flag_types_can_have_distinct_source_owned_dispositions(self):
        for flag in sorted(sizing.COMPLEXITY_FLAGS):
            with self.subTest(flag=flag):
                context = copy.deepcopy(self.context)
                context["package_id"] += "/" + flag
                context["local_execution_v1"]["complexity_flags"] = [flag]
                self.resign(context)
                self.registry[context["package_id"]] = record_for(context)
                self.assertEqual(sizing.qualify(context, ROLES)["status"], "qualified")

    def test_every_semantic_mutation_blocks_even_after_fresh_caller_sizing_review(self):
        changes = {
            "unknown_field": lambda c: c.update(unreviewed_effect="publish"),
            "id": lambda c: c.update(work_item_id="V3-TEST-TWO"),
            "leaf_id": lambda c: c.update(manifest_leaf_id="V3-TEST-TWO"),
            "missing_id": lambda c: c.pop("work_item_id"),
            "title": lambda c: c.update(title="Another task"),
            "goal": lambda c: c.update(goal="Expand authority and execute a new behavior."),
            "criteria": lambda c: c["acceptance_criteria"].append("Permit another fixed behavior."),
            "scope": lambda c: c["write_scope"].append("src/another.py"),
            "validation": lambda c: c["validation"].clear(),
            "dependency": lambda c: c["depends_on"].clear(),
            "spec": lambda c: c.update(spec_hash="sha256:" + "f" * 64),
            "spec_path": lambda c: c.update(spec_path="/another/spec.md"),
            "plan": lambda c: c["source_plan"].update(hash="sha256:" + "f" * 64),
            "package": lambda c: c.update(package_hash="sha256:" + "f" * 64),
            "unknown_package": lambda c: c.update(package_id="unreviewed/package"),
            "workflow": lambda c: c["workflow_request"].update(team_template="other"),
            "flags_removed": lambda c: c["local_execution_v1"].update(complexity_flags=[]),
            "flags_added": lambda c: c["local_execution_v1"]["complexity_flags"].append("migration"),
            "interfaces": lambda c: c["local_execution_v1"]["changed_interfaces"].append("other interface"),
            "model": lambda c: c["local_execution_v1"].update(implementation_model="gpt-6-luna"),
            "purpose": lambda c: c["local_execution_v1"]["role_purposes"].update(implementation="review"),
        }
        for name, change in changes.items():
            with self.subTest(name=name):
                context = copy.deepcopy(self.context)
                change(context)
                self.resign(context)
                self.assertEqual(sizing.qualify(context, ROLES)["status"], "blocked")

    def test_late_bound_checkout_and_revision_require_new_full_sizing_review(self):
        for field, value in (("execution_repo", "/new/isolated/checkout"), ("base_branch", "b" * 40)):
            with self.subTest(field=field):
                context = copy.deepcopy(self.context)
                context[field] = value
                self.assertEqual(sizing.semantic_subject_sha256(context), sizing.semantic_subject_sha256(self.context))
                self.assertEqual(sizing.qualify(context, ROLES)["status"], "blocked")
                self.resign(context)
                self.assertEqual(sizing.qualify(context, ROLES)["status"], "qualified")
        for field, values in (("execution_repo", (None, "relative", "/a/../b", "/a//b", "/a/", "//a/b", "/a/\0b", "/a/\nb", "/a/\ud800b")),
                              ("base_branch", (None, "main", "a" * 39, "A" * 40))):
            for value in values:
                with self.subTest(field=field, value=value):
                    context = copy.deepcopy(self.context)
                    context[field] = value
                    self.resign(context)
                    self.assertEqual(sizing.qualify(context, ROLES)["status"], "blocked")

    def test_no_full_packet_budget_bypass_through_review_only_subset(self):
        for field, value, status in (("write_scope", [f"src/file{i}.py" for i in range(5)], "split_required"),
                                     ("acceptance_criteria", [f"The bounded criterion number {i} passes." for i in range(4)], "split_required")):
            with self.subTest(field=field):
                context = copy.deepcopy(self.context)
                context[field] = value
                self.resign(context)
                self.registry[context["package_id"]] = record_for(context)
                result = sizing.qualify(context, [{"role_id": "code-review", "goal_gate": False}])
                self.assertEqual(result["status"], status)
                with self.assertRaises(ValueError):
                    sizing.assignment_for_task({"role_id": "code-review", "goal_gate": False,
                                                "work_item_context": context})
        context = copy.deepcopy(self.context)
        context["local_execution_v1"]["unresolved_questions"] = ["Which actor is trusted?"]
        self.resign(context)
        self.registry[context["package_id"]] = record_for(context)
        self.assertEqual(sizing.qualify(context, [{"role_id": "code-review", "goal_gate": False}])["status"],
                         "decomposition_required")

    def test_strict_selected_roles_and_goal_gate_cannot_be_relabelled(self):
        bad_roles = ([{"role_id": "code-review"}],
                     [{"role_id": "implementation", "goal_gate": True}],
                     [{"role_id": "semantic-alignment", "goal_gate": False}],
                     [{"role_id": "code-review", "id": "implementation", "goal_gate": False}],
                     [{"role_id": " code-review", "goal_gate": False}],
                     [{"role_id": "unknown", "goal_gate": False}])
        for roles in bad_roles:
            with self.subTest(roles=roles):
                self.assertEqual(sizing.qualify(self.context, roles)["status"], "blocked")

    def test_projection_binds_actual_identity_and_rejects_extra_contract_fields(self):
        task = intake()
        task["id"] = "V3-TEST-TWO"
        context = context_for(task)
        self.assertEqual(context["work_item_id"], task["id"])
        self.assertEqual(sizing.qualify(context, ROLES)["status"], "blocked")
        task = intake()
        task["metadata"]["local_execution_v1"]["self_approved"] = "private-input-do-not-copy"
        context = wi.work_item_context(task)
        self.assertNotIn("private-input-do-not-copy", str(context))
        self.assertEqual(sizing.qualify(context, ROLES)["status"], "blocked")

    def test_malformed_policy_types_are_blocked_without_exception(self):
        for value in ([], {}, None, 3, False):
            with self.subTest(value=value):
                context = copy.deepcopy(self.context)
                context["local_execution_v1"]["policy_id"] = value
                self.assertEqual(sizing.qualify(context, ROLES)["status"], "blocked")
                task = intake()
                task["metadata"]["local_execution_v1"]["policy_id"] = value
                projected = wi.work_item_context(task)
                self.assertEqual(sizing.qualify(projected, ROLES)["status"], "blocked")

    def test_v1_v2_retain_complexity_rejection_for_same_flagged_work(self):
        for policy in (sizing.POLICY_ID, sizing.REVIEWED_POLICY_ID):
            with self.subTest(policy=policy):
                context = copy.deepcopy(self.context)
                contract = context["local_execution_v1"]
                contract["policy_id"] = policy
                if policy == sizing.POLICY_ID:
                    for key in sizing.REVIEWED_FIELDS:
                        contract.pop(key)
                else:
                    self.resign(context)
                self.assertEqual(sizing.qualify(context, ROLES)["status"], "decomposition_required")
                contract["complexity_flags"] = []
                if policy == sizing.REVIEWED_POLICY_ID:
                    self.resign(context)
                self.assertEqual(sizing.qualify(context, ROLES)["status"], "qualified")
