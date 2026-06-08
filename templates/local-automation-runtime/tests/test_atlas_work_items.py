from __future__ import annotations

import importlib.machinery
import importlib.util
import contextlib
import io
import json
import shutil
import sys
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


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


class AtlasWorkItemProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.work_items = load_script("atlas_work_items_test", "atlas_work_items.py")
        sys.modules["atlas_work_items"] = cls.work_items
        cls.orchestrator = load_script("atlas_orchestrator_work_items_test", "atlas-agent-orchestrator")
        cls.add = load_script("atlas_work_item_add_test", "atlas-agent-work-item-add")
        cls.inspect = load_script("atlas_work_item_inspect_test", "atlas-agent-work-item-inspect")
        cls.requeue_stale = load_script("atlas_work_item_requeue_stale_test", "atlas-agent-work-item-requeue-stale")

    def write_store(self, path: Path, items: list[dict]) -> None:
        path.write_text(json.dumps({"version": 1, "work_items": items}, indent=2) + "\n", encoding="utf-8")

    def read_items(self, path: Path) -> list[dict]:
        return json.loads(path.read_text(encoding="utf-8"))["work_items"]

    def test_ready_work_item_projects_to_operation_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "work-items.json"
            self.write_store(
                store_path,
                [
                    {
                        "id": "WI-1",
                        "status": "ready",
                        "title": "Add local lifecycle loop",
                        "labels": ["area:runtime"],
                        "scheduler": {
                            "execution_repo": "local/atlas",
                            "write_scope": ["templates/local-automation-runtime"],
                            "parallel_group": "bootstrap",
                            "workflow_kind": "planning",
                            "team_template": "planning-design-doc",
                            "required_outputs": ["threat_model"],
                        },
                    }
                ],
            )

            provider = self.work_items.AtlasWorkItemOperationProvider(self.work_items.AtlasWorkItemStore(store_path))
            operations = provider.ready_operations()

        self.assertEqual(len(operations), 1)
        self.assertEqual(operations[0].source_id, "WI-1")
        self.assertEqual(operations[0].source_type, "atlas_work_item")
        self.assertEqual(operations[0].execution_repo, "local/atlas")
        self.assertEqual(operations[0].write_scope, ["templates/local-automation-runtime"])
        self.assertEqual(operations[0].metadata["workflow_kind"], "planning")
        self.assertEqual(operations[0].metadata["team_template"], "planning-design-doc")
        self.assertEqual(operations[0].metadata["required_outputs"], ["threat_model"])
        self.assertTrue(operations[0].ready)

    def test_add_work_item_cli_creates_ready_item_with_scheduler_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "work-items.json"

            with contextlib.redirect_stdout(io.StringIO()):
                rc = self.add.main(
                    [
                        str(store_path),
                        "--id",
                        "WI-1",
                        "--title",
                        "Review local evidence",
                        "--workflow-kind",
                        "review",
                        "--required-output",
                        "review_decision",
                        "--write-scope",
                        "templates/local-automation-runtime",
                        "--priority",
                        "p1",
                        "--critical-path-rank",
                        "4",
                        "--actor",
                        "test",
                        "--json",
                    ]
                )
            items = self.read_items(store_path)
            provider = self.work_items.AtlasWorkItemOperationProvider(self.work_items.AtlasWorkItemStore(store_path))
            ready = provider.ready_operations()

        self.assertEqual(rc, 0)
        self.assertEqual(items[0]["id"], "WI-1")
        self.assertEqual(items[0]["status"], "ready")
        self.assertEqual(items[0]["lifecycle"]["created_by"], "test")
        self.assertEqual(items[0]["scheduler"]["workflow_kind"], "review")
        self.assertEqual(items[0]["scheduler"]["required_outputs"], ["review_decision"])
        self.assertEqual(items[0]["scheduler"]["write_scope"], ["templates/local-automation-runtime"])
        self.assertEqual(items[0]["scheduler"]["critical_path_rank"], 4)
        self.assertEqual(items[0]["evidence"][0]["type"], "create")
        self.assertEqual(ready[0].source_id, "WI-1")

    def test_add_work_item_cli_selects_template_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "work-items.json"

            with contextlib.redirect_stdout(io.StringIO()):
                rc = self.add.main(
                    [
                        str(store_path),
                        "--id",
                        "WI-1",
                        "--workflow-kind",
                        "review",
                        "--required-output",
                        "review_decision",
                        "--team-templates",
                        str(ROOT / "team-templates"),
                        "--select-team-template",
                    ]
                )
            item = self.read_items(store_path)[0]
            evidence = item["evidence"][0]["evidence"]

        self.assertEqual(rc, 0)
        self.assertEqual(item["scheduler"]["team_template"], "review-evidence-gate")
        self.assertEqual(evidence["workflow_selection"]["selected_template"], "review-evidence-gate")
        self.assertEqual(evidence["workflow_selection"]["selection"]["status"], "use_existing_template")

    def test_add_work_item_cli_requires_template_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "work-items.json"

            with contextlib.redirect_stderr(io.StringIO()):
                rc = self.add.main(
                    [
                        str(store_path),
                        "--id",
                        "WI-1",
                        "--workflow-kind",
                        "review",
                        "--required-output",
                        "unknown_output",
                        "--team-templates",
                        str(ROOT / "team-templates"),
                        "--require-template-match",
                    ]
                )
            store_exists = store_path.exists()

        self.assertEqual(rc, 1)
        self.assertFalse(store_exists)

    def test_add_work_item_rejects_duplicate_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "work-items.json"
            self.write_store(store_path, [{"id": "WI-1", "status": "ready"}])

            with contextlib.redirect_stderr(io.StringIO()):
                rc = self.add.main([str(store_path), "--id", "WI-1"])
            items = self.read_items(store_path)

        self.assertEqual(rc, 1)
        self.assertEqual(len(items), 1)

    def test_open_dependency_blocks_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "work-items.json"
            self.write_store(
                store_path,
                [
                    {"id": "WI-1", "status": "ready", "scheduler": {"depends_on": ["WI-0"]}},
                    {"id": "WI-0", "status": "running"},
                ],
            )

            provider = self.work_items.AtlasWorkItemOperationProvider(self.work_items.AtlasWorkItemStore(store_path))

        self.assertEqual(provider.ready_operations(), [])

    def test_ready_operations_are_ordered_by_priority_then_critical_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "work-items.json"
            self.write_store(
                store_path,
                [
                    {"id": "WI-4", "status": "ready", "scheduler": {"priority": "p2", "critical_path_rank": 1}},
                    {"id": "WI-3", "status": "ready", "scheduler": {"priority": "p1", "critical_path_rank": 5}},
                    {"id": "WI-2", "status": "ready", "labels": ["priority:p0"]},
                    {"id": "WI-1", "status": "ready", "scheduler": {"priority": "p1", "critical_path_rank": 1}},
                ],
            )

            provider = self.work_items.AtlasWorkItemOperationProvider(self.work_items.AtlasWorkItemStore(store_path))
            ready = provider.ready_operations()
            states = provider.operation_states()

        self.assertEqual([state.source_id for state in ready], ["WI-2", "WI-1", "WI-3", "WI-4"])
        self.assertEqual([state.source_id for state in states], ["WI-4", "WI-3", "WI-2", "WI-1"])

    def test_operation_states_include_ready_blocked_active_and_terminal_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "work-items.json"
            self.write_store(
                store_path,
                [
                    {"id": "WI-1", "status": "ready", "scheduler": {"execution_repo": "local/atlas", "write_scope": ["runtime"]}},
                    {"id": "WI-2", "status": "ready", "scheduler": {"depends_on": ["WI-9"], "execution_repo": "local/atlas", "write_scope": ["runtime"]}},
                    {
                        "id": "WI-3",
                        "status": "running",
                        "scheduler": {"execution_repo": "other/repo", "write_scope": ["other"]},
                    },
                    {"id": "WI-4", "status": "done"},
                ],
            )

            provider = self.work_items.AtlasWorkItemOperationProvider(self.work_items.AtlasWorkItemStore(store_path))
            states = provider.operation_states()

        self.assertEqual([state.source_id for state in states], ["WI-1", "WI-2", "WI-3", "WI-4"])
        self.assertTrue(states[0].ready)
        self.assertIn("missing dependency: WI-9", states[1].blockers)
        self.assertIn("already claimed", states[2].blockers)
        self.assertIn("terminal state: done", states[3].blockers)

    def test_active_scope_conflict_blocks_overlapping_ready_item_but_allows_disjoint_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "work-items.json"
            self.write_store(
                store_path,
                [
                    {
                        "id": "WI-1",
                        "status": "running",
                        "scheduler": {
                            "execution_repo": "local/atlas",
                            "base_branch": "main",
                            "write_scope": ["runtime"],
                        },
                    },
                    {
                        "id": "WI-2",
                        "status": "ready",
                        "scheduler": {
                            "execution_repo": "local/atlas",
                            "base_branch": "main",
                            "write_scope": ["runtime"],
                        },
                    },
                    {
                        "id": "WI-3",
                        "status": "ready",
                        "scheduler": {
                            "execution_repo": "local/atlas",
                            "base_branch": "main",
                            "write_scope": ["docs"],
                        },
                    },
                ],
            )

            provider = self.work_items.AtlasWorkItemOperationProvider(self.work_items.AtlasWorkItemStore(store_path))
            states = provider.operation_states()
            ready = provider.ready_operations()

        self.assertIn("active scope conflict: WI-1", states[1].blockers)
        self.assertFalse(states[1].ready)
        self.assertTrue(states[2].ready)
        self.assertEqual([state.source_id for state in ready], ["WI-3"])

    def test_active_scope_conflict_is_conservative_when_scope_is_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "work-items.json"
            self.write_store(
                store_path,
                [
                    {"id": "WI-1", "status": "running", "scheduler": {"execution_repo": "local/atlas"}},
                    {
                        "id": "WI-2",
                        "status": "ready",
                        "scheduler": {
                            "execution_repo": "local/atlas",
                            "write_scope": ["docs"],
                        },
                    },
                ],
            )

            provider = self.work_items.AtlasWorkItemOperationProvider(self.work_items.AtlasWorkItemStore(store_path))
            states = provider.operation_states()

        self.assertIn("active scope conflict: WI-1", states[1].blockers)

    def test_work_item_inspect_summarizes_scheduler_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "work-items.json"
            self.write_store(
                store_path,
                [
                    {"id": "WI-1", "status": "ready", "scheduler": {"execution_repo": "local/atlas", "write_scope": ["runtime"]}},
                    {"id": "WI-2", "status": "ready", "scheduler": {"blockers": ["needs decision"], "execution_repo": "local/atlas", "write_scope": ["runtime"]}},
                    {
                        "id": "WI-3",
                        "status": "running",
                        "scheduler": {"execution_repo": "other/repo", "write_scope": ["other"]},
                    },
                    {"id": "WI-4", "status": "done"},
                ],
            )

            summary = self.inspect.inspect_store(store_path)

        self.assertEqual(summary["counts"], {"ready": 1, "blocked": 1, "active": 1, "terminal": 1})
        self.assertEqual(summary["items"][1]["status"], "blocked")
        self.assertEqual(summary["items"][1]["blockers"], ["blocker: needs decision"])

    def test_work_item_inspect_includes_workflow_lifecycle_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "work-items.json"
            self.write_store(
                store_path,
                [
                    {
                        "id": "WI-1",
                        "status": "ready",
                        "result": {
                            "status": "ready",
                            "returncode": 3,
                            "summary": "partial workflow",
                            "evidence": {
                                "team_template": "review-evidence-gate",
                                "workflow_kind": "review",
                                "completed_roles": ["code-review"],
                                "attempted_roles": ["code-review"],
                                "workflow_continuation": {
                                    "reason": "required workflow outputs remain incomplete",
                                    "next_status": "ready",
                                },
                                "workflow_selection": {
                                    "selected_template": "review-evidence-gate",
                                },
                                "team_run": {
                                    "run_id": "WI-1-run",
                                    "template_id": "review-evidence-gate",
                                    "workflow_kind": "review",
                                    "status": "running",
                                    "missing_outputs": {
                                        "review-rollup": ["review_decision"],
                                    },
                                },
                            },
                        },
                        "workflow_runs": [
                            {
                                "status": "running",
                                "team_run": {
                                    "run_id": "WI-1-run",
                                    "template_id": "review-evidence-gate",
                                    "workflow_kind": "review",
                                    "status": "running",
                                    "missing_outputs": {
                                        "review-rollup": ["review_decision"],
                                    },
                                },
                                "workflow_selection": {
                                    "selected_template": "review-evidence-gate",
                                },
                                "artifacts": {"team_run_path": str(root / "team-run.json")},
                            }
                        ],
                    }
                ],
            )

            summary = self.inspect.inspect_store(store_path)
            workflow = summary["items"][0]["workflow"]

        self.assertEqual(summary["counts"], {"ready": 1, "blocked": 0, "active": 0, "terminal": 0})
        self.assertEqual(summary["items"][0]["result"]["returncode"], 3)
        self.assertEqual(workflow["template_id"], "review-evidence-gate")
        self.assertEqual(workflow["selected_template"], "review-evidence-gate")
        self.assertEqual(workflow["status"], "running")
        self.assertEqual(workflow["completed_roles"], ["code-review"])
        self.assertEqual(workflow["missing_outputs"], {"review-rollup": ["review_decision"]})
        self.assertEqual(workflow["continuation"]["next_status"], "ready")
        self.assertEqual(workflow["artifact_paths"]["team_run_path"], str(root / "team-run.json"))

    def test_done_dependency_can_be_claimed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "work-items.json"
            self.write_store(
                store_path,
                [
                    {"id": "WI-1", "status": "ready", "scheduler": {"depends_on": ["WI-0"]}},
                    {"id": "WI-0", "status": "done"},
                ],
            )
            store = self.work_items.AtlasWorkItemStore(store_path)
            provider = self.work_items.AtlasWorkItemOperationProvider(store, claimed_by="test-worker")

            operation = provider.ready_operations()[0]
            claimed = provider.claim(operation)
            item = self.read_items(store_path)[0]

        self.assertIsNotNone(claimed)
        assert claimed is not None
        self.assertEqual(claimed.state, "running")
        self.assertIn("claimed_at", item["claim"])

    def test_run_worker_daemon_once_claims_and_records_result_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "work-items.json"
            self.write_store(store_path, [{"id": "WI-1", "status": "ready", "title": "Local task"}])
            store = self.work_items.AtlasWorkItemStore(store_path)
            provider = self.work_items.AtlasWorkItemOperationProvider(store, claimed_by="test-worker")
            worker = self.work_items.LocalCommandOperationWorker(None, jobs_dir=root / "jobs")

            processed = self.work_items.run_worker_daemon_once(provider, worker)
            item = self.read_items(store_path)[0]

        self.assertEqual(processed, 1)
        self.assertEqual(item["status"], "done")
        self.assertEqual(item["state"], "done")
        self.assertEqual(item["claim"]["claimed_by"], "test-worker")
        self.assertEqual([entry["type"] for entry in item["evidence"]], ["claim", "result"])
        self.assertEqual(item["result"]["returncode"], 0)
        self.assertEqual(item["result"]["status"], "done")

    def test_requeue_stale_claims_previews_and_applies_with_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "work-items.json"
            old_claim = "2026-05-31T00:00:00Z"
            self.write_store(
                store_path,
                [
                    {
                        "id": "WI-1",
                        "status": "running",
                        "state": "running",
                        "lifecycle": {"state": "running", "claimed_at": old_claim},
                        "claim": {"claimed_by": "old-worker", "claimed_at": old_claim},
                    },
                    {
                        "id": "WI-2",
                        "status": "running",
                        "state": "running",
                        "lifecycle": {"state": "running", "claimed_at": "2026-05-31T05:59:30Z"},
                    },
                ],
            )
            provider = self.work_items.AtlasWorkItemOperationProvider(self.work_items.AtlasWorkItemStore(store_path))

            preview = provider.requeue_stale_claims(
                stale_seconds=3600,
                requeued_by="test",
                now=datetime(2026, 5, 31, 6, 0, 0, tzinfo=timezone.utc),
                apply=False,
            )
            before = self.read_items(store_path)
            applied = provider.requeue_stale_claims(
                stale_seconds=3600,
                requeued_by="test",
                now=datetime(2026, 5, 31, 6, 0, 0, tzinfo=timezone.utc),
                apply=True,
            )
            after = self.read_items(store_path)

        self.assertEqual([record["source_id"] for record in preview], ["WI-1"])
        self.assertEqual(before[0]["status"], "running")
        self.assertEqual([record["source_id"] for record in applied], ["WI-1"])
        self.assertEqual(after[0]["status"], "ready")
        self.assertEqual(after[0]["lifecycle"]["state"], "ready")
        self.assertNotIn("claim", after[0])
        self.assertEqual(after[0]["previous_claims"][0]["claimed_by"], "old-worker")
        self.assertEqual(after[0]["evidence"][0]["type"], "requeue")
        self.assertEqual(after[1]["status"], "running")

    def test_requeue_stale_cli_defaults_to_preview(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "work-items.json"
            self.write_store(
                store_path,
                [
                    {
                        "id": "WI-1",
                        "status": "running",
                        "state": "running",
                        "lifecycle": {"state": "running", "claimed_at": "2026-05-31T00:00:00Z"},
                    }
                ],
            )

            records = self.requeue_stale.requeue_stale(
                store_path,
                stale_seconds=0,
                actor="test",
                apply=False,
            )
            item = self.read_items(store_path)[0]

        self.assertEqual(records[0]["source_id"], "WI-1")
        self.assertEqual(item["status"], "running")

    def test_orchestrator_local_work_item_path_does_not_query_github_issues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "work-items.json"
            self.write_store(store_path, [{"id": "WI-1", "status": "ready"}])
            args = types.SimpleNamespace(
                atlas_work_items=str(store_path),
                atlas_work_item_command=None,
                atlas_role_command_config=None,
                atlas_role_max=1,
                team_templates=None,
                max_items=1,
            )

            with mock.patch.object(self.orchestrator, "ready_issues", side_effect=AssertionError("GitHub path used")):
                with mock.patch.object(self.orchestrator.common, "jobs_dir", return_value=root / "jobs"):
                    processed = self.orchestrator.process_once(args)

            item = self.read_items(store_path)[0]

        self.assertEqual(processed, 1)
        self.assertEqual(item["status"], "done")
        self.assertEqual(item["evidence"][0]["type"], "claim")
        self.assertEqual(item["evidence"][1]["type"], "result")

    def test_orchestrator_local_work_item_dry_run_does_not_claim_or_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "work-items.json"
            self.write_store(store_path, [{"id": "WI-1", "status": "ready", "title": "Preview task"}])
            args = types.SimpleNamespace(
                atlas_work_items=str(store_path),
                atlas_work_item_command=None,
                atlas_role_command_config=None,
                atlas_role_max=1,
                team_templates=None,
                max_items=1,
                dry_run=True,
            )

            with mock.patch.object(self.orchestrator.common, "jobs_dir", side_effect=AssertionError("worker path used")):
                processed = self.orchestrator.process_once(args)
            item = self.read_items(store_path)[0]

        self.assertEqual(processed, 1)
        self.assertEqual(item["status"], "ready")
        self.assertNotIn("claim", item)
        self.assertNotIn("result", item)

    def test_orchestrator_can_run_role_runner_from_command_config(self) -> None:
        if not shutil.which("python3"):
            self.skipTest("python3 command unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            templates = root / "templates"
            templates.mkdir()
            (templates / "single-role.json").write_text(
                json.dumps(
                    {
                        "id": "single-role",
                        "name": "Single Role",
                        "workflow_kind": "review",
                        "roles": [
                            {
                                "id": "review",
                                "agent_ref": "agent-registry://review",
                                "must_produce": ["decision"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            command_config = root / "commands.json"
            command_config.write_text(
                json.dumps(
                    {
                        "agents": {
                            "agent-registry://review": [
                                "python3",
                                "-c",
                                (
                                    "import json, os;"
                                    "json.dump({"
                                    "'status':'complete',"
                                    "'outputs':{'decision':'pass'}"
                                    "}, open(os.environ['ATLAS_ROLE_RESULT_FILE'], 'w'))"
                                ),
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            store_path = root / "work-items.json"
            self.write_store(
                store_path,
                [
                    {
                        "id": "WI-1",
                        "status": "ready",
                        "scheduler": {"team_template": "single-role"},
                    }
                ],
            )
            args = types.SimpleNamespace(
                atlas_work_items=str(store_path),
                atlas_work_item_command=None,
                atlas_role_command_config=str(command_config),
                atlas_role_max=1,
                team_templates=str(templates),
                max_items=1,
            )

            with mock.patch.object(self.orchestrator.common, "jobs_dir", return_value=root / "jobs"):
                processed = self.orchestrator.process_once(args)
            item = self.read_items(store_path)[0]
            evidence = item["result"]["evidence"]
            rollup = Path(evidence["team_rollup_path"]).read_text(encoding="utf-8")

        self.assertEqual(processed, 1)
        self.assertEqual(evidence["team_run_status"], "complete")
        self.assertEqual(evidence["missing_outputs"], {})
        self.assertEqual(evidence["team_run"]["status"], "complete")
        self.assertEqual(evidence["team_run"]["missing_outputs"], {})
        self.assertEqual(evidence["attempted_roles"], ["review"])
        self.assertEqual(evidence["completed_roles"], ["review"])
        self.assertEqual(item["workflow_runs"][0]["team_run"]["status"], "complete")
        self.assertIn("decision: pass", item["workflow_runs"][0]["team_rollup_markdown"])
        self.assertIn("- decision: pass", rollup)

    def test_orchestrator_fake_execute_sample_completes_review_workflow(self) -> None:
        if not shutil.which("python3"):
            self.skipTest("python3 command unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "work-items.json"
            shutil.copyfile(ROOT / "examples" / "atlas-work-items.sample.json", store_path)
            args = types.SimpleNamespace(
                atlas_work_items=str(store_path),
                atlas_work_item_command=None,
                atlas_role_command_config=str(ROOT / "config" / "role-commands.fake-execute.example.json"),
                atlas_role_max=100,
                team_templates=str(ROOT / "team-templates"),
                max_items=1,
            )

            with mock.patch.object(self.orchestrator.common, "jobs_dir", return_value=root / "jobs"):
                processed = self.orchestrator.process_once(args)
            item = self.read_items(store_path)[0]
            evidence = item["result"]["evidence"]
            role_tasks = json.loads(Path(evidence["team_role_tasks_path"]).read_text(encoding="utf-8"))["tasks"]
            role_results = json.loads(Path(evidence["team_role_results_path"]).read_text(encoding="utf-8"))

        self.assertEqual(processed, 1)
        self.assertEqual(item["status"], "done")
        self.assertEqual(item["result"]["returncode"], 0)
        self.assertEqual(evidence["team_template"], "review-evidence-gate")
        self.assertEqual(evidence["team_run_status"], "complete")
        self.assertEqual(evidence["missing_outputs"], {})
        self.assertEqual(
            evidence["completed_roles"],
            ["code-review", "security-review", "semantic-review", "review-rollup"],
        )
        self.assertEqual(item["workflow_runs"][0]["status"], "complete")
        self.assertEqual(item["workflow_runs"][0]["team_run"]["missing_outputs"], {})
        self.assertEqual([task["status"] for task in role_tasks], ["complete", "complete", "complete", "complete"])
        self.assertEqual(role_tasks[-1]["consumed_role_results"]["code-review"]["status"], "complete")
        self.assertEqual(len(role_results), 4)

    def test_worker_writes_team_run_artifacts_for_workflow_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "work-items.json"
            self.write_store(
                store_path,
                [
                    {
                        "id": "WI-1",
                        "status": "ready",
                        "scheduler": {
                            "workflow_kind": "planning",
                            "required_outputs": ["threat_model", "validation_commands"],
                        },
                    }
                ],
            )
            store = self.work_items.AtlasWorkItemStore(store_path)
            provider = self.work_items.AtlasWorkItemOperationProvider(store, claimed_by="test-worker")
            worker = self.work_items.LocalCommandOperationWorker(
                None,
                jobs_dir=root / "jobs",
                templates_dir=ROOT / "team-templates",
                agent_registry_path=ROOT / "config" / "agent-registry.example.json",
                agent_root=ROOT.parents[1],
            )

            processed = self.work_items.run_worker_daemon_once(provider, worker)
            item = self.read_items(store_path)[0]
            result = item["result"]
            evidence = result["evidence"]
            rollup = Path(evidence["team_rollup_path"]).read_text(encoding="utf-8")
            role_tasks = json.loads(Path(evidence["team_role_tasks_path"]).read_text(encoding="utf-8"))["tasks"]

        self.assertEqual(processed, 1)
        self.assertEqual(evidence["team_template"], "planning-design-doc")
        self.assertEqual(evidence["workflow_kind"], "planning")
        self.assertEqual(evidence["workflow_selection"]["selected_template"], "planning-design-doc")
        self.assertEqual(evidence["workflow_selection"]["selection"]["status"], "use_existing_template")
        self.assertEqual(evidence["workflow_selection"]["selection"]["uncovered_required_outputs"], [])
        selection_candidate = next(
            candidate
            for candidate in evidence["workflow_selection"]["candidates"]
            if candidate["id"] == "planning-design-doc"
        )
        self.assertEqual(selection_candidate["missing_required_outputs"], [])
        self.assertIn("threat_model", selection_candidate["covered_required_outputs"])
        self.assertIn("security", evidence["team_roles"])
        self.assertIn("security", evidence["missing_outputs"])
        self.assertEqual(evidence["team_run_status"], "running")
        self.assertEqual(evidence["team_run"]["template_id"], "planning-design-doc")
        self.assertEqual(evidence["team_run"]["status"], "running")
        self.assertIn("security", evidence["team_run"]["missing_outputs"])
        self.assertEqual(item["workflow_runs"][0]["team_run"]["template_id"], "planning-design-doc")
        self.assertEqual(item["workflow_runs"][0]["status"], "running")
        self.assertIn("team_role_tasks_path", evidence)
        self.assertEqual(role_tasks[0]["template_id"], "planning-design-doc")
        self.assertIn("agent_ref", role_tasks[0])
        self.assertEqual(role_tasks[0]["agent_definition"]["id"], "architecture")
        self.assertEqual(role_tasks[4]["agent_definition"]["id"], "data-contracts")
        self.assertTrue(role_tasks[4]["agent_definition"]["source"].endswith("agents/data-contracts.md"))
        self.assertIn("## Missing Outputs", rollup)
        self.assertIn("security", rollup)

    def test_worker_command_can_fill_team_run_role_outputs(self) -> None:
        if not shutil.which("python3"):
            self.skipTest("python3 command unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            templates = root / "templates"
            templates.mkdir()
            (templates / "two-role.json").write_text(
                json.dumps(
                    {
                        "id": "two-role",
                        "name": "Two Role",
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
                ),
                encoding="utf-8",
            )
            store_path = root / "work-items.json"
            self.write_store(
                store_path,
                [
                    {
                        "id": "WI-1",
                        "status": "ready",
                        "scheduler": {"team_template": "two-role"},
                    }
                ],
            )
            command = [
                "python3",
                "-c",
                (
                    "import json, os;"
                    "json.dump(["
                    "{'role_id':'review','status':'complete','outputs':{'findings':'none'}},"
                    "{'role_id':'rollup','status':'complete','outputs':{'decision':'pass'}}"
                    "], open(os.environ['ATLAS_TEAM_ROLE_RESULTS_FILE'], 'w'))"
                ),
            ]
            store = self.work_items.AtlasWorkItemStore(store_path)
            provider = self.work_items.AtlasWorkItemOperationProvider(store, claimed_by="test-worker")
            worker = self.work_items.LocalCommandOperationWorker(command, jobs_dir=root / "jobs", templates_dir=templates)

            processed = self.work_items.run_worker_daemon_once(provider, worker)
            item = self.read_items(store_path)[0]
            result = item["result"]
            evidence = result["evidence"]
            rollup = Path(evidence["team_rollup_path"]).read_text(encoding="utf-8")
            role_tasks = json.loads(Path(evidence["team_role_tasks_path"]).read_text(encoding="utf-8"))["tasks"]

        self.assertEqual(processed, 1)
        self.assertEqual(result["returncode"], 0)
        self.assertEqual(evidence["team_run_status"], "complete")
        self.assertEqual(evidence["missing_outputs"], {})
        self.assertEqual(evidence["team_run"]["status"], "complete")
        self.assertEqual(evidence["team_run"]["missing_outputs"], {})
        self.assertEqual(evidence["attempted_roles"], ["review", "rollup"])
        self.assertEqual(evidence["completed_roles"], ["review", "rollup"])
        self.assertEqual(item["workflow_runs"][0]["team_run"]["status"], "complete")
        self.assertIn("findings: none", item["workflow_runs"][0]["team_rollup_markdown"])
        self.assertEqual([task["status"] for task in role_tasks], ["complete", "complete"])
        self.assertEqual([task["missing_outputs"] for task in role_tasks], [[], []])
        self.assertIn("- findings: none", rollup)
        self.assertIn("- decision: pass", rollup)

    def test_worker_fails_when_command_exits_zero_but_workflow_outputs_are_incomplete(self) -> None:
        if not shutil.which("python3"):
            self.skipTest("python3 command unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            templates = root / "templates"
            templates.mkdir()
            (templates / "single-role.json").write_text(
                json.dumps(
                    {
                        "id": "single-role",
                        "name": "Single Role",
                        "workflow_kind": "review",
                        "roles": [
                            {
                                "id": "review",
                                "agent_ref": "agents/review.md",
                                "must_produce": ["decision", "findings"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            store_path = root / "work-items.json"
            self.write_store(
                store_path,
                [
                    {
                        "id": "WI-1",
                        "status": "ready",
                        "scheduler": {"team_template": "single-role"},
                    }
                ],
            )
            command = [
                "python3",
                "-c",
                (
                    "import json, os;"
                    "json.dump([{'role_id':'review','status':'complete','outputs':{'decision':'pass'}}], "
                    "open(os.environ['ATLAS_TEAM_ROLE_RESULTS_FILE'], 'w'))"
                ),
            ]
            store = self.work_items.AtlasWorkItemStore(store_path)
            provider = self.work_items.AtlasWorkItemOperationProvider(store, claimed_by="test-worker")
            worker = self.work_items.LocalCommandOperationWorker(command, jobs_dir=root / "jobs", templates_dir=templates)

            processed = self.work_items.run_worker_daemon_once(provider, worker)
            item = self.read_items(store_path)[0]
            evidence = item["result"]["evidence"]
            team_run = json.loads(Path(evidence["team_run_path"]).read_text(encoding="utf-8"))

        self.assertEqual(processed, 1)
        self.assertEqual(item["status"], "failed")
        self.assertEqual(item["result"]["returncode"], 0)
        self.assertEqual(evidence["team_run_status"], "running")
        self.assertEqual(evidence["workflow_incomplete"]["next_status"], "failed")
        self.assertEqual(evidence["completed_roles"], [])
        self.assertEqual(evidence["attempted_roles"], ["review"])
        self.assertEqual(team_run["role_results"]["review"]["status"], "incomplete")
        self.assertIn(
            "missing required output(s): findings",
            team_run["role_results"]["review"]["contract_issues"],
        )

    def test_bounded_role_runner_requeues_and_resumes_incomplete_workflow(self) -> None:
        if not shutil.which("python3"):
            self.skipTest("python3 command unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            templates = root / "templates"
            templates.mkdir()
            (templates / "two-role.json").write_text(
                json.dumps(
                    {
                        "id": "two-role",
                        "name": "Two Role",
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
                ),
                encoding="utf-8",
            )
            command_config = root / "commands.json"
            command_config.write_text(
                json.dumps(
                    {
                        "default": [
                            "python3",
                            "-c",
                            (
                                "import json, os;"
                                "role=os.environ['ATLAS_ROLE_ID'];"
                                "outputs={'findings':'none'} if role == 'review' else {'decision':'pass'};"
                                "json.dump({'status':'complete','outputs':outputs}, "
                                "open(os.environ['ATLAS_ROLE_RESULT_FILE'], 'w'))"
                            ),
                        ]
                    }
                ),
                encoding="utf-8",
            )
            store_path = root / "work-items.json"
            self.write_store(
                store_path,
                [
                    {
                        "id": "WI-1",
                        "status": "ready",
                        "scheduler": {"team_template": "two-role"},
                    }
                ],
            )
            command = [
                str(ROOT / "atlas-agent-role-runner"),
                "--command-config",
                str(command_config),
                "--max-roles",
                "1",
            ]
            store = self.work_items.AtlasWorkItemStore(store_path)
            provider = self.work_items.AtlasWorkItemOperationProvider(store, claimed_by="test-worker")
            worker = self.work_items.LocalCommandOperationWorker(command, jobs_dir=root / "jobs", templates_dir=templates)

            first_processed = self.work_items.run_worker_daemon_once(provider, worker)
            first_item = self.read_items(store_path)[0]
            second_processed = self.work_items.run_worker_daemon_once(provider, worker)
            final_item = self.read_items(store_path)[0]
            final_evidence = final_item["result"]["evidence"]
            role_tasks = json.loads(Path(final_evidence["team_role_tasks_path"]).read_text(encoding="utf-8"))["tasks"]

        self.assertEqual(first_processed, 1)
        self.assertEqual(first_item["status"], "ready")
        self.assertEqual(first_item["result"]["status"], "ready")
        self.assertEqual(first_item["result"]["returncode"], 3)
        self.assertEqual(first_item["result"]["evidence"]["team_run_status"], "running")
        self.assertTrue(first_item["result"]["evidence"]["workflow_continuation"])
        self.assertEqual(first_item["result"]["evidence"]["completed_roles"], ["review"])
        self.assertEqual(first_item["workflow_runs"][0]["team_run"]["status"], "running")
        self.assertEqual(first_item["previous_claims"][0]["claimed_by"], "test-worker")
        self.assertEqual(second_processed, 1)
        self.assertEqual(final_item["status"], "done")
        self.assertEqual(final_item["result"]["returncode"], 0)
        self.assertTrue(final_evidence["workflow_resumed"])
        self.assertEqual(final_evidence["team_run_status"], "complete")
        self.assertEqual(final_evidence["completed_roles"], ["review", "rollup"])
        self.assertEqual(len(final_item["workflow_runs"]), 1)
        self.assertEqual(final_item["workflow_runs"][0]["team_run"]["status"], "complete")
        self.assertEqual([task["status"] for task in role_tasks], ["complete", "complete"])
        self.assertEqual(role_tasks[-1]["consumed_role_results"]["review"]["outputs"]["findings"], "none")


if __name__ == "__main__":
    unittest.main()
