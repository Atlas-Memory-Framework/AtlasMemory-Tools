from __future__ import annotations

import importlib.machinery
import importlib.util
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_script(name: str, filename: str):
    loader = importlib.machinery.SourceFileLoader(name, str(ROOT / filename))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


class AtlasWorkflowTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflows = load_script("atlas_workflows_test", "atlas_workflows.py")
        cls.workflow_lint = load_script("atlas_workflow_lint_test", "atlas-agent-workflow-lint")
        cls.workflow_select = load_script("atlas_workflow_select_test", "atlas-agent-workflow-select")
        cls.workflow_template_add = load_script(
            "atlas_workflow_template_add_test",
            "atlas-agent-workflow-template-add",
        )

    def planning_template(self):
        return self.workflows.TeamTemplate.from_dict(
            {
                "id": "planning-design-doc",
                "name": "Planning Design Doc",
                "purpose": "Fan out specialist agent roles and roll them into one plan.",
                "workflow_kind": "planning",
                "roles": [
                    {
                        "id": "architecture",
                        "label": "Architecture",
                        "agent_ref": "agents/architecture.md",
                        "skills": ["technical-planning"],
                        "must_produce": ["architecture_risks", "recommended_shape"],
                    },
                    {
                        "id": "security",
                        "label": "Security",
                        "agent_ref": "agents/security.md",
                        "must_produce": ["threat_model", "required_gates"],
                    },
                ],
                "rollup": {"document": "plan-evidence.md"},
            }
        )

    def test_template_validates_roles_and_required_outputs(self) -> None:
        template = self.planning_template()

        self.assertEqual(template.validate(), [])
        self.assertEqual(template.roles[0].id, "architecture")
        self.assertEqual(template.roles[1].must_produce, ["threat_model", "required_gates"])

    def test_template_rejects_role_without_outputs(self) -> None:
        template = self.workflows.TeamTemplate.from_dict(
            {
                "id": "bad-template",
                "roles": [{"id": "architecture", "agent_ref": "agents/architecture.md"}],
            }
        )

        self.assertIn("role architecture must declare at least one output", template.validate())

    def test_template_rejects_unknown_role_dependency_and_duplicate_outputs(self) -> None:
        template = self.workflows.TeamTemplate.from_dict(
            {
                "id": "bad-template",
                "roles": [
                    {
                        "id": "author",
                        "agent_ref": "agents/author.md",
                        "must_produce": ["summary", "summary"],
                    },
                    {
                        "id": "rollup",
                        "agent_ref": "agents/rollup.md",
                        "consumes": ["missing-role"],
                        "must_produce": ["summary"],
                    },
                ],
            }
        )

        errors = template.validate()

        self.assertIn("role author has duplicate outputs", errors)
        self.assertIn("output summary is produced by both author and rollup", errors)
        self.assertIn("role rollup consumes unknown role missing-role", errors)

    def test_template_rejects_dependency_cycles(self) -> None:
        template = self.workflows.TeamTemplate.from_dict(
            {
                "id": "bad-template",
                "roles": [
                    {
                        "id": "author",
                        "agent_ref": "agents/author.md",
                        "consumes": ["review"],
                        "must_produce": ["summary"],
                    },
                    {
                        "id": "review",
                        "agent_ref": "agents/review.md",
                        "consumes": ["author"],
                        "must_produce": ["findings"],
                    },
                ],
            }
        )

        self.assertIn("role dependency cycle: author -> review -> author", template.validate())

    def test_template_requires_rollup_coverage_when_outputs_block_completion(self) -> None:
        template = self.workflows.TeamTemplate.from_dict(
            {
                "id": "bad-rollup",
                "workflow_kind": "review",
                "roles": [
                    {
                        "id": "review",
                        "agent_ref": "agents/review.md",
                        "must_produce": ["findings"],
                    },
                    {
                        "id": "rollup",
                        "agent_ref": "agents/rollup.md",
                        "must_produce": ["decision"],
                    },
                ],
                "rollup": {"missing_outputs_block_completion": True},
            }
        )

        errors = template.validate()

        self.assertIn(
            "rollup coverage requires at least one prior role before the final rollup phase",
            errors,
        )

    def test_team_run_tracks_missing_outputs_until_all_roles_complete(self) -> None:
        template = self.planning_template()
        run = self.workflows.TeamRun.start(run_id="run-1", template=template, work_item_id="WI-1")

        run.record_role_result(
            self.workflows.TeamRunRoleResult(
                role_id="architecture",
                status="complete",
                outputs={
                    "architecture_risks": "State ownership is split.",
                    "recommended_shape": "Use one local work-item lifecycle.",
                },
            )
        )

        self.assertEqual(run.refresh_status(template), "running")
        self.assertEqual(run.missing_outputs(template), {"security": ["threat_model", "required_gates"]})

        run.record_role_result(
            self.workflows.TeamRunRoleResult(
                role_id="security",
                status="complete",
                outputs={"threat_model": "Local files are trusted input only.", "required_gates": "No GitHub mutation."},
                evidence=["jobs/security-review.md"],
            )
        )

        self.assertEqual(run.refresh_status(template), "complete")
        self.assertEqual(run.missing_outputs(template), {})

    def test_apply_role_results_rejects_unknown_role(self) -> None:
        template = self.planning_template()
        run = self.workflows.TeamRun.start(run_id="run-1", template=template, work_item_id="WI-1")

        with self.assertRaises(ValueError):
            self.workflows.apply_role_results(
                template=template,
                run=run,
                results=[
                    self.workflows.TeamRunRoleResult(
                        role_id="unknown",
                        status="complete",
                        outputs={"summary": "not allowed"},
                    )
                ],
            )

    def test_apply_role_results_normalizes_contract_issues(self) -> None:
        template = self.planning_template()
        run = self.workflows.TeamRun.start(run_id="run-1", template=template, work_item_id="WI-1")

        self.workflows.apply_role_results(
            template=template,
            run=run,
            results=[
                self.workflows.TeamRunRoleResult(
                    role_id="architecture",
                    status="complete",
                    outputs={
                        "architecture_risks": "State ownership is split.",
                        "bonus_output": "not part of the role contract",
                    },
                )
            ],
        )

        result = run.role_results["architecture"]
        summary = self.workflows.team_run_summary(template, run)
        markdown = run.rollup_markdown(template)

        self.assertEqual(result.status, "incomplete")
        self.assertIn("missing required output(s): recommended_shape", result.contract_issues)
        self.assertIn("unexpected output(s): bonus_output", result.contract_issues)
        self.assertEqual(run.missing_outputs(template)["architecture"], ["architecture_risks", "recommended_shape"])
        self.assertEqual(summary["roles"][0]["status"], "incomplete")
        self.assertIn("unexpected output(s): bonus_output", summary["roles"][0]["contract_issues"])
        self.assertIn("Contract issue: missing required output(s): recommended_shape", markdown)

    def test_apply_role_results_requires_consumed_roles_to_be_complete(self) -> None:
        template = self.workflows.TeamTemplate.from_dict(
            {
                "id": "review-rollup",
                "workflow_kind": "review",
                "roles": [
                    {
                        "id": "review",
                        "agent_ref": "agents/review.md",
                        "must_produce": ["findings"],
                    },
                    {
                        "id": "rollup",
                        "agent_ref": "agents/rollup.md",
                        "consumes": ["review"],
                        "must_produce": ["decision"],
                    },
                ],
            }
        )
        run = self.workflows.TeamRun.start(run_id="run-1", template=template, work_item_id="WI-1")

        self.workflows.apply_role_results(
            template=template,
            run=run,
            results=[
                self.workflows.TeamRunRoleResult(
                    role_id="rollup",
                    status="complete",
                    outputs={"decision": "pass"},
                )
            ],
        )

        result = run.role_results["rollup"]
        summary = self.workflows.team_run_summary(template, run)
        markdown = run.rollup_markdown(template)

        self.assertEqual(result.status, "incomplete")
        self.assertIn("dependency not complete: review", result.contract_issues)
        self.assertEqual(run.missing_outputs(template), {"review": ["findings"], "rollup": ["decision"]})
        packets = self.workflows.role_task_packets(template, run)
        self.assertEqual(packets[1]["contract_issues"], ["dependency not complete: review"])
        self.assertEqual(packets[1]["dependency_blockers"], ["dependency not complete: review"])
        self.assertEqual(summary["roles"][1]["dependency_blockers"], ["dependency not complete: review"])
        self.assertIn("Dependency blocker: dependency not complete: review", markdown)
        self.assertIn("Consumes: review", markdown)

    def test_apply_role_results_allows_same_batch_dependency_completion(self) -> None:
        template = self.workflows.TeamTemplate.from_dict(
            {
                "id": "review-rollup",
                "workflow_kind": "review",
                "roles": [
                    {
                        "id": "review",
                        "agent_ref": "agents/review.md",
                        "must_produce": ["findings"],
                    },
                    {
                        "id": "rollup",
                        "agent_ref": "agents/rollup.md",
                        "consumes": ["review"],
                        "must_produce": ["decision"],
                    },
                ],
            }
        )
        run = self.workflows.TeamRun.start(run_id="run-1", template=template, work_item_id="WI-1")

        self.workflows.apply_role_results(
            template=template,
            run=run,
            results=[
                self.workflows.TeamRunRoleResult(
                    role_id="rollup",
                    status="complete",
                    outputs={"decision": "pass"},
                ),
                self.workflows.TeamRunRoleResult(
                    role_id="review",
                    status="complete",
                    outputs={"findings": "none"},
                ),
            ],
        )

        self.assertEqual(run.role_results["rollup"].status, "complete")
        self.assertEqual(run.role_results["rollup"].contract_issues, [])
        self.assertEqual(run.refresh_status(template), "complete")

    def test_apply_role_results_checks_transitive_dependency_completion(self) -> None:
        template = self.workflows.TeamTemplate.from_dict(
            {
                "id": "transitive",
                "workflow_kind": "review",
                "roles": [
                    {
                        "id": "source",
                        "agent_ref": "agents/source.md",
                        "must_produce": ["source_output"],
                    },
                    {
                        "id": "middle",
                        "agent_ref": "agents/middle.md",
                        "consumes": ["source"],
                        "must_produce": ["middle_output"],
                    },
                    {
                        "id": "rollup",
                        "agent_ref": "agents/rollup.md",
                        "consumes": ["middle"],
                        "must_produce": ["decision"],
                    },
                ],
            }
        )
        run = self.workflows.TeamRun.start(run_id="run-1", template=template, work_item_id="WI-1")

        self.workflows.apply_role_results(
            template=template,
            run=run,
            results=[
                self.workflows.TeamRunRoleResult(
                    role_id="rollup",
                    status="complete",
                    outputs={"decision": "pass"},
                ),
                self.workflows.TeamRunRoleResult(
                    role_id="middle",
                    status="complete",
                    outputs={"middle_output": "ready"},
                ),
            ],
        )

        self.assertEqual(run.role_results["middle"].status, "incomplete")
        self.assertIn("dependency not complete: source", run.role_results["middle"].contract_issues)
        self.assertEqual(run.role_results["rollup"].status, "incomplete")
        self.assertIn("dependency not complete: middle", run.role_results["rollup"].contract_issues)

    def test_apply_role_results_recomputes_stale_dependency_contract_issues(self) -> None:
        template = self.workflows.TeamTemplate.from_dict(
            {
                "id": "review-rollup",
                "workflow_kind": "review",
                "roles": [
                    {
                        "id": "review",
                        "agent_ref": "agents/review.md",
                        "must_produce": ["findings"],
                    },
                    {
                        "id": "rollup",
                        "agent_ref": "agents/rollup.md",
                        "consumes": ["review"],
                        "must_produce": ["decision"],
                    },
                ],
            }
        )
        run = self.workflows.TeamRun.start(run_id="run-1", template=template, work_item_id="WI-1")
        self.workflows.apply_role_results(
            template=template,
            run=run,
            results=[
                self.workflows.TeamRunRoleResult(
                    role_id="rollup",
                    status="complete",
                    outputs={"decision": "pass"},
                )
            ],
        )

        self.workflows.apply_role_results(
            template=template,
            run=run,
            results=[
                self.workflows.TeamRunRoleResult(
                    role_id="review",
                    status="complete",
                    outputs={"findings": "none"},
                )
            ],
        )

        self.assertEqual(run.role_results["review"].status, "complete")
        self.assertEqual(run.role_results["rollup"].status, "complete")
        self.assertEqual(run.role_results["rollup"].contract_issues, [])
        self.assertEqual(run.refresh_status(template), "complete")

    def test_load_role_results_supports_role_result_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "results.json"
            path.write_text(
                json.dumps(
                    {
                        "role_results": {
                            "security": {
                                "status": "complete",
                                "outputs": {"threat_model": "local-only"},
                                "evidence": ["security.md"],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            results = self.workflows.load_role_results(path)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].role_id, "security")
        self.assertEqual(results[0].outputs["threat_model"], "local-only")

    def test_rollup_markdown_combines_role_outputs_and_missing_outputs(self) -> None:
        template = self.planning_template()
        run = self.workflows.TeamRun.start(run_id="run-1", template=template, work_item_id="WI-1")
        run.record_role_result(
            self.workflows.TeamRunRoleResult(
                role_id="security",
                status="complete",
                outputs={"threat_model": "No external dispatch.", "required_gates": "Local-only evidence."},
            )
        )

        markdown = run.rollup_markdown(template)

        self.assertIn("# Planning Design Doc Evidence", markdown)
        self.assertIn("### Security", markdown)
        self.assertIn("- threat_model: No external dispatch.", markdown)
        self.assertIn("`architecture`: architecture_risks, recommended_shape", markdown)

    def test_role_task_packets_expose_agent_refs_skills_and_missing_outputs(self) -> None:
        template = self.planning_template()
        run = self.workflows.TeamRun.start(run_id="run-1", template=template, work_item_id="WI-1")
        run.record_role_result(
            self.workflows.TeamRunRoleResult(
                role_id="architecture",
                status="complete",
                outputs={
                    "architecture_risks": "State ownership is split.",
                    "recommended_shape": "Use one local work-item lifecycle.",
                },
            )
        )

        packets = self.workflows.role_task_packets(template, run)

        self.assertEqual([packet["role_id"] for packet in packets], ["architecture", "security"])
        self.assertEqual(packets[0]["agent_ref"], "agents/architecture.md")
        self.assertEqual(packets[0]["skills"], ["technical-planning"])
        self.assertEqual(packets[0]["missing_outputs"], [])
        self.assertEqual(packets[1]["missing_outputs"], ["threat_model", "required_gates"])
        self.assertEqual(packets[0]["consumed_role_results"], {})

    def test_role_task_packets_include_consumed_role_results(self) -> None:
        template = self.workflows.TeamTemplate.from_dict(
            {
                "id": "review-rollup",
                "workflow_kind": "review",
                "roles": [
                    {
                        "id": "review",
                        "agent_ref": "agents/review.md",
                        "must_produce": ["findings"],
                    },
                    {
                        "id": "rollup",
                        "agent_ref": "agents/rollup.md",
                        "consumes": ["review"],
                        "must_produce": ["decision"],
                    },
                ],
            }
        )
        run = self.workflows.TeamRun.start(run_id="run-1", template=template, work_item_id="WI-1")
        run.record_role_result(
            self.workflows.TeamRunRoleResult(
                role_id="review",
                status="complete",
                outputs={"findings": "no defects"},
            )
        )

        packets = self.workflows.role_task_packets(template, run)

        self.assertEqual(packets[1]["consumed_role_results"]["review"]["outputs"]["findings"], "no defects")

    def test_role_task_packets_include_resolved_registry_agent_definition(self) -> None:
        template = self.workflows.TeamTemplate.from_dict(
            {
                "id": "registry-agent",
                "roles": [
                    {
                        "id": "security",
                        "agent_ref": "agent-registry://security",
                        "must_produce": ["threat_model"],
                    }
                ],
            }
        )
        registry = self.workflows.load_agent_registry(ROOT / "config" / "agent-registry.example.json")
        run = self.workflows.TeamRun.start(run_id="run-1", template=template, work_item_id="WI-1")

        packets = self.workflows.role_task_packets(template, run, registry=registry)

        self.assertEqual(packets[0]["agent_definition"]["id"], "security")
        self.assertEqual(packets[0]["agent_definition"]["ref"], "agent-registry://security")
        self.assertIn("critical-ideation", packets[0]["agent_definition"]["skills"])
        self.assertEqual(packets[0]["agent_definition"]["source"], "agents/security.md")
        self.assertEqual(packets[0]["agent_definition"]["execution_profile"], "planning")

    def test_role_task_packets_include_local_markdown_agent_definition(self) -> None:
        template = self.workflows.TeamTemplate.from_dict(
            {
                "id": "local-agent",
                "roles": [
                    {
                        "id": "data-contracts",
                        "agent_ref": "agents/data-contracts.md",
                        "must_produce": ["contracts"],
                    }
                ],
            }
        )
        run = self.workflows.TeamRun.start(run_id="run-1", template=template, work_item_id="WI-1")

        packets = self.workflows.role_task_packets(template, run, agent_root=ROOT.parents[1])

        self.assertEqual(packets[0]["agent_definition"]["id"], "data-contracts")
        self.assertIn("Schema/contracts specialist", packets[0]["agent_definition"]["description"])
        self.assertTrue(packets[0]["agent_definition"]["source"].endswith("agents/data-contracts.md"))

    def test_template_role_phases_group_parallel_ready_roles(self) -> None:
        template = self.workflows.TeamTemplate.from_dict(
            {
                "id": "review-rollup",
                "workflow_kind": "review",
                "roles": [
                    {
                        "id": "code-review",
                        "agent_ref": "agents/code-review.md",
                        "must_produce": ["findings"],
                    },
                    {
                        "id": "security-review",
                        "agent_ref": "agents/security-review.md",
                        "must_produce": ["security_findings"],
                    },
                    {
                        "id": "rollup",
                        "agent_ref": "agents/rollup.md",
                        "consumes": ["code-review", "security-review"],
                        "must_produce": ["decision"],
                    },
                ],
            }
        )
        run = self.workflows.TeamRun.start(run_id="run-1", template=template, work_item_id="WI-1")

        packets = self.workflows.role_task_packets(template, run)

        self.assertEqual(template.role_phases(), [["code-review", "security-review"], ["rollup"]])
        self.assertEqual([packet["phase_index"] for packet in packets], [0, 0, 1])

    def test_team_run_summary_is_compact_lifecycle_evidence(self) -> None:
        template = self.planning_template()
        run = self.workflows.TeamRun.start(run_id="run-1", template=template, work_item_id="WI-1")
        run.record_role_result(
            self.workflows.TeamRunRoleResult(
                role_id="security",
                status="complete",
                outputs={"threat_model": "local-only", "required_gates": "none"},
            )
        )
        run.refresh_status(template)

        summary = self.workflows.team_run_summary(template, run)

        self.assertEqual(summary["run_id"], "run-1")
        self.assertEqual(summary["template_id"], "planning-design-doc")
        self.assertEqual(summary["status"], "running")
        self.assertIn("architecture", summary["missing_outputs"])
        self.assertEqual(summary["role_phases"], [["architecture", "security"]])
        self.assertEqual(summary["roles"][1]["completed_outputs"], ["required_gates", "threat_model"])

    def test_template_registry_loads_and_selects_by_kind_and_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            template_path = Path(tmp) / "planning.json"
            template_path.write_text(json.dumps(self.planning_template().to_dict()), encoding="utf-8")

            templates = self.workflows.load_team_templates(tmp)
            selected = self.workflows.select_team_template(
                templates,
                workflow_kind="planning",
                required_outputs=["threat_model", "recommended_shape"],
            )

        self.assertEqual(len(templates), 1)
        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected.id, "planning-design-doc")

    def test_default_planning_template_is_valid_and_selectable(self) -> None:
        templates = self.workflows.load_team_templates(ROOT / "team-templates")

        selected = self.workflows.select_team_template(
            templates,
            workflow_kind="planning",
            required_outputs=["threat_model", "plan_patch", "validation_commands"],
        )

        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected.id, "planning-design-doc")

    def test_default_work_item_template_is_valid_and_selectable(self) -> None:
        templates = self.workflows.load_team_templates(ROOT / "team-templates")

        selected = self.workflows.select_team_template(
            templates,
            workflow_kind="work-item",
            required_outputs=["change_summary", "test_results", "plan_alignment", "final_evidence_document"],
        )

        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected.id, "work-item-change-lifecycle")

    def test_default_review_and_validation_templates_are_valid_and_selectable(self) -> None:
        templates = self.workflows.load_team_templates(ROOT / "team-templates")

        review = self.workflows.select_team_template(
            templates,
            workflow_kind="review",
            required_outputs=["correctness_findings", "security_gate_status", "review_decision"],
        )
        validation = self.workflows.select_team_template(
            templates,
            workflow_kind="validation",
            required_outputs=["validation_matrix", "local_results", "validation_decision"],
        )

        self.assertIsNotNone(review)
        self.assertIsNotNone(validation)
        assert review is not None
        assert validation is not None
        self.assertEqual(review.id, "review-evidence-gate")
        self.assertEqual(validation.id, "validation-evidence-gate")

    def test_work_item_metadata_selects_template_by_kind_outputs_or_explicit_id(self) -> None:
        templates = self.workflows.load_team_templates(ROOT / "team-templates")
        by_kind = {
            "id": "WI-1",
            "scheduler": {
                "workflow_kind": "planning",
                "required_outputs": ["threat_model", "validation_commands"],
            },
        }
        by_id = {
            "id": "WI-2",
            "scheduler": {
                "team_template": "planning-design-doc",
                "required_outputs": ["plan_patch"],
            },
        }

        selected_by_kind = self.workflows.select_team_template_for_work_item(templates, by_kind)
        selected_by_id = self.workflows.select_team_template_for_work_item(templates, by_id)

        self.assertIsNotNone(selected_by_kind)
        self.assertIsNotNone(selected_by_id)
        assert selected_by_kind is not None
        assert selected_by_id is not None
        self.assertEqual(selected_by_kind.id, "planning-design-doc")
        self.assertEqual(selected_by_id.id, "planning-design-doc")

    def test_template_selection_report_explains_selected_and_missing_outputs(self) -> None:
        templates = self.workflows.load_team_templates(ROOT / "team-templates")

        selected_report = self.workflows.template_selection_report(
            templates,
            {
                "workflow_kind": "review",
                "required_outputs": ["correctness_findings", "review_decision"],
            },
        )
        missing_report = self.workflows.template_selection_report(
            templates,
            {
                "workflow_kind": "review",
                "required_outputs": ["correctness_findings", "unknown_output"],
            },
        )

        self.assertEqual(selected_report["selected_template"], "review-evidence-gate")
        self.assertEqual(selected_report["selection"]["status"], "use_existing_template")
        self.assertEqual(selected_report["selection"]["suggested_action"], "use_existing_template")
        self.assertEqual(selected_report["selection"]["uncovered_required_outputs"], [])
        review_candidate = next(
            candidate for candidate in selected_report["candidates"] if candidate["id"] == "review-evidence-gate"
        )
        self.assertTrue(review_candidate["selectable"])
        self.assertEqual(review_candidate["missing_required_outputs"], [])
        self.assertIsNone(missing_report["selected_template"])
        self.assertEqual(missing_report["selection"]["status"], "no_covering_template")
        self.assertEqual(missing_report["selection"]["suggested_action"], "edit_closest_template_or_create_new")
        self.assertEqual(missing_report["selection"]["closest_template"], "review-evidence-gate")
        self.assertEqual(missing_report["selection"]["covered_required_outputs"], ["correctness_findings"])
        self.assertEqual(missing_report["selection"]["uncovered_required_outputs"], ["unknown_output"])
        missing_candidate = next(
            candidate for candidate in missing_report["candidates"] if candidate["id"] == "review-evidence-gate"
        )
        self.assertEqual(missing_candidate["missing_required_outputs"], ["unknown_output"])
        compact = self.workflows.compact_template_selection_report(selected_report)
        compact_review = next(candidate for candidate in compact["candidates"] if candidate["id"] == "review-evidence-gate")
        self.assertEqual(compact["selected_template"], "review-evidence-gate")
        self.assertEqual(compact["selection"]["status"], "use_existing_template")
        self.assertEqual(
            compact_review["covered_required_outputs"],
            ["correctness_findings", "review_decision"],
        )
        self.assertNotIn("outputs", compact_review)

    def test_template_selection_report_recommends_create_for_unknown_kind(self) -> None:
        templates = self.workflows.load_team_templates(ROOT / "team-templates")

        report = self.workflows.template_selection_report(
            templates,
            {
                "workflow_kind": "migration",
                "required_outputs": ["migration_plan"],
            },
        )

        self.assertIsNone(report["selected_template"])
        self.assertEqual(report["selection"]["status"], "no_matching_workflow_kind")
        self.assertEqual(report["selection"]["suggested_action"], "create_new_template")
        self.assertIsNone(report["selection"]["closest_template"])
        self.assertEqual(report["selection"]["uncovered_required_outputs"], ["migration_plan"])

    def test_template_selection_prefers_most_specific_covering_template(self) -> None:
        broad = self.workflows.TeamTemplate.from_dict(
            {
                "id": "broad-review",
                "workflow_kind": "review",
                "roles": [
                    {
                        "id": "review",
                        "agent_ref": "agents/review.md",
                        "must_produce": ["decision", "findings", "risks"],
                    }
                ],
            }
        )
        narrow = self.workflows.TeamTemplate.from_dict(
            {
                "id": "narrow-review",
                "workflow_kind": "review",
                "roles": [
                    {
                        "id": "decision",
                        "agent_ref": "agents/review.md",
                        "must_produce": ["decision"],
                    }
                ],
            }
        )

        selected = self.workflows.select_team_template(
            [broad, narrow],
            workflow_kind="review",
            required_outputs=["decision"],
        )
        report = self.workflows.template_selection_report(
            [broad, narrow],
            {"workflow_kind": "review", "required_outputs": ["decision"]},
        )

        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected.id, "narrow-review")
        self.assertEqual(report["selected_template"], "narrow-review")
        by_id = {candidate["id"]: candidate for candidate in report["candidates"]}
        self.assertEqual(by_id["narrow-review"]["extra_output_count"], 0)
        self.assertEqual(by_id["broad-review"]["extra_output_count"], 2)

    def test_explicit_template_selection_keeps_requested_id(self) -> None:
        broad = self.workflows.TeamTemplate.from_dict(
            {
                "id": "broad-review",
                "workflow_kind": "review",
                "roles": [
                    {
                        "id": "review",
                        "agent_ref": "agents/review.md",
                        "must_produce": ["decision", "findings", "risks"],
                    }
                ],
            }
        )
        narrow = self.workflows.TeamTemplate.from_dict(
            {
                "id": "narrow-review",
                "workflow_kind": "review",
                "roles": [
                    {
                        "id": "decision",
                        "agent_ref": "agents/review.md",
                        "must_produce": ["decision"],
                    }
                ],
            }
        )

        selected = self.workflows.select_team_template_for_work_item(
            [narrow, broad],
            {
                "id": "WI-1",
                "scheduler": {
                    "team_template": "broad-review",
                    "required_outputs": ["decision"],
                },
            },
        )

        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected.id, "broad-review")

    def test_sample_work_item_selects_review_template(self) -> None:
        templates = self.workflows.load_team_templates(ROOT / "team-templates")
        payload = json.loads((ROOT / "examples" / "atlas-work-items.sample.json").read_text(encoding="utf-8"))
        work_item = payload["work_items"][0]

        selected = self.workflows.select_team_template_for_work_item(templates, work_item)

        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected.id, "review-evidence-gate")

    def test_agent_registry_validates_default_template_agent_refs(self) -> None:
        templates = self.workflows.load_team_templates(ROOT / "team-templates")
        registry = self.workflows.load_agent_registry(ROOT / "config" / "agent-registry.example.json")

        errors = [
            error
            for template in templates
            for error in self.workflows.validate_template_agent_refs(
                template,
                registry=registry,
                agent_root=ROOT.parents[1],
            )
        ]

        self.assertEqual(errors, [])

    def test_agent_ref_validation_reports_missing_registry_and_file_refs(self) -> None:
        template = self.workflows.TeamTemplate.from_dict(
            {
                "id": "bad-agents",
                "roles": [
                    {
                        "id": "missing-registry",
                        "agent_ref": "agent-registry://missing",
                        "must_produce": ["out"],
                    },
                    {
                        "id": "missing-file",
                        "agent_ref": "agents/missing.md",
                        "must_produce": ["file_out"],
                    },
                ],
            }
        )
        registry = self.workflows.AgentRegistry.from_dict({"agents": {}})

        errors = self.workflows.validate_template_agent_refs(
            template,
            registry=registry,
            agent_root=ROOT.parents[1],
        )

        self.assertIn("role missing-registry references unknown registry agent agent-registry://missing", errors)
        self.assertIn("role missing-file references missing agent file agents/missing.md", errors)

    def test_agent_ref_validation_reports_missing_registry_agent_source(self) -> None:
        template = self.workflows.TeamTemplate.from_dict(
            {
                "id": "bad-source",
                "roles": [
                    {
                        "id": "security",
                        "agent_ref": "agent-registry://security",
                        "must_produce": ["out"],
                    }
                ],
            }
        )
        registry = self.workflows.AgentRegistry.from_dict(
            {
                "agents": {
                    "security": {
                        "ref": "agent-registry://security",
                        "source": "agents/missing-security.md",
                    }
                }
            }
        )

        errors = self.workflows.validate_template_agent_refs(
            template,
            registry=registry,
            agent_root=ROOT.parents[1],
        )

        self.assertIn("role security registry agent source is missing agents/missing-security.md", errors)

    def test_workflow_lint_passes_default_templates_with_registry(self) -> None:
        summary = self.workflow_lint.lint_templates(
            ROOT / "team-templates",
            agent_registry=ROOT / "config" / "agent-registry.example.json",
            agent_root=ROOT.parents[1],
        )

        self.assertEqual(summary["errors"], [])
        self.assertEqual(summary["template_count"], 4)
        by_id = {template["id"]: template for template in summary["templates"]}
        self.assertEqual(
            by_id["review-evidence-gate"]["role_phases"],
            [["code-review", "security-review", "semantic-review"], ["review-rollup"]],
        )
        self.assertEqual(by_id["review-evidence-gate"]["rollup_roles"], ["review-rollup"])
        self.assertEqual(by_id["planning-design-doc"]["rollup_roles"], ["rollup-editor"])

    def test_workflow_select_cli_reports_sample_work_item_selection(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            rc = self.workflow_select.main(
                [
                    "--team-templates",
                    str(ROOT / "team-templates"),
                    "--work-item",
                    str(ROOT / "examples" / "atlas-work-items.sample.json"),
                    "--json",
                ]
            )

        payload = json.loads(stdout.getvalue())

        self.assertEqual(rc, 0)
        self.assertEqual(payload["selected_template"], "review-evidence-gate")
        self.assertEqual(payload["selection"]["suggested_action"], "use_existing_template")
        self.assertEqual(payload["request"]["workflow_kind"], "review")

    def test_workflow_select_cli_returns_nonzero_without_template_match(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            rc = self.workflow_select.main(
                [
                    "--team-templates",
                    str(ROOT / "team-templates"),
                    "--workflow-kind",
                    "review",
                    "--required-output",
                    "unknown_output",
                ]
            )

        self.assertEqual(rc, 1)

    def test_workflow_template_add_cli_writes_valid_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            role_a = json.dumps(
                {
                    "id": "migration-analysis",
                    "agent_ref": "agent-registry://architecture",
                    "must_produce": ["migration_risks"],
                }
            )
            role_b = json.dumps(
                {
                    "id": "migration-rollup",
                    "agent_ref": "agent-registry://rollup-editor",
                    "must_produce": ["migration_plan"],
                    "consumes": ["migration-analysis"],
                }
            )
            with contextlib.redirect_stdout(io.StringIO()) as stdout:
                rc = self.workflow_template_add.main(
                    [
                        tmp,
                        "--id",
                        "migration-plan",
                        "--workflow-kind",
                        "migration",
                        "--purpose",
                        "Plan a local migration workflow.",
                        "--role-json",
                        role_a,
                        "--role-json",
                        role_b,
                        "--json",
                    ]
                )

            payload = json.loads(stdout.getvalue())
            template = self.workflows.load_team_template(Path(tmp) / "migration-plan.json")

        self.assertEqual(rc, 0)
        self.assertEqual(payload["path"], str(Path(tmp) / "migration-plan.json"))
        self.assertEqual(template.id, "migration-plan")
        self.assertEqual(template.workflow_kind, "migration")
        self.assertEqual(template.role_phases(), [["migration-analysis"], ["migration-rollup"]])
        self.assertEqual(template.validate(), [])

    def test_workflow_template_add_cli_rejects_invalid_rollup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            role = json.dumps(
                {
                    "id": "single",
                    "agent_ref": "agent-registry://architecture",
                    "must_produce": ["migration_plan"],
                }
            )
            with contextlib.redirect_stderr(io.StringIO()):
                rc = self.workflow_template_add.main(
                    [
                        tmp,
                        "--id",
                        "bad-migration",
                        "--workflow-kind",
                        "migration",
                        "--role-json",
                        role,
                    ]
                )

        self.assertEqual(rc, 1)

    def test_workflow_lint_returns_nonzero_for_missing_agent_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            templates = root / "templates"
            templates.mkdir()
            (templates / "bad.json").write_text(
                json.dumps(
                    {
                        "id": "bad",
                        "roles": [
                            {
                                "id": "role",
                                "agent_ref": "agent-registry://missing",
                                "must_produce": ["out"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            registry = root / "registry.json"
            registry.write_text(json.dumps({"agents": {}}), encoding="utf-8")

            with contextlib.redirect_stdout(io.StringIO()):
                rc = self.workflow_lint.main(
                    [
                        "--team-templates",
                        str(templates),
                        "--agent-registry",
                        str(registry),
                        "--json",
                    ]
                )

        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
