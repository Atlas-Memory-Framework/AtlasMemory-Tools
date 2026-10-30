from __future__ import annotations

import importlib.machinery
import importlib.util
import contextlib
import io
import json
import multiprocessing
import os
import shutil
import subprocess
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


def _compete_for_projected_item(store_path: str, barrier, results, claimed_by: str) -> None:
    try:
        import atlas_work_items
        provider = atlas_work_items.AtlasWorkItemOperationProvider(
            atlas_work_items.AtlasWorkItemStore(store_path), claimed_by=claimed_by
        )
        operation = provider.ready_operations()[0]
        barrier.wait(timeout=8)
        result = provider.claim(operation)
        results.put((claimed_by, None if result is None else result.state, None))
    except BaseException as exc:
        results.put((claimed_by, None, f"{type(exc).__name__}: {exc}"))


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
        cls.role_codex = load_script("atlas_role_codex_context_test", "atlas-agent-role-codex")

    def write_store(self, path: Path, items: list[dict]) -> None:
        path.write_text(json.dumps({"version": 1, "work_items": items}, indent=2) + "\n", encoding="utf-8")

    def read_items(self, path: Path) -> list[dict]:
        return json.loads(path.read_text(encoding="utf-8"))["work_items"]

    def test_store_lock_tolerates_path_disappearing_before_stale_stat(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "store.lock"
            lock = self.work_items._StoreLock(lock_path)
            with mock.patch.object(Path, "exists", return_value=True), \
                    mock.patch.object(Path, "stat", side_effect=FileNotFoundError):
                lock._remove_stale_lock()
            with lock:
                self.assertTrue(lock_path.exists())

    def test_store_lock_stale_check_still_surfaces_other_stat_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "store.lock"
            lock_path.write_text("{}", encoding="utf-8")
            lock = self.work_items._StoreLock(lock_path)
            with mock.patch.object(Path, "exists", return_value=True), \
                    mock.patch.object(Path, "stat", side_effect=PermissionError("denied")):
                with self.assertRaises(PermissionError):
                    lock._remove_stale_lock()

    def test_store_lock_release_during_stat_returns_to_exclusive_acquisition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "store.lock"
            lock_path.write_text(json.dumps({"pid": 99999999}), encoding="utf-8")
            lock = self.work_items._StoreLock(lock_path)
            original_stat = Path.stat
            disappeared = False

            def release_then_stat(path, *args, **kwargs):
                nonlocal disappeared
                if path == lock_path and not disappeared:
                    disappeared = True
                    lock_path.unlink(missing_ok=True)
                    raise FileNotFoundError(path)
                return original_stat(path, *args, **kwargs)

            def exists_via_stat(path, *args, **kwargs):
                path.stat(*args, **kwargs)
                return True

            with mock.patch.object(Path, "stat", new=release_then_stat), \
                    mock.patch.object(Path, "exists", new=exists_via_stat):
                lock._remove_stale_lock()
                with lock:
                    self.assertTrue(lock_path.exists())
                    acquired = json.loads(lock_path.read_text(encoding="utf-8"))
                    self.assertEqual(acquired["pid"], __import__("os").getpid())
            self.assertFalse(lock_path.exists())

    def test_store_lock_preserves_fresh_live_owner_and_existing_stale_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "store.lock"
            lock_path.write_text(json.dumps({"pid": __import__("os").getpid()}), encoding="utf-8")
            lock = self.work_items._StoreLock(lock_path)
            lock._remove_stale_lock()
            self.assertTrue(lock_path.exists())

            lock_path.write_text(json.dumps({"pid": 99999999}), encoding="utf-8")
            with mock.patch.object(self.work_items.os, "kill", side_effect=ProcessLookupError):
                lock._remove_stale_lock()
            self.assertFalse(lock_path.exists())

            lock_path.write_text(json.dumps({"pid": __import__("os").getpid()}), encoding="utf-8")
            old = __import__("time").time() - 301
            __import__("os").utime(lock_path, (old, old))
            lock._remove_stale_lock()
            self.assertFalse(lock_path.exists())

    def test_independent_providers_only_one_claim_same_projected_ready_item(self) -> None:
        if "fork" not in multiprocessing.get_all_start_methods():
            self.skipTest("bounded fork-based provider contention requires fork")
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "work-items.json"
            metadata = {"owner": "queue-test", "retained": ["keep", 7]}
            unrelated = {"id": "WI-OTHER", "status": "ready", "metadata": {"keep": True}}
            self.write_store(store_path, [
                {"id": "WI-CLAIM", "status": "ready", "metadata": metadata,
                 "scheduler": {"execution_repo": "local/synthetic", "write_scope": ["src"]}},
                unrelated,
            ])
            context = multiprocessing.get_context("fork")
            barrier = context.Barrier(3)
            results = context.Queue()
            workers = [context.Process(
                target=_compete_for_projected_item,
                args=(str(store_path), barrier, results, f"competitor-{index}"),
            ) for index in range(2)]
            try:
                for process in workers:
                    process.start()
                barrier.wait(timeout=8)
                for process in workers:
                    process.join(timeout=8)
                self.assertTrue(all(not process.is_alive() for process in workers), "provider process timed out")
                records = [results.get(timeout=3) for _ in workers]
                self.assertTrue(all(record[2] is None for record in records), records)
                self.assertEqual(sum(record[1] == "running" for record in records), 1, records)
                self.assertEqual(sum(record[1] is None for record in records), 1, records)
                payload = json.loads(store_path.read_text(encoding="utf-8"))
                self.assertEqual(payload["version"], 1)
                items = {item["id"]: item for item in payload["work_items"]}
                claimed = items["WI-CLAIM"]
                self.assertEqual(claimed["status"], "running")
                self.assertIn(claimed["claim"]["claimed_by"], {"competitor-0", "competitor-1"})
                self.assertEqual(claimed["metadata"], metadata)
                self.assertEqual(items["WI-OTHER"], unrelated)
            finally:
                for process in workers:
                    if process.is_alive():
                        process.terminate()
                        process.join(timeout=2)
                    if process.is_alive() and hasattr(process, "kill"):
                        process.kill()
                        process.join(timeout=2)
                    process.close()
                results.close()
                results.join_thread()

    def test_write_scope_directories_and_globs_conflict_conservatively(self) -> None:
        overlap = self.work_items.write_scopes_overlap
        for left, right in [
            (["src"], ["src/a.py"]),
            (["src/**/*.py"], ["src/nested/a.py"]),
            (["src/a*.py"], ["src/abc.py"]),
            (["../other"], ["docs"]),
            (["**/a.py"], ["docs/a.py"]),
        ]:
            with self.subTest(left=left, right=right):
                self.assertTrue(overlap(left, right))
                self.assertTrue(overlap(right, left))
        self.assertFalse(overlap(["src"], ["src2/a.py"]))
        self.assertFalse(overlap(["src/a"], ["docs/b"]))

    def test_azure_record_cannot_be_claimed_by_legacy_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "work-items.json"
            self.write_store(store_path, [{"id": "azdo:Instablinds:Instablinds:17", "status": "ready"}])
            before = store_path.read_bytes()
            provider = self.work_items.AtlasWorkItemOperationProvider(self.work_items.AtlasWorkItemStore(store_path))
            operation = provider.operation_states()[0]
            self.assertFalse(operation.ready)
            self.assertIn("Azure records require the Azure worker and its authority gates", operation.blockers)
            self.assertIsNone(provider.claim(operation))
            self.assertEqual(before, store_path.read_bytes())

    def test_azure_origin_detection_recognizes_https_and_ssh_authorities(self) -> None:
        origins = [
            "https://dev.azure.com/Instablinds/Instablinds/_git/Website",
            "https://Instablinds@dev.azure.com/Instablinds/Instablinds/_git/Website",
            "https://username:placeholder@dev.azure.com/Instablinds/Instablinds/_git/Website",
            "https://DEV.AZURE.COM/Instablinds/Instablinds/_git/Website",
            "https://dev.azure.com.:443/Instablinds/Instablinds/_git/Website",
            "https://Instablinds.visualstudio.com/Instablinds/_git/Website",
            "https://Instablinds.visualstudio.com:443/DefaultCollection/Instablinds/_git/Website",
            "git@ssh.dev.azure.com:v3/Instablinds/Instablinds/Website",
            "ssh.dev.azure.com:v3/Instablinds/Instablinds/Website",
            "ssh://git@ssh.dev.azure.com/v3/Instablinds/Instablinds/Website",
            "ssh://git@SSH.DEV.AZURE.COM:22/v3/Instablinds/Instablinds/Website",
            "Instablinds@vs-ssh.visualstudio.com:v3/Instablinds/Instablinds/Website",
            "ssh://Instablinds@vs-ssh.visualstudio.com:22/v3/Instablinds/Instablinds/Website",
            # Classification excludes the legacy worker; it does not authorize
            # an Azure endpoint. An unsupported transport/port stays excluded.
            "http://dev.azure.com/Instablinds/Instablinds/_git/Website",
            "https://dev.azure.com:8443/Instablinds/Instablinds/_git/Website",
            "https://dev.azure.com:invalid/Instablinds/Instablinds/_git/Website",
            "git://dev.azure.com/Instablinds/Instablinds/_git/Website",
            "https://github.com@dev.azure.com/Instablinds/Instablinds/_git/Website",
            "https://dev.azure.com/Instablinds/Instablinds/_git/Website?redirect=github.com#fragment",
        ]
        for origin in origins:
            with self.subTest(origin=origin):
                self.assertTrue(self.work_items.is_azure_operation("WI-1", {}, origin))

    def test_azure_origin_detection_ignores_spoofed_hosts_and_embedded_references(self) -> None:
        origins = [
            "https://notdev.azure.com/org/repo",
            "https://dev.azure.com.evil.example/org/repo",
            "https://org.visualstudio.com.evil.example/org/repo",
            "https://org.notvisualstudio.com/org/repo",
            "https://dev.azure.com@github.com/org/repo",
            "https://org.visualstudio.com@github.com/org/repo",
            "https://github.com/org/dev.azure.com/repo",
            "https://github.com/org/project.visualstudio.com/repo",
            "https://github.com/org/dev.azure.com/",
            "https://github.com/org/project.visualstudio.com/",
            "https://github.com/org/repo?redirect=https://dev.azure.com/org/repo",
            "https://github.com/org/repo#https://org.visualstudio.com/project/repo",
            "git@github.com:org/dev.azure.com/repo",
            "git@github.com:org/project.visualstudio.com/repo",
            "ssh://git@github.com/dev.azure.com/org/repo",
            "git@ssh.dev.azure.com.evil.example:v3/org/project/repo",
            "Instablinds@vs-ssh.visualstudio.com.evil.example:v3/org/project/repo",
            "dev.azure.com/org/project/repo",
            "/tmp/dev.azure.com/org/project/repo",
            "file:///tmp/org.visualstudio.com/project/repo",
            "https://visualstudio.com/org/repo",
            "https://org..visualstudio.com/org/repo",
            "https://[dev.azure.com/org/repo",
            "https://[::1/org.visualstudio.com/repo",
            "https:///dev.azure.com/org/repo",
            "",
        ]
        for origin in origins:
            with self.subTest(origin=origin):
                self.assertFalse(self.work_items.is_azure_operation("WI-1", {}, origin))

    def test_explicit_azure_identity_is_preserved_regardless_of_origin(self) -> None:
        for source_id, metadata in [
            ("AZDO:Instablinds:Instablinds:17", {}),
            ("azure:Instablinds/Instablinds:17", {"provider": "github"}),
            ("WI-1", {"provider": "azure-devops"}),
            ("WI-1", {"provider": "AZURE_DEVOPS"}),
            ("WI-1", {"provider": "azure"}),
        ]:
            with self.subTest(source_id=source_id, metadata=metadata):
                self.assertTrue(self.work_items.is_azure_operation(source_id, metadata, "https://github.com/org/repo"))
        self.assertTrue(self.work_items.is_azure_operation("WI-1", {"provider": "github"}, "https://dev.azure.com/org/project/_git/repo"))

    def test_azure_origins_block_legacy_projection_claims_and_worker_without_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "work-items.json"
            worker = self.work_items.LocalCommandOperationWorker([sys.executable, "-c", "pass"], jobs_dir=root / "jobs")
            for origin in [
                "https://dev.azure.com:443/Instablinds/Instablinds/_git/Website",
                "git@ssh.dev.azure.com:v3/Instablinds/Instablinds/Website",
                "Instablinds@vs-ssh.visualstudio.com:v3/Instablinds/Instablinds/Website",
            ]:
                with self.subTest(origin=origin):
                    self.write_store(store_path, [{"id": "WI-1", "status": "ready", "scheduler": {"execution_repo": origin}}])
                    before = store_path.read_bytes()
                    provider = self.work_items.AtlasWorkItemOperationProvider(self.work_items.AtlasWorkItemStore(store_path))
                    operation = provider.operation_states()[0]
                    self.assertFalse(operation.ready)
                    self.assertIsNone(provider.claim(operation))
                    result = worker.run(operation, store_path)
                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(result.status, "failed")
                    self.assertIn("Azure worker", result.summary)
                    self.assertEqual(before, store_path.read_bytes())
                    self.assertFalse(worker.jobs_dir.exists())

    def test_github_repo_with_azure_text_remains_eligible_for_legacy_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "work-items.json"
            self.write_store(store_path, [{"id": "WI-1", "status": "ready", "metadata": {"provider": "github"},
                                          "scheduler": {"execution_repo": "https://github.com/org/dev.azure.com/"}}])
            provider = self.work_items.AtlasWorkItemOperationProvider(self.work_items.AtlasWorkItemStore(store_path))
            operation = provider.operation_states()[0]
            self.assertTrue(operation.ready)
            self.assertEqual(operation.blockers, [])
            self.assertIsNotNone(provider.claim(operation))

    def test_successful_exit_without_acceptance_evidence_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "work-items.json"
            self.write_store(store_path, [{"id": "WI-1", "status": "ready"}])
            provider = self.work_items.AtlasWorkItemOperationProvider(self.work_items.AtlasWorkItemStore(store_path))
            worker = self.work_items.LocalCommandOperationWorker([sys.executable, "-c", "pass"], jobs_dir=root / "jobs")
            self.work_items.run_worker_daemon_once(provider, worker)
            item = self.read_items(store_path)[0]
            self.assertEqual(item["status"], "failed")
            self.assertIn("acceptance", item["result"]["summary"])

    def test_missing_executable_records_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "work-items.json"
            self.write_store(store_path, [{"id": "WI-1", "status": "ready"}])
            provider = self.work_items.AtlasWorkItemOperationProvider(self.work_items.AtlasWorkItemStore(store_path))
            worker = self.work_items.LocalCommandOperationWorker([str(root / "missing-command")], jobs_dir=root / "jobs")
            self.work_items.run_worker_daemon_once(provider, worker)
            item = self.read_items(store_path)[0]
            self.assertEqual(item["status"], "blocked")
            self.assertEqual(item["process_uncertainty"]["status"], "unresolved")
            self.assertNotEqual(item["result"]["returncode"], 0)

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

    def test_work_item_context_reaches_initial_refreshed_and_resumed_role_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "work-items.json"
            item = {
                "id": "WI-context", "status": "ready", "title": "Implement bounded packet context",
                "description": "Carry the actual source task into delegated reviewer prompts.",
                "goal": "Review whether goals and scope survive the complete workflow lifecycle.",
                "acceptance_criteria": ["The downstream reviewer sees the source goal."],
                "validation": ["python3 -m unittest tests.test_atlas_work_items"],
                "write_scope": ["templates/local-automation-runtime/atlas_work_items.py"],
                "spec_path": "specs/packet-context.md", "spec_hash": "sha256:source-spec",
                "metadata": {
                    "source_kind": "plan-package", "manifest_leaf_id": "packet-context",
                    "package_id": "pkg-context", "package_hash": "sha256:package",
                    "source_plan": {"path": "plan.md", "hash": "sha256:plan", "secret": "drop-me"},
                    "required_gates": ["reviewed"], "files_out_of_scope": ["secrets/"],
                    "acceptance_criteria": ["The downstream reviewer sees the source goal."],
                    "credential": "drop-me-too",
                },
                "scheduler": {
                    "team_template": "review-evidence-gate", "workflow_kind": "review",
                    "execution_repo": "https://username:placeholder@github.com/example/repo.git",
                    "base_branch": "local-context",
                },
                "lifecycle": {"state": "ready", "private": "omit"},
                "evidence": [{"private": "omit"}],
            }
            self.write_store(store_path, [item])
            provider = self.work_items.AtlasWorkItemOperationProvider(self.work_items.AtlasWorkItemStore(store_path))
            operation = provider.ready_operations()[0]
            worker = self.work_items.LocalCommandOperationWorker(
                None, jobs_dir=root / "jobs", templates_dir=ROOT / "team-templates"
            )
            job = root / "job"
            job.mkdir()
            evidence = worker.write_workflow_artifacts(operation, job, "first", store_path)
            packet_path = Path(evidence["team_role_tasks_path"])
            packet = json.loads(packet_path.read_text(encoding="utf-8"))["tasks"][0]
            prompt = self.role_codex.build_prompt(packet, root / "result.json")
            self.assertIn("Review whether goals and scope survive", prompt)
            self.assertIn("templates/local-automation-runtime/atlas_work_items.py", prompt)
            self.assertNotIn("drop-me", prompt)
            self.assertNotIn("username:placeholder", prompt)
            self.assertEqual(packet["work_item_context"]["execution_repo"], "https://github.com/example/repo.git")
            self.assertEqual(packet["work_item_context"]["base_branch"], "local-context")
            self.assertEqual(operation.execution_repo, item["scheduler"]["execution_repo"])

            results_path = root / "role-results.json"
            results_path.write_text(json.dumps([{
                "role_id": "code-review", "status": "complete", "outputs": {
                    "correctness_findings": "none", "regression_risks": "none", "test_gaps": "none",
                },
            }]), encoding="utf-8")
            refreshed = worker.apply_workflow_role_results(evidence, results_path)
            retained_rollup = refreshed["team_rollup_markdown"]
            self.assertEqual(retained_rollup, Path(refreshed["team_rollup_path"]).read_text(encoding="utf-8"))
            # Provider recording must use retained evidence even if the old
            # pathname has changed since the producer returned.
            Path(refreshed["team_rollup_path"]).write_text("replaced after return", encoding="utf-8")
            record = self.work_items.workflow_run_record(
                self.work_items.OperationResult("ready", 0, "partial workflow", refreshed),
                allow_path_fallback=False,
            )
            self.assertEqual(record["team_rollup_markdown"], retained_rollup[:20000])
            refreshed_packet = json.loads(packet_path.read_text(encoding="utf-8"))["tasks"][1]
            self.assertEqual(refreshed_packet["work_item_context"], operation.work_item_context)
            self.assertIn("Review whether goals and scope survive", self.role_codex.build_prompt(refreshed_packet, "result"))

            # Persist the incomplete run exactly as the provider does so the next
            # operation projection can resume it and regenerate the same context.
            stored = self.read_items(store_path)[0]
            stored["workflow_runs"] = [{
                "contract_hash": refreshed["contract_hash"], "rework_count": 0,
                "team_run": json.loads(Path(refreshed["team_run_path"]).read_text(encoding="utf-8")),
                "artifacts": {"team_run_path": refreshed["team_run_path"]},
            }]
            self.write_store(store_path, [stored])
            resumed_operation = provider.project(stored)
            resume_job = root / "resume-job"
            resume_job.mkdir()
            resumed = worker.write_workflow_artifacts(resumed_operation, resume_job, "second", store_path)
            resumed_tasks = json.loads(Path(resumed["team_role_tasks_path"]).read_text(encoding="utf-8"))["tasks"]
            self.assertTrue(resumed["workflow_resumed"])
            self.assertEqual(resumed_tasks[1]["work_item_context"], operation.work_item_context)
            self.assertIn("Review whether goals and scope survive", self.role_codex.build_prompt(resumed_tasks[1], "result"))

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

    def test_blocked_goal_review_result_projects_recorded_verdict_and_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "work-items.json"
            self.write_store(store_path, [{
                "id": "WI-BLOCKED", "status": "blocked",
                "scheduler": {"workflow_kind": "work-item"},
                "result": {"status": "blocked", "returncode": 2,
                    "summary": "Local workflow blocked: goal acceptance review failed",
                    "evidence": {"goal_acceptance": {
                        "verdict": "fail", "reason": "Acceptance criterion lacks evidence."}}},
            }])
            state = self.work_items.AtlasWorkItemOperationProvider(
                self.work_items.AtlasWorkItemStore(store_path)).operation_states()[0]
        self.assertFalse(state.ready)
        self.assertTrue(any("goal review fail" in blocker and "Acceptance criterion lacks evidence." in blocker
                            for blocker in state.blockers))

    def test_blocked_execution_result_projects_concrete_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "work-items.json"
            self.write_store(store_path, [{
                "id": "WI-FAILED", "status": "blocked",
                "result": {"status": "failed", "returncode": 1,
                    "summary": "Worker failed: validation command returned 1"},
            }])
            state = self.work_items.AtlasWorkItemOperationProvider(
                self.work_items.AtlasWorkItemStore(store_path)).operation_states()[0]
        self.assertTrue(any("Worker failed: validation command returned 1" in blocker
                            for blocker in state.blockers))

    def test_blocked_goal_review_with_missing_reason_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "work-items.json"
            self.write_store(store_path, [{
                "id": "WI-MALFORMED", "status": "blocked",
                "result": {"status": "blocked", "evidence": {
                    "goal_acceptance": {"verdict": "unexpected", "reason": ["bad"]}}},
            }])
            state = self.work_items.AtlasWorkItemOperationProvider(
                self.work_items.AtlasWorkItemStore(store_path)).operation_states()[0]
        self.assertFalse(state.ready)
        self.assertEqual(state.blockers, ["goal review inconclusive: reason unavailable"])

    def test_ready_item_result_does_not_change_ready_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "work-items.json"
            self.write_store(store_path, [{
                "id": "WI-READY", "status": "ready",
                "result": {"status": "blocked", "summary": "historical result"},
            }])
            state = self.work_items.AtlasWorkItemOperationProvider(
                self.work_items.AtlasWorkItemStore(store_path)).operation_states()[0]
        self.assertTrue(state.ready)
        self.assertEqual(state.blockers, [])

    def test_fresh_process_inspection_surfaces_block_reason_without_store_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "work-items.json"
            self.write_store(store_path, [{
                "id": "WI-BLOCKED", "status": "blocked",
                "result": {"status": "blocked", "returncode": 2,
                    "summary": "Local workflow blocked",
                    "evidence": {"goal_acceptance": {
                        "verdict": "fail", "reason": "Criterion lacks evidence."}}},
            }])
            before = store_path.read_bytes()
            inspector = ROOT / "atlas-agent-work-item-inspect"
            text_result = subprocess.run(
                [sys.executable, str(inspector), str(store_path)], capture_output=True, text=True, check=True)
            json_result = subprocess.run(
                [sys.executable, str(inspector), str(store_path), "--json"], capture_output=True, text=True, check=True)
            after = store_path.read_bytes()
        self.assertIn("goal review fail: Criterion lacks evidence.", text_result.stdout)
        projection = json.loads(json_result.stdout)
        self.assertEqual(projection["items"][0]["blockers"], [
            "goal review fail: Criterion lacks evidence.",
            "execution blocked: Local workflow blocked",
        ])
        self.assertEqual(after, before)

    def test_fresh_process_inspection_keeps_goal_and_worker_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "work-items.json"
            self.write_store(store_path, [{
                "id": "WI-MIXED", "status": "blocked",
                "result": {"status": "blocked", "summary": "Worker failed: validation command returned 1",
                    "evidence": {"goal_acceptance": {"verdict": "pass", "reason": "Criteria met."},
                        "workflow_result_error": "Malformed role results: JSON parse failed"}},
            }])
            before = store_path.read_bytes()
            inspector = ROOT / "atlas-agent-work-item-inspect"
            outputs = [subprocess.run([sys.executable, str(inspector), str(store_path), *extra],
                capture_output=True, text=True, check=True).stdout for extra in ([], ["--json"])]
            after = store_path.read_bytes()
        projection = json.loads(outputs[1])["items"][0]
        self.assertFalse(projection["ready"])
        self.assertTrue(any("goal review pass: Criteria met." in value for value in projection["blockers"]))
        self.assertTrue(any("Malformed role results: JSON parse failed" in value for value in projection["blockers"]))
        self.assertTrue(any("Worker failed: validation command returned 1" in value for value in projection["blockers"]))
        self.assertIn("goal review pass: Criteria met.", outputs[0])
        self.assertIn("Malformed role results: JSON parse failed", outputs[0])
        self.assertEqual(after, before)

    def test_fresh_process_inspection_surfaces_actual_worker_role_json_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = {"goal": "Review probe", "acceptance_criteria": ["Probe criterion"]}
            operation = self.work_items.OperationState(
                operation_id="probe", source_type="atlas_work_item", source_id="WI-PARSE-ERROR",
                title="Review probe", state="running", ready=False, blockers=[],
                metadata={"workflow_kind": "work-item", "team_template": "work-item-change-lifecycle"},
                work_item_context=context,
            )
            child = "import os,pathlib;pathlib.Path(os.environ['ATLAS_TEAM_ROLE_RESULTS_FILE']).write_text('{');print('Worker failed: invalid role JSON')"
            worker = self.work_items.LocalCommandOperationWorker(
                [sys.executable, "-c", child], jobs_dir=root / "jobs",
                templates_dir=ROOT / "team-templates")
            store_path = root / "work-items.json"
            self.write_store(store_path, [{"id": "WI-PARSE-ERROR", "status": "running", "state": "running"}])
            result = worker.run(operation, store_path)
            self.assertTrue(result.evidence.get("workflow_result_error"))
            self.assertEqual(result.status, "blocked")
            self.write_store(store_path, [{"id": "WI-PARSE-ERROR", "status": "blocked", "result": result.to_dict()}])
            before = store_path.read_bytes()
            inspector = ROOT / "atlas-agent-work-item-inspect"
            outputs = [subprocess.run([sys.executable, str(inspector), str(store_path), *extra],
                capture_output=True, text=True, check=True).stdout for extra in ([], ["--json"])]
            after = store_path.read_bytes()
        projection = json.loads(outputs[1])["items"][0]
        self.assertFalse(projection["ready"])
        expected_error = result.evidence["workflow_result_error"][:300]
        self.assertTrue(any(expected_error in value for value in projection["blockers"]))
        self.assertIn(expected_error, outputs[0])
        self.assertEqual(after, before)

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
        self.assertEqual(item["status"], "failed")
        self.assertEqual(item["state"], "failed")
        self.assertEqual(item["claim"]["claimed_by"], "test-worker")
        self.assertEqual([entry["type"] for entry in item["evidence"]], ["claim", "result"])
        self.assertNotEqual(item["result"]["returncode"], 0)
        self.assertEqual(item["result"]["status"], "failed")

    def test_ordinary_daemon_refuses_pilot_task_before_claim_or_worker_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "work-items.json"
            self.write_store(store_path, [{"id": "WI-PILOT", "status": "ready",
                "metadata": {"atlas_delta_review_pilot_v1": {"enabled": True}}}])
            before = store_path.read_bytes()
            provider = self.work_items.AtlasWorkItemOperationProvider(self.work_items.AtlasWorkItemStore(store_path))
            worker = mock.Mock()
            with self.assertRaisesRegex(self.work_items.PilotTaskRequiresSupervisedHandoff, "supervised in-app handoff"):
                self.work_items.run_worker_daemon_once(provider, worker)
            self.assertEqual(store_path.read_bytes(), before)
            worker.run.assert_not_called()

    def test_direct_record_result_cannot_mark_pilot_task_done_without_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "work-items.json"
            self.write_store(store_path, [{"id": "WI-PILOT", "status": "running",
                "metadata": {"atlas_delta_review_pilot_v1": {"enabled": True}}}])
            before = store_path.read_bytes()
            provider = self.work_items.AtlasWorkItemOperationProvider(self.work_items.AtlasWorkItemStore(store_path))
            operation = provider.operation_states()[0]
            result = self.work_items.OperationResult(status="done", returncode=0, summary="bypass attempt")
            with self.assertRaisesRegex(ValueError, "pilot metadata is missing or malformed"):
                provider.record_result(operation, result)
            self.assertEqual(store_path.read_bytes(), before)

    def test_record_result_rejects_pilot_checkout_changed_after_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkout_a = root / "checkout-a"
            checkout_b = root / "checkout-b"
            checkout_a.mkdir()
            checkout_b.mkdir()
            store_path = root / "work-items.json"
            self.write_store(store_path, [{
                "id": "WI-PILOT-MOVED",
                "status": "running",
                "scheduler": {"execution_repo": str(checkout_a)},
                "metadata": {"atlas_delta_review_pilot_v1": {
                    "enabled": True,
                    "repository_root": str(checkout_a),
                    "required_checks": [
                        {"id": "code", "lane": "code", "argv": [sys.executable, "-c", "pass"], "timeout_seconds": 30},
                        {"id": "environment", "lane": "environment", "argv": [sys.executable, "-c", "pass"], "timeout_seconds": 30},
                        {"id": "tests", "lane": "test", "argv": [sys.executable, "-c", "pass"], "timeout_seconds": 30},
                    ],
                    "evidence": {},
                }},
            }])
            provider = self.work_items.AtlasWorkItemOperationProvider(
                self.work_items.AtlasWorkItemStore(store_path)
            )
            stale_operation = provider.operation_states()[0]
            payload = json.loads(store_path.read_text(encoding="utf-8"))
            payload["work_items"][0]["scheduler"]["execution_repo"] = str(checkout_b)
            store_path.write_text(json.dumps(payload), encoding="utf-8")
            before = store_path.read_bytes()

            with self.assertRaisesRegex(ValueError, "execution repository changed since operation projection"):
                provider.record_result(stale_operation, self.work_items.OperationResult(
                    status="done", returncode=0, summary="stale checkout completion attempt"
                ))

            self.assertEqual(store_path.read_bytes(), before)

    def test_nonpilot_record_result_can_still_complete_normally(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "work-items.json"
            self.write_store(store_path, [{"id": "WI-ORDINARY", "status": "running"}])
            provider = self.work_items.AtlasWorkItemOperationProvider(self.work_items.AtlasWorkItemStore(store_path))
            operation = provider.operation_states()[0]
            provider.record_result(operation, self.work_items.OperationResult(
                status="done", returncode=0, summary="ordinary accepted completion"))
            item = self.read_items(store_path)[0]
        self.assertEqual(item["status"], "done")
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

    def test_cancel_before_start_does_not_launch_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "work-items.json"
            self.write_store(store_path, [{"id": "WI-CANCEL", "status": "running", "state": "running"}])
            operation = self.work_items.AtlasWorkItemOperationProvider(self.work_items.AtlasWorkItemStore(store_path)).operation_states()[0]
            cancel = __import__("threading").Event()
            cancel.set()
            worker = self.work_items.LocalCommandOperationWorker([sys.executable, "-c", "raise SystemExit(99)"], jobs_dir=root / "jobs")
            with mock.patch.object(self.work_items.subprocess, "Popen", side_effect=AssertionError("must not launch")):
                result = worker.run(operation, store_path, cancel_event=cancel)
            self.assertTrue(result.evidence["cancelled_before_start"])
            self.assertEqual(self.read_items(store_path)[0]["status"], "running")

    def test_contracted_job_artifact_reader_rejects_symlink_and_oversize(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / "outside.json"
            outside.write_text('{"role_results": []}', encoding="utf-8")
            (root / "linked.json").symlink_to(outside)
            (root / "large.json").write_bytes(b"x" * 9)
            os.mkfifo(root / "blocked.json")
            directory_fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                with self.assertRaises(OSError):
                    self.work_items._read_job_file(directory_fd, "linked.json", limit=64)
                with self.assertRaises(OSError):
                    self.work_items._read_job_file(directory_fd, "large.json", limit=8)
                open_file = os.open
                def require_nonblocking(path, flags, *args, **kwargs):
                    if path == "blocked.json":
                        self.assertTrue(flags & getattr(os, "O_NONBLOCK", 0))
                    return open_file(path, flags, *args, **kwargs)
                with mock.patch.object(self.work_items.os, "open", side_effect=require_nonblocking):
                    with self.assertRaises(OSError):
                        self.work_items._read_job_file(directory_fd, "blocked.json", limit=64)
                self.assertEqual(outside.read_text(encoding="utf-8"), '{"role_results": []}')
            finally:
                os.close(directory_fd)

    def test_contracted_workflow_consumer_reads_and_publishes_through_held_job_fd(self) -> None:
        import atlas_workflows

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job_dir = root / "job"
            job_dir.mkdir()
            templates = root / "templates"
            templates.mkdir()
            (templates / "two-role.json").write_text(json.dumps({
                "id": "two-role", "name": "Two Role", "workflow_kind": "test",
                "roles": [
                    {"id": "review", "agent_ref": "agents/review.md", "must_produce": ["findings"]},
                    {"id": "rollup", "agent_ref": "agents/rollup.md", "consumes": ["review"],
                     "must_produce": ["decision"]},
                ],
            }), encoding="utf-8")
            template = atlas_workflows.load_team_templates(templates)[0]
            run = atlas_workflows.TeamRun.start(run_id="run-1", template=template, work_item_id="WI-FD")
            run_path = job_dir / "team-run.json"
            results_path = job_dir / "team-role-results.json"
            rollup_path = job_dir / "team-rollup.md"
            tasks_path = job_dir / "team-role-tasks.json"
            run_path.write_text(json.dumps(run.to_dict()), encoding="utf-8")
            results_path.write_text(json.dumps([
                {"role_id": "review", "status": "complete", "outputs": {"findings": "no issue"}},
                {"role_id": "rollup", "status": "complete", "outputs": {"decision": "pass"}},
            ]), encoding="utf-8")
            rollup_path.write_text("initial", encoding="utf-8")
            tasks_path.write_text("{}", encoding="utf-8")
            worker = self.work_items.LocalCommandOperationWorker(
                None, jobs_dir=root / "jobs", templates_dir=templates,
            )
            evidence = {
                "team_template": "two-role", "team_run_path": str(run_path),
                "team_rollup_path": str(rollup_path), "team_role_tasks_path": str(tasks_path),
                "work_item_context": {}, "contract_hash": "contract-1",
            }
            parent_fd = os.open(job_dir.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            directory_fd = os.open(job_dir.name, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0), dir_fd=parent_fd)
            parent_stat = os.fstat(parent_fd)
            try:
                updated = worker.apply_workflow_role_results(
                    evidence, results_path, job_dir_fd=directory_fd, job_dir=job_dir,
                    job_parent_fd=parent_fd, job_parent_identity=(parent_stat.st_dev, parent_stat.st_ino),
                )
            finally:
                os.close(directory_fd)
                os.close(parent_fd)

            saved_run = atlas_workflows.TeamRun.from_dict(json.loads(run_path.read_text(encoding="utf-8")))
            saved_packets = json.loads(tasks_path.read_text(encoding="utf-8"))["tasks"]

        self.assertEqual(updated["team_run_status"], "complete")
        self.assertIn("no issue", updated["team_rollup_markdown"])
        self.assertEqual(saved_run.status, "complete")
        self.assertEqual([packet["status"] for packet in saved_packets], ["complete", "complete"])

    def test_contracted_worker_completes_valid_result_through_held_job_fd(self) -> None:
        import atlas_workflows

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            templates = root / "templates"
            templates.mkdir()
            (templates / "two-role.json").write_text(json.dumps({
                "id": "two-role", "name": "Two Role", "workflow_kind": "test",
                "roles": [
                    {"id": "review", "agent_ref": "agents/review.md", "must_produce": ["findings"]},
                    {"id": "rollup", "agent_ref": "agents/rollup.md", "consumes": ["review"],
                     "must_produce": ["decision"]},
                ],
            }), encoding="utf-8")
            store_path = root / "work-items.json"
            self.write_store(store_path, [{
                "id": "WI-VALID-FD", "status": "running", "state": "running",
                "scheduler": {"team_template": "two-role"},
                "metadata": {"local_execution_v1": {
                    "policy_id": "local-luna-unit-v1",
                    "role_purposes": {"implementation": "implementation"},
                    "changed_interfaces": [], "unresolved_questions": [], "complexity_flags": [],
                }},
            }])
            provider = self.work_items.AtlasWorkItemOperationProvider(
                self.work_items.AtlasWorkItemStore(store_path), claimed_by="test-worker",
            )
            operation = provider.operation_states()[0]
            runner = ROOT / "atlas-agent-role-runner"
            worker = self.work_items.LocalCommandOperationWorker(
                [str(runner), "--command-config", str(root / "commands.json"), "--max-roles", "1"],
                jobs_dir=root / "jobs", templates_dir=templates,
            )

            def workflow_artifacts(_operation, job_dir, _job_id, _store_path):
                template = atlas_workflows.load_team_templates(templates)[0]
                team_run = atlas_workflows.TeamRun.start(
                    run_id="run-valid-fd", template=template, work_item_id="WI-VALID-FD",
                )
                run_path = job_dir / "team-run.json"
                rollup_path = job_dir / "team-rollup.md"
                tasks_path = job_dir / "team-role-tasks.json"
                run_path.write_text(json.dumps(team_run.to_dict()), encoding="utf-8")
                rollup_path.write_text("initial", encoding="utf-8")
                tasks_path.write_text("{}", encoding="utf-8")
                return {
                    "team_template": "two-role", "team_run_path": str(run_path),
                    "team_rollup_path": str(rollup_path), "team_role_tasks_path": str(tasks_path),
                    "team_run_status": "running", "goal_review_required": False,
                    "work_item_context": operation.work_item_context, "contract_hash": "contract-valid",
                }

            def valid_launch(_command, *, env, **_kwargs):
                Path(env["ATLAS_TEAM_ROLE_RESULTS_FILE"]).write_text(json.dumps([
                    {"role_id": "review", "status": "complete", "outputs": {"findings": "no issue"}},
                    {"role_id": "rollup", "status": "complete", "outputs": {"decision": "pass"}},
                ]), encoding="utf-8")
                return types.SimpleNamespace(pid=987654322, returncode=0)

            with mock.patch.object(worker, "write_workflow_artifacts", side_effect=workflow_artifacts), \
                    mock.patch.object(self.work_items.subprocess, "Popen", side_effect=valid_launch), \
                    mock.patch.object(self.work_items.os, "waitid", return_value=object()), \
                    mock.patch.object(worker, "_stop_process_group", return_value=True):
                result = worker.run(operation, store_path)
                provider.record_result(operation, result)
            item = self.read_items(store_path)[0]

        self.assertEqual(result.status, "done")
        self.assertTrue(result.evidence["invocation_completed"])
        self.assertEqual(result.evidence["team_run_status"], "complete")
        self.assertEqual(item["process_uncertainty"]["status"], "resolved")
        self.assertEqual(item["status"], "done")

    def test_contracted_worker_refuses_forged_aggregate_after_job_directory_swap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "work-items.json"
            self.write_store(store_path, [{
                "id": "WI-SWAP", "status": "running", "state": "running",
                "scheduler": {"team_template": "two-role"},
                "metadata": {"local_execution_v1": {
                    "policy_id": "local-luna-unit-v1",
                    "role_purposes": {"implementation": "implementation"},
                    "changed_interfaces": [], "unresolved_questions": [], "complexity_flags": [],
                }},
            }])
            store = self.work_items.AtlasWorkItemStore(store_path)
            provider = self.work_items.AtlasWorkItemOperationProvider(store, claimed_by="test-worker")
            operation = provider.operation_states()[0]
            runner = ROOT / "atlas-agent-role-runner"
            worker = self.work_items.LocalCommandOperationWorker(
                [str(runner), "--command-config", str(root / "commands.json"), "--max-roles", "1"],
                jobs_dir=root / "jobs",
            )
            external = root / "external-team-run.json"
            external.write_text('{"sentinel":"unchanged"}', encoding="utf-8")

            def workflow_artifacts(_operation, job_dir, _job_id, _store_path):
                return {
                    "team_template": "two-role", "team_run_path": str(job_dir / "team-run.json"),
                    "team_rollup_path": str(job_dir / "team-rollup.md"),
                    "team_role_tasks_path": str(job_dir / "team-role-tasks.json"),
                    "team_run_status": "running", "work_item_context": {}, "contract_hash": "c1",
                }

            def swapped_launch(_command, *, cwd, env, **_kwargs):
                job_path = Path(cwd)
                job_path.rename(job_path.with_name(job_path.name + ".held"))
                job_path.mkdir()
                (job_path / "team-role-results.json").write_text(json.dumps([
                    {"role_id": "review", "status": "complete", "outputs": {"findings": "forged"}},
                ]), encoding="utf-8")
                (job_path / "team-run.json").symlink_to(external)
                return types.SimpleNamespace(pid=987654321, returncode=0)

            with mock.patch.object(worker, "write_workflow_artifacts", side_effect=workflow_artifacts), \
                    mock.patch.object(self.work_items.subprocess, "Popen", side_effect=swapped_launch), \
                    mock.patch.object(self.work_items.os, "waitid", return_value=object()), \
                    mock.patch.object(worker, "_stop_process_group", return_value=True), \
                    mock.patch.object(worker, "apply_workflow_role_results") as apply_mock:
                result = worker.run(operation, store_path)
                provider.record_result(operation, result)
            item = self.read_items(store_path)[0]
            external_bytes = external.read_bytes()

        self.assertEqual(result.status, "blocked")
        self.assertTrue(result.evidence["job_directory_identity_changed"])
        self.assertFalse(result.evidence["invocation_completed"])
        self.assertEqual(external_bytes, b'{"sentinel":"unchanged"}')
        apply_mock.assert_not_called()
        self.assertEqual(item["process_uncertainty"]["status"], "unresolved")
        self.assertEqual(item["status"], "blocked")

    def test_contracted_worker_keeps_durable_hold_when_group_cleanup_is_uncertain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "work-items.json"
            self.write_store(store_path, [{
                "id": "WI-UNCERTAIN-FD", "status": "running", "state": "running",
                "metadata": {"local_execution_v1": {
                    "policy_id": "local-luna-unit-v1",
                    "role_purposes": {"implementation": "implementation"},
                    "changed_interfaces": [], "unresolved_questions": [], "complexity_flags": [],
                }},
            }])
            provider = self.work_items.AtlasWorkItemOperationProvider(
                self.work_items.AtlasWorkItemStore(store_path), claimed_by="test-worker",
            )
            operation = provider.operation_states()[0]
            runner = ROOT / "atlas-agent-role-runner"
            worker = self.work_items.LocalCommandOperationWorker(
                [str(runner), "--command-config", str(root / "commands.json"), "--max-roles", "1"],
                jobs_dir=root / "jobs",
            )
            fake_proc = types.SimpleNamespace(pid=987654323, returncode=0)
            with mock.patch.object(worker, "write_workflow_artifacts", return_value={}), \
                    mock.patch.object(self.work_items.subprocess, "Popen", return_value=fake_proc), \
                    mock.patch.object(self.work_items.os, "waitid", return_value=object()), \
                    mock.patch.object(worker, "_stop_process_group", return_value=False):
                result = worker.run(operation, store_path)
                provider.record_result(operation, result)
            item = self.read_items(store_path)[0]

        self.assertEqual(result.status, "blocked")
        self.assertFalse(result.evidence["termination_proved"])
        self.assertFalse(result.evidence["invocation_completed"])
        self.assertEqual(item["process_uncertainty"]["status"], "unresolved")
        self.assertEqual(item["status"], "blocked")

    def test_contracted_uncertain_record_suppresses_rollup_path_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "work-items.json"
            self.write_store(store_path, [{
                "id": "WI-ROLLUP-UNCERTAIN", "status": "running", "state": "running",
                "metadata": {"local_execution_v1": {
                    "policy_id": "local-luna-unit-v1",
                    "role_purposes": {"implementation": "implementation"},
                    "changed_interfaces": [], "unresolved_questions": [], "complexity_flags": [],
                }},
            }])
            store = self.work_items.AtlasWorkItemStore(store_path)
            provider = self.work_items.AtlasWorkItemOperationProvider(store, claimed_by="test-worker")
            operation = provider.operation_states()[0]
            external = root / "external-rollup.md"
            external.write_text("private sentinel", encoding="utf-8")
            job_dir = root / "job"
            job_dir.mkdir()
            (job_dir / "team-rollup.md").symlink_to(external)
            store.update_item(operation.source_id, lambda item: item.update({
                "process_uncertainty": {"status": "unresolved", "invocation_id": "invocation-uncertain"},
            }) or item)
            result = self.work_items.OperationResult(
                status="blocked", returncode=124, summary="timeout; custody uncertain",
                evidence={
                    "process_invocation_id": "invocation-uncertain", "invocation_completed": False,
                    "termination_proved": False, "job_dir": str(job_dir),
                    "team_run": {"run_id": "run-uncertain", "status": "running"},
                    "team_rollup_path": str(job_dir / "team-rollup.md"),
                },
            )
            provider.record_result(operation, result)
            item = self.read_items(store_path)[0]
            sentinel = external.read_text(encoding="utf-8")

        self.assertEqual(item["process_uncertainty"]["status"], "unresolved")
        self.assertNotIn("team_rollup_markdown", item["workflow_runs"][0])
        self.assertEqual(sentinel, "private sentinel")

    def test_contracted_invalid_aggregate_record_does_not_read_rollup_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "work-items.json"
            self.write_store(store_path, [{
                "id": "WI-ROLLUP-INVALID", "status": "running", "state": "running",
                "metadata": {"local_execution_v1": {
                    "policy_id": "local-luna-unit-v1",
                    "role_purposes": {"implementation": "implementation"},
                    "changed_interfaces": [], "unresolved_questions": [], "complexity_flags": [],
                }},
            }])
            provider = self.work_items.AtlasWorkItemOperationProvider(
                self.work_items.AtlasWorkItemStore(store_path), claimed_by="test-worker",
            )
            operation = provider.operation_states()[0]
            external = root / "external-rollup.md"
            external.write_text("must not be imported", encoding="utf-8")
            job_dir = root / "job"
            job_dir.mkdir()
            (job_dir / "team-rollup.md").symlink_to(external)
            result = self.work_items.OperationResult(
                status="blocked", returncode=1, summary="invalid aggregate",
                evidence={
                    "workflow_result_error": "invalid contracted aggregate",
                    "team_run": {"run_id": "run-invalid", "status": "blocked"},
                    "team_rollup_path": str(job_dir / "team-rollup.md"),
                },
            )
            provider.record_result(operation, result)
            item = self.read_items(store_path)[0]
            sentinel = external.read_text(encoding="utf-8")

        self.assertNotIn("team_rollup_markdown", item["workflow_runs"][0])
        self.assertEqual(sentinel, "must not be imported")

    def test_contracted_worker_bounds_held_output_before_decode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "work-items.json"
            self.write_store(store_path, [{
                "id": "WI-OUTPUT-BOUND", "status": "running", "state": "running",
                "metadata": {"local_execution_v1": {
                    "policy_id": "local-luna-unit-v1",
                    "role_purposes": {"implementation": "implementation"},
                    "changed_interfaces": [], "unresolved_questions": [], "complexity_flags": [],
                }},
            }])
            provider = self.work_items.AtlasWorkItemOperationProvider(
                self.work_items.AtlasWorkItemStore(store_path), claimed_by="test-worker",
            )
            operation = provider.operation_states()[0]
            worker = self.work_items.LocalCommandOperationWorker(
                [str(ROOT / "atlas-agent-role-runner"), "--command-config", str(root / "commands.json"), "--max-roles", "1"],
                jobs_dir=root / "jobs",
            )
            fake_proc = types.SimpleNamespace(pid=987654324, returncode=0)
            def noisy_launch(_command, *, stdout, **_kwargs):
                stdout.write(b"x" * 9)
                stdout.flush()
                return fake_proc
            with mock.patch.object(self.work_items, "_CONTRACTED_WORKER_OUTPUT_LIMIT_BYTES", 8), \
                    mock.patch.object(worker, "write_workflow_artifacts", return_value={}), \
                    mock.patch.object(self.work_items.subprocess, "Popen", side_effect=noisy_launch), \
                    mock.patch.object(self.work_items.os, "waitid", return_value=object()), \
                    mock.patch.object(worker, "_stop_process_group", return_value=True):
                result = worker.run(operation, store_path)
                provider.record_result(operation, result)
            item = self.read_items(store_path)[0]

        self.assertEqual(result.status, "failed")
        self.assertTrue(result.evidence["output_limit_exceeded"])
        self.assertTrue(result.evidence["invocation_completed"])
        self.assertEqual(item["process_uncertainty"]["status"], "resolved")

    def test_timeout_kills_nested_process_group_and_keeps_partial_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "work-items.json"
            self.write_store(store_path, [{"id": "WI-TREE", "status": "running", "state": "running"}])
            operation = self.work_items.AtlasWorkItemOperationProvider(self.work_items.AtlasWorkItemStore(store_path)).operation_states()[0]
            grandchild_file = root / "grandchild.json"
            grandchild = "import json,os,pathlib,signal,sys,time;p=pathlib.Path(sys.argv[1]);signal.signal(signal.SIGTERM,signal.SIG_IGN);s=open(f'/proc/{os.getpid()}/stat').read();p.write_text(json.dumps({'pid':os.getpid(),'start':s[s.rfind(')')+2:].split()[19]}));time.sleep(30)"
            child = ("import subprocess,sys,time;sys.stdout.buffer.write(b'x'*200000);sys.stdout.buffer.flush();print('partial-output',flush=True); "
                f"subprocess.Popen([sys.executable,'-c',{grandchild!r},{str(grandchild_file)!r}]); "
                f"deadline=time.monotonic()+3; "
                f"exec(\"while time.monotonic()<deadline and not __import__('pathlib').Path({str(grandchild_file)!r}).exists(): time.sleep(.01)\"); time.sleep(30)")
            worker = self.work_items.LocalCommandOperationWorker([sys.executable, "-c", child], jobs_dir=root / "jobs", timeout_seconds=0.6, termination_grace_seconds=0.1)
            start = __import__("time").monotonic()
            real_popen = self.work_items.subprocess.Popen
            held = []
            def launch_tree(*args, **kwargs):
                proc = real_popen(*args, **kwargs)
                held.append(proc)
                return proc
            try:
                with mock.patch.object(self.work_items.subprocess, "Popen", side_effect=launch_tree):
                    result = worker.run(operation, store_path)
                elapsed = __import__("time").monotonic() - start
                output = Path(result.evidence["output_path"]).read_bytes()
                persisted = self.read_items(store_path)[0]
                spawned = json.loads(grandchild_file.read_text(encoding="utf-8"))
                def process_state(pid: int):
                    try:
                        raw = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
                        fields = raw[raw.rfind(")") + 2:].split()
                        return fields[0], fields[19]
                    except (OSError, IndexError):
                        return None
                deadline = __import__("time").monotonic() + 1
                while __import__("time").monotonic() < deadline and process_state(spawned["pid"]) not in (None, ("Z", spawned["start"])):
                    __import__("time").sleep(0.01)
                self.assertIn(process_state(spawned["pid"]), (None, ("Z", spawned["start"])))
                self.assertEqual(process_state(result.evidence["process_pid"]), None)
                self.assertTrue(result.evidence["process_shutdown"]["term_sent"])
                self.assertTrue(result.evidence["process_shutdown"]["kill_sent"])
                self.assertTrue(result.evidence["process_shutdown"]["leader_reaped"])
            finally:
                if held and held[0].returncode is None:
                    try:
                        __import__("os").killpg(held[0].pid, __import__("signal").SIGKILL)
                    except ProcessLookupError:
                        pass
                    try:
                        held[0].wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        pass
                if grandchild_file.exists():
                    try:
                        spawned = json.loads(grandchild_file.read_text(encoding="utf-8"))
                        state = process_state(spawned["pid"])
                        if state and state[1] == spawned["start"] and state[0] != "Z":
                            __import__("os").kill(spawned["pid"], __import__("signal").SIGKILL)
                    except (OSError, ValueError, NameError, KeyError):
                        pass
        self.assertLess(elapsed, 2.5)
        self.assertIn(b"partial-output", output)
        self.assertGreaterEqual(len(output), 200000)
        self.assertTrue(result.evidence["timed_out"])
        self.assertEqual(result.status, "blocked")
        self.assertEqual(persisted["process_uncertainty"]["status"], "unresolved")

    def test_cancel_during_execution_stops_held_process_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "work-items.json"
            self.write_store(store_path, [{"id": "WI-CANCEL-LIVE", "status": "running", "state": "running"}])
            operation = self.work_items.AtlasWorkItemOperationProvider(self.work_items.AtlasWorkItemStore(store_path)).operation_states()[0]
            cancel = __import__("threading").Event()
            worker = self.work_items.LocalCommandOperationWorker([sys.executable, "-c", "import time;print('cancel-output',flush=True);time.sleep(30)"],
                jobs_dir=root / "jobs", timeout_seconds=5, termination_grace_seconds=0.1)
            timer = __import__("threading").Timer(0.2, cancel.set)
            timer.start()
            try:
                result = worker.run(operation, store_path, cancel_event=cancel)
                output = Path(result.evidence["output_path"]).read_bytes()
            finally:
                timer.cancel()
        self.assertTrue(result.evidence["cancelled"])
        self.assertEqual(result.status, "blocked")
        self.assertTrue(result.evidence["process_shutdown"]["leader_reaped"])
        self.assertIn(b"cancel-output", output)

    def test_normal_large_output_completes_without_pipe_deadlock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "work-items.json"
            self.write_store(store_path, [{"id": "WI-LARGE", "status": "running", "state": "running"}])
            store = self.work_items.AtlasWorkItemStore(store_path)
            provider = self.work_items.AtlasWorkItemOperationProvider(store)
            operation = provider.operation_states()[0]
            worker = self.work_items.LocalCommandOperationWorker([sys.executable, "-c", "import sys;sys.stdout.buffer.write(b'z'*300000)"],
                jobs_dir=root / "jobs", timeout_seconds=2)
            result = worker.run(operation, store_path)
            provider.record_result(operation, result)
            item = self.read_items(store_path)[0]
            self.assertTrue(Path(result.evidence["output_path"]).exists())
            output = Path(result.evidence["output_path"]).read_bytes()
        self.assertEqual(len(output), 300000)
        self.assertTrue(result.evidence["invocation_completed"])
        self.assertTrue(result.evidence["termination_proved"])
        self.assertEqual(item["process_uncertainty"]["status"], "resolved")

    def test_postlaunch_store_lock_does_not_extend_child_deadline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "work-items.json"
            self.write_store(store_path, [{"id": "WI-LOCK", "status": "running", "state": "running"}])
            operation = self.work_items.AtlasWorkItemOperationProvider(self.work_items.AtlasWorkItemStore(store_path)).operation_states()[0]
            worker = self.work_items.LocalCommandOperationWorker([sys.executable, "-c", "import time;time.sleep(30)"],
                jobs_dir=root / "jobs", timeout_seconds=0.05, termination_grace_seconds=0)
            lock = store_path.with_suffix(store_path.suffix + ".lock")
            real_popen = self.work_items.subprocess.Popen
            def launch_then_lock(*args, **kwargs):
                proc = real_popen(*args, **kwargs)
                lock.write_text(json.dumps({"pid": __import__("os").getpid(), "created_at": "now"}), encoding="utf-8")
                return proc
            start = __import__("time").monotonic()
            try:
                with mock.patch.object(self.work_items.subprocess, "Popen", side_effect=launch_then_lock):
                    result = worker.run(operation, store_path)
            finally:
                lock.unlink(missing_ok=True)
            elapsed = __import__("time").monotonic() - start
        self.assertLess(elapsed, 1.0)
        self.assertTrue(result.evidence["timed_out"])
        self.assertTrue(result.evidence["process_shutdown"]["leader_reaped"])

    def test_lost_waitid_custody_never_signals_numeric_process_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "work-items.json"
            self.write_store(store_path, [{"id": "WI-CUSTODY", "status": "running", "state": "running"}])
            operation = self.work_items.AtlasWorkItemOperationProvider(self.work_items.AtlasWorkItemStore(store_path)).operation_states()[0]
            worker = self.work_items.LocalCommandOperationWorker([sys.executable, "-c", "pass"], jobs_dir=root / "jobs")
            real_popen = self.work_items.subprocess.Popen
            held = []
            def launch(*args, **kwargs):
                proc = real_popen(*args, **kwargs)
                held.append(proc)
                return proc
            try:
                with mock.patch.object(self.work_items.subprocess, "Popen", side_effect=launch), \
                        mock.patch.object(self.work_items.os, "waitid", side_effect=ChildProcessError), \
                        mock.patch.object(self.work_items.os, "killpg") as killpg:
                    result = worker.run(operation, store_path)
                    self.assertFalse(any(call.args[1] in (__import__("signal").SIGTERM, __import__("signal").SIGKILL)
                        for call in killpg.call_args_list))
            finally:
                if held:
                    held[0].wait(timeout=2)
        self.assertEqual(result.status, "blocked")
        self.assertFalse(result.evidence["termination_proved"])
        self.assertEqual(result.evidence["process_shutdown"]["group_status"], "custody_lost")

    def test_post_reap_exception_does_not_signal_reused_process_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "work-items.json"
            self.write_store(store_path, [{"id": "WI-POST-REAP", "status": "running", "state": "running"}])
            operation = self.work_items.AtlasWorkItemOperationProvider(self.work_items.AtlasWorkItemStore(store_path)).operation_states()[0]
            worker = self.work_items.LocalCommandOperationWorker([sys.executable, "-c", "print('done',flush=True)"],
                jobs_dir=root / "jobs", timeout_seconds=2)
            real_stop = worker._stop_process_group
            real_killpg = self.work_items.os.killpg
            signals = []
            def stop_then_raise(proc, **kwargs):
                real_stop(proc, **kwargs)
                raise RuntimeError("synthetic after reap")
            def track_killpg(pgid, sig):
                if sig in (__import__("signal").SIGTERM, __import__("signal").SIGKILL):
                    signals.append((pgid, sig))
                return real_killpg(pgid, sig)
            with mock.patch.object(worker, "_stop_process_group", side_effect=stop_then_raise), \
                    mock.patch.object(self.work_items.os, "killpg", side_effect=track_killpg):
                result = worker.run(operation, store_path)
        self.assertEqual(result.status, "blocked")
        self.assertEqual(signals, [])
        self.assertTrue(result.evidence["process_shutdown"]["leader_reaped"])
        self.assertFalse(result.evidence["process_shutdown"]["kill_sent"])

    def test_keyboard_interrupt_immediately_after_popen_cleans_held_child(self) -> None:
        """An interrupt after Popen returns must retain the invocation and reap its child."""
        import os
        import time

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "work-items.json"
            self.write_store(store_path, [{"id": "WI-POST-Popen-INTERRUPT", "status": "running", "state": "running"}])
            operation = self.work_items.AtlasWorkItemOperationProvider(
                self.work_items.AtlasWorkItemStore(store_path)
            ).operation_states()[0]
            worker = self.work_items.LocalCommandOperationWorker(
                [sys.executable, "-c", "import sys,time;print('launch-boundary-output',flush=True);time.sleep(30)"],
                jobs_dir=root / "jobs", timeout_seconds=5, termination_grace_seconds=0.1,
            )
            real_popen = self.work_items.subprocess.Popen
            held = []

            def launch_after_output_is_flushed(*args, **kwargs):
                proc = real_popen(*args, **kwargs)
                held.append(proc)
                output_path = Path(kwargs["stdout"].name)
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    if output_path.exists() and b"launch-boundary-output" in output_path.read_bytes():
                        return proc
                    if proc.poll() is not None:
                        self.fail("synthetic child exited before writing its synchronization output")
                    time.sleep(0.01)
                self.fail("synthetic child did not flush synchronization output before launch returned")

            injected = []
            target_code = self.work_items.LocalCommandOperationWorker.run.__code__

            def interrupt_after_handle_is_assigned(frame, event, arg):
                if (event == "line" and frame.f_code is target_code
                        and held and frame.f_locals.get("proc") is held[0]
                        and "invocation" in frame.f_locals
                        and "pid" not in frame.f_locals["invocation"] and not injected):
                    injected.append(True)
                    raise KeyboardInterrupt("synthetic immediate post-Popen interrupt")
                return interrupt_after_handle_is_assigned

            result = None
            escaped = None
            worker_reaped_child = False
            started_at = time.monotonic()
            previous_trace = sys.gettrace()
            try:
                with mock.patch.object(self.work_items.subprocess, "Popen", side_effect=launch_after_output_is_flushed):
                    sys.settrace(interrupt_after_handle_is_assigned)
                    try:
                        result = worker.run(operation, store_path)
                    except KeyboardInterrupt as exc:
                        escaped = exc
                    finally:
                        sys.settrace(previous_trace)
                worker_reaped_child = bool(held and held[0].returncode is not None)
            finally:
                sys.settrace(previous_trace)
                # Own and clean the real process even when the regression exposes the bug.
                for proc in held:
                    if proc.poll() is None:
                        try:
                            os.killpg(proc.pid, __import__("signal").SIGKILL)
                        except ProcessLookupError:
                            pass
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        self.fail("fixture could not reap its synthetic child")

            self.assertTrue(injected, "the interruption seam must run after successful Popen")
            self.assertIsNone(escaped, f"post-launch interruption escaped worker: {escaped!r}")
            self.assertLess(time.monotonic() - started_at, 2.0, "post-launch cleanup must return within a bound")
            self.assertIsNotNone(result, "worker must return a bounded blocked result")
            self.assertEqual(result.status, "blocked")
            self.assertEqual(result.evidence["process_invocation_id"],
                             self.read_items(store_path)[0]["process_uncertainty"]["invocation_id"])
            persisted = self.read_items(store_path)[0]
            self.assertEqual(persisted["process_uncertainty"]["status"], "unresolved")
            self.assertIn(b"launch-boundary-output", Path(result.evidence["output_path"]).read_bytes())
            self.assertIn("process_shutdown", result.evidence)
            self.assertTrue(result.evidence["process_shutdown"]["leader_reaped"])
            self.assertTrue(worker_reaped_child, "worker must terminate and reap its held child")
            self.assertTrue(held and held[0].returncode is not None, "direct child must be reaped")
            with self.assertRaises(ProcessLookupError):
                os.kill(held[0].pid, 0)

    def test_postlaunch_keyboard_interrupt_is_bounded_and_keeps_uncertainty(self) -> None:
        class InterruptOnPoll:
            def __init__(self):
                self.calls = 0
            def is_set(self):
                self.calls += 1
                if self.calls <= 2:
                    return False
                __import__("time").sleep(0.15)
                raise KeyboardInterrupt("synthetic interrupt")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "work-items.json"
            self.write_store(store_path, [{"id": "WI-INTERRUPT", "status": "running", "state": "running"}])
            operation = self.work_items.AtlasWorkItemOperationProvider(self.work_items.AtlasWorkItemStore(store_path)).operation_states()[0]
            worker = self.work_items.LocalCommandOperationWorker([sys.executable, "-c", "import time;print('interrupt-output',flush=True);time.sleep(30)"],
                jobs_dir=root / "jobs", timeout_seconds=5, termination_grace_seconds=0.1)
            result = worker.run(operation, store_path, cancel_event=InterruptOnPoll())
            persisted = self.read_items(store_path)[0]
            output = Path(result.evidence["output_path"]).read_bytes()
        self.assertEqual(result.status, "blocked")
        self.assertIn("KeyboardInterrupt", result.evidence["supervisor_error"])
        self.assertIn(b"interrupt-output", output)
        self.assertTrue(result.evidence["process_shutdown"]["leader_reaped"])
        self.assertEqual(persisted["process_uncertainty"]["status"], "unresolved")

    def test_batch_stops_after_ambiguous_first_launch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "work-items.json"
            self.write_store(store_path, [{"id": "WI-A", "status": "ready"}, {"id": "WI-B", "status": "ready"}])
            store = self.work_items.AtlasWorkItemStore(store_path)
            provider = self.work_items.AtlasWorkItemOperationProvider(store)
            worker = self.work_items.LocalCommandOperationWorker([sys.executable, "-c", "pass"], jobs_dir=root / "jobs")
            with mock.patch.object(self.work_items.subprocess, "Popen", side_effect=RuntimeError("ambiguous")):
                processed = self.work_items.run_worker_daemon_once(provider, worker, limit=2)
            items = {item["id"]: item for item in self.read_items(store_path)}
        self.assertEqual(processed, 1)
        self.assertEqual(items["WI-A"]["status"], "blocked")
        self.assertEqual(items["WI-A"]["process_uncertainty"]["status"], "unresolved")
        self.assertEqual(items["WI-B"]["status"], "ready")

    def test_ambiguous_popen_exception_leaves_durable_invocation_uncertainty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "work-items.json"
            self.write_store(store_path, [{"id": "WI-LAUNCH", "status": "running", "state": "running"}])
            store = self.work_items.AtlasWorkItemStore(store_path)
            provider = self.work_items.AtlasWorkItemOperationProvider(store)
            operation = provider.operation_states()[0]
            worker = self.work_items.LocalCommandOperationWorker([sys.executable, "-c", "pass"], jobs_dir=root / "jobs")
            with mock.patch.object(self.work_items.subprocess, "Popen", side_effect=RuntimeError("ambiguous launch")):
                result = worker.run(operation, store_path)
            provider.record_result(operation, result)
            item = self.read_items(store_path)[0]
        self.assertEqual(result.status, "blocked")
        self.assertEqual(item["status"], "blocked")
        self.assertEqual(item["result"]["status"], "blocked")
        self.assertEqual(item["process_uncertainty"]["status"], "unresolved")
        self.assertEqual(item["process_uncertainty"]["invocation_id"], result.evidence["process_invocation_id"])

    def test_unresolved_launch_blocks_restart_requeue_result_normalization_and_rework(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "work-items.json"
            old = "2026-01-01T00:00:00Z"
            self.write_store(store_path, [{"id": "WI-UNKNOWN", "status": "running", "state": "running",
                "lifecycle": {"state": "running", "claimed_at": old}, "claim": {"claimed_at": old},
                "process_uncertainty": {"status": "unresolved", "invocation_id": "inv-1", "pid": 1234}},
                {"id": "WI-OVERLAP", "status": "ready"}])
            store = self.work_items.AtlasWorkItemStore(store_path)
            provider = self.work_items.AtlasWorkItemOperationProvider(store)
            operation = provider.operation_states()[0]
            self.assertFalse(operation.ready)
            self.assertTrue(any("unresolved worker process uncertainty" in b for b in operation.blockers))
            fresh_inspect = subprocess.run([sys.executable, str(ROOT / "atlas-agent-work-item-inspect"), str(store_path), "--json"],
                capture_output=True, text=True, check=True)
            fresh_item = json.loads(fresh_inspect.stdout)["items"][0]
            self.assertEqual(fresh_item["status"], "active")
            self.assertTrue(any("unresolved worker process uncertainty" in b for b in fresh_item["blockers"]))
            overlap = next(state for state in provider.operation_states() if state.source_id == "WI-OVERLAP")
            self.assertFalse(overlap.ready)
            self.assertTrue(any("active scope conflict: WI-UNKNOWN" == b for b in overlap.blockers))
            # Public stale recovery must refuse the still-running record before result normalization.
            preview = provider.requeue_stale_claims(stale_seconds=1, now=datetime(2026, 1, 2, tzinfo=timezone.utc), apply=False)
            applied = provider.requeue_stale_claims(stale_seconds=1, now=datetime(2026, 1, 2, tzinfo=timezone.utc), apply=True)
            stale_cli = subprocess.run([sys.executable, str(ROOT / "atlas-agent-work-item-requeue-stale"), str(store_path),
                "--stale-seconds", "1", "--apply", "--json"], capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(stale_cli.stdout)["records"], [])
            still_running = self.read_items(store_path)[0]
            self.assertEqual(preview, [])
            self.assertEqual(applied, [])
            self.assertEqual(still_running["status"], "running")
            result = self.work_items.OperationResult(status="ready", returncode=0, summary="bad normalization")
            provider.record_result(operation, result)
            item = self.read_items(store_path)[0]
            # These variants must not resolve uncertainty, including mismatched identity or absent shutdown proof.
            for evidence in [
                {"process_invocation_id": "inv-1", "invocation_completed": True},
                {"process_invocation_id": "other", "invocation_completed": True, "termination_proved": True},
                {"process_invocation_id": "inv-1", "invocation_completed": True, "termination_proved": False},
            ]:
                path_variant = root / "variant.json"
                self.write_store(path_variant, [{"id": "WI-V", "status": "blocked", "process_uncertainty":
                    {"status": "unresolved", "invocation_id": "inv-1"}}])
                variant_provider = self.work_items.AtlasWorkItemOperationProvider(self.work_items.AtlasWorkItemStore(path_variant))
                variant_op = variant_provider.operation_states()[0]
                variant_provider.record_result(variant_op, self.work_items.OperationResult(status="ready", returncode=0,
                    summary="forged", evidence=evidence))
                variant = self.read_items(path_variant)[0]
                self.assertEqual(variant["status"], "blocked")
                self.assertEqual(variant["process_uncertainty"]["status"], "unresolved")
            with self.assertRaisesRegex(ValueError, "unresolved process uncertainty"):
                provider.requeue_for_rework("WI-UNKNOWN", reason="retry", evidence=["reviewed"])
            final = self.read_items(store_path)[0]
        self.assertEqual(item["status"], "blocked")
        self.assertEqual(item["result"]["status"], "blocked")
        self.assertEqual(final["status"], "blocked")
        self.assertEqual(final["process_uncertainty"]["status"], "unresolved")
        self.assertEqual(preview, [])
        self.assertEqual(applied, [])

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
        self.assertEqual(item["status"], "failed")
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
                        "workflow_kind": "artifact-review",
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
                        "workflow_kind": "artifact-review",
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
                        "workflow_kind": "artifact-review",
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
        self.assertEqual(item["status"], "blocked")
        self.assertEqual(item["result"]["returncode"], 0)
        self.assertEqual(evidence["team_run_status"], "blocked")
        self.assertNotIn("workflow_continuation", evidence)
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
                        "workflow_kind": "artifact-review",
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
