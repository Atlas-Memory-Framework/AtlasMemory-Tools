from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/plain-technical-english/scripts/check_review.py"
spec = importlib.util.spec_from_file_location("plain_english_check_review", SCRIPT)
assert spec and spec.loader
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)
FIXTURES = {
    item["id"]: item
    for item in json.loads((ROOT / "tests/fixtures/plain-technical-english.json").read_text())
}


def filled_record(data: bytes) -> dict:
    """Syntactically complete test record; this helper does not judge meaning."""
    record = checker.prepare(data)
    record["reviewer"] = "fixture-reviewer"
    record["reader_summary"] = "A fixture exercises review record validation."
    quote = data.decode().splitlines()[0]
    for item in record["criteria"].values():
        item.update(result="pass", reason="Fixture supplies a reviewer judgment.", evidence=[{"line": 1, "text": quote}])
    return record


class ReviewRecordTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = FIXTURES["clear-technical-reasoning"]["text"].encode()
        self.record = filled_record(self.data)

    def test_prepared_record_cannot_pass_until_reviewed(self) -> None:
        errors, failures = checker.validate(self.data, checker.prepare(self.data))
        self.assertTrue(errors)
        self.assertFalse(failures)

    def test_checks_technical_prose_without_length_or_jargon_rules(self) -> None:
        self.assertEqual(checker.validate(self.data, self.record), ([], []))

    def test_checker_does_not_claim_semantic_classification(self) -> None:
        # Even an unclear short report can carry a formally valid judgment.
        # Reader review, exercised independently, must catch that bad judgment.
        data = FIXTURES["unclear-short-report"]["text"].encode()
        self.assertEqual(checker.validate(data, filled_record(data)), ([], []))

    def test_source_change_invalidates_review_even_if_anchor_survives(self) -> None:
        errors, _ = checker.validate(self.data + b"Deployment remains untested.\n", self.record)
        self.assertTrue(any("stale" in error for error in errors))

    def test_protected_span_change_also_invalidates_review(self) -> None:
        data = FIXTURES["protected-content"]["text"].encode()
        changed = data.replace(b"source_sha256", b"source_hash")
        errors, _ = checker.validate(changed, filled_record(data))
        self.assertTrue(any("stale" in error for error in errors))

    def test_reviewed_failure_is_distinct_from_malformed_record(self) -> None:
        self.record["criteria"]["reasoning-uncertainty"].update(
            result="fail", reason="The report claims deployment from a fixture test."
        )
        errors, failures = checker.validate(self.data, self.record)
        self.assertFalse(errors)
        self.assertEqual(len(failures), 1)
        self.assertIn("reasoning-uncertainty", failures[0])

    def test_omitted_and_unknown_criteria_are_rejected(self) -> None:
        for key in ("missing", "unknown"):
            with self.subTest(key=key):
                record = deepcopy(self.record)
                if key == "missing":
                    record["criteria"].pop("faithfulness")
                else:
                    record["criteria"]["word-count"] = {}
                errors, _ = checker.validate(self.data, record)
                self.assertTrue(errors)

    def test_not_applicable_requires_a_conditional_criterion_and_reason(self) -> None:
        self.record["criteria"]["terms-referents"]["result"] = "not-applicable"
        self.assertEqual(checker.validate(self.data, self.record), ([], []))
        self.record["criteria"]["terms-referents"]["reason"] = ""
        self.assertTrue(checker.validate(self.data, self.record)[0])
        self.record["criteria"]["faithfulness"]["result"] = "not-applicable"
        self.assertTrue(any("faithfulness" in error for error in checker.validate(self.data, self.record)[0]))

    def test_bad_anchors_are_rejected(self) -> None:
        for entry in (
            {"line": 1, "text": "invented quotation"},
            {"line": 0, "text": "The importer"},
            {"line": True, "text": "The importer"},
            {"line": 1000, "text": "The importer"},
            {"line": 1, "text": "The importer\nprevents"},
        ):
            with self.subTest(entry=entry):
                record = deepcopy(self.record)
                record["criteria"]["answer-first"]["evidence"] = [entry]
                self.assertTrue(checker.validate(self.data, record)[0])

    def test_malformed_assessments_do_not_crash(self) -> None:
        for assessment in (None, [], {"result": []}, {"result": {}}):
            with self.subTest(assessment=assessment):
                record = deepcopy(self.record)
                record["criteria"]["answer-first"] = assessment
                self.assertTrue(checker.validate(self.data, record)[0])

    def test_duplicate_json_keys_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            json.loads('{"schema": "one", "schema": "two"}', object_pairs_hook=checker.unique_object)

    def test_retained_independent_review_records_match_fixture_bytes(self) -> None:
        evidence = json.loads((ROOT / "evals/plain-technical-english/20261016-review.json").read_text())
        self.assertEqual(
            {item["id"]: item["result"] for item in evidence["outcomes"]},
            {key: item["expected_reader_result"] for key, item in FIXTURES.items()},
        )
        for run in evidence["checker_runs"]:
            with self.subTest(draft=run["draft_id"]):
                data = FIXTURES[run["draft_id"]]["text"].encode()
                errors, failures = checker.validate(data, run["review"])
                self.assertFalse(errors)
                self.assertEqual(1 if failures else 0, run["observed_exit_code"])

    def test_cli_exit_codes_and_no_source_or_review_rewrites(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = Path(tmp) / "report.md"
            review = Path(tmp) / "review.json"
            document.write_bytes(FIXTURES["protected-content"]["text"].encode())
            original = document.read_bytes()
            prepared = subprocess.run([sys.executable, str(SCRIPT), "prepare", str(document)], capture_output=True, check=True)
            review.write_bytes(prepared.stdout)

            def run_check(expected: int) -> None:
                saved_review = review.read_bytes()
                result = subprocess.run([sys.executable, str(SCRIPT), "check", str(document), str(review)], capture_output=True)
                self.assertEqual(result.returncode, expected, result.stderr.decode())
                self.assertEqual(document.read_bytes(), original)
                self.assertEqual(review.read_bytes(), saved_review)

            run_check(2)
            record = filled_record(original)
            review.write_text(json.dumps(record))
            run_check(0)
            record["criteria"]["answer-first"]["result"] = "fail"
            review.write_text(json.dumps(record))
            run_check(1)
            review.write_text('{"schema":')
            run_check(2)
            review.unlink()
            result = subprocess.run([sys.executable, str(SCRIPT), "check", str(document), str(review)], capture_output=True)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(document.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
