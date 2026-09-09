from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import sync_runtime_template
import verify_repo


class AzureRuntimeCopyBoundaries(unittest.TestCase):
    def test_runtime_upgrade_excludes_authority_and_execution_state(self):
        prefix = "templates/local-automation-runtime/"
        private = ["authority/trust.json", ".azure-api/throttle.json",
                   ".azure-dispatch/decisions.json", "azure-reconcile/journal.json",
                   ".azure-supervisor/loop.json", "approval-inbox/requests.json",
                   "worktrees/task/source.py", "state/azure-worker/claims.json"]
        managed = ["atlas_authority.py", "config/routing.example.json",
                   "tests/fixtures/authority-public.json"]
        inventory = "\n".join(prefix + name for name in private + managed)
        with patch.object(sync_runtime_template, "run_capture", return_value=inventory):
            actual = [str(path) for path in sync_runtime_template.source_template_files()]
        self.assertEqual(actual, sorted(managed))

    def test_verifier_treats_authority_and_execution_state_as_local_artifacts(self):
        for name in ("authority", ".azure-api", ".azure-dispatch", ".azure-supervisor",
                     "approval-inbox", "azure-reconcile", "worktrees"):
            with self.subTest(directory=name):
                path = ROOT / "templates/local-automation-runtime" / name
                self.assertTrue(verify_repo.is_pruned_dir(path))


if __name__ == "__main__":
    unittest.main()
