from __future__ import annotations

import contextlib
from copy import deepcopy
import email.utils
import http.client
import importlib.machinery
import importlib.util
import io
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock
import urllib.error
import urllib.parse


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import atlas_azure_devops as az


class Clock:
    def __init__(self, now=1700000000.0):
        self.now, self.sleeps = now, []

    def __call__(self):
        return self.now

    def sleep(self, value):
        self.sleeps.append(value)
        self.now += value


class Response:
    def __init__(self, data=None, *, status=200, headers=None, raw=None):
        self.status, self.headers = status, headers or {}
        self.raw = raw if raw is not None else json.dumps({} if data is None else data).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, maximum):
        return self.raw


class Opener:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def open(self, request, *, timeout):
        self.calls.append(request)
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value(request) if callable(value) else value


def raw_item(number, state="To Do", deps=(), successors=(), revision=1):
    return {"id": number, "rev": revision,
            "fields": {"System.State": state, "System.Title": f"Item {number}", "System.TeamProject": "Instablinds"},
            "relations": [{"rel": rel, "url": f"https://dev.azure.com/Instablinds/_apis/wit/workItems/{target}"}
                          for rel, values in ((az.PREDECESSOR, deps), (az.SUCCESSOR, successors)) for target in values]}


PROJECT_GUID = "6fb87f10-7d68-41ad-88ae-7ec8cfce0699"
OTHER_PROJECT_GUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def with_project_guid(item, alias=PROJECT_GUID):
    result = deepcopy(item)
    prefix = f"https://dev.azure.com/Instablinds/{alias}/_apis/wit/workItems/"
    result["url"] = prefix + str(item["id"])
    for relation in result["relations"]:
        relation["url"] = prefix + relation["url"].rsplit("/", 1)[-1]
    return result


def ident(number):
    return f"azdo:Instablinds:Instablinds:{number}"


def graph(dependencies):
    return {"schema_version": 1, "organization": "Instablinds", "project": "Instablinds",
            "dependencies": {ident(key): [ident(value) for value in values] for key, values in dependencies.items()}}


def authority(manifest, **extra):
    return {"dependency_contract_sha256": az.canonical_digest(manifest),
            "approval_record": "test-only-reviewed-contract", "execution_authorized": True, **extra}


def lock_process(root, entered, release):
    throttle = az.SharedThrottle(Path(root), interval=0)
    with mock.patch.object(az.SharedThrottle, "_validate_root", lambda self: self.runtime_dir):
        with throttle.slot():
            entered.set()
            release.wait(10)


def deadline_process(root, first, output):
    clock = Clock()
    opener = Opener([Response({"ok": True}, headers={"Retry-After": "4"} if first else {})])
    client = az.AzureDevOpsClient("Instablinds", "Instablinds", Path(root), opener=opener, clock=clock, sleep=clock.sleep, interval=0)
    with mock.patch.object(az.SharedThrottle, "_validate_root", lambda self: self.runtime_dir):
        result = client.request("GET", "_apis/git/repositories/Website")
    output.put({"calls": len(opener.calls), "slept": sum(clock.sleeps), "result": result})


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.clock = Clock()
        self.validation = mock.patch.object(az.SharedThrottle, "_validate_root", lambda self: self.runtime_dir)
        self.validation.start()
        self.addCleanup(self.validation.stop)

    def client(self, responses, **kwargs):
        opener = Opener(responses)
        client = az.AzureDevOpsClient("Instablinds", "Instablinds", self.root,
                                     opener=opener, clock=self.clock, sleep=self.clock.sleep,
                                     interval=0, **kwargs)
        return client, opener

    def test_constructing_client_and_cache_does_not_create_files(self):
        client, _ = self.client([])
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertEqual(client.organization, "Instablinds")

    def test_success_retry_after_is_not_replayed_and_delays_next_client(self):
        first, first_io = self.client([Response({"ok": 1}, headers={"Retry-After": "4"})])
        self.assertEqual(first.request("GET", "_apis/git/repositories/Website"), {"ok": 1})
        self.assertEqual(len(first_io.calls), 1)
        self.assertEqual(self.clock.sleeps, [])
        second, second_io = self.client([Response({"ok": 2})])
        self.assertEqual(second.request("GET", "_apis/git/repositories/Website"), {"ok": 2})
        self.assertEqual(len(second_io.calls), 1)
        self.assertEqual(sum(self.clock.sleeps), 4)
        state = json.loads((self.root / ".azure-api" / "throttle.lock").read_text())
        self.assertEqual(set(state), {"version", "not_before"})

    def test_retry_after_http_date_is_shared_and_not_capped(self):
        date = email.utils.formatdate(self.clock() + 600, usegmt=True)
        client, opener = self.client([Response(headers={"Retry-After": date}), Response()], max_wait=10)
        client.request("GET", "_apis/git/repositories/Website")
        with self.assertRaisesRegex(az.AzureError, "wait budget"):
            client.request("GET", "_apis/git/repositories/Website", fresh=True)
        self.assertEqual(len(opener.calls), 1)
        self.assertEqual(az.retry_after_seconds(date, self.clock()), 600)

    def test_read_retry_after_and_backoff_are_bounded(self):
        failed = urllib.error.HTTPError("https://secret.invalid", 429, "sensitive remote body", {"Retry-After": "3"}, None)
        client, opener = self.client([failed, urllib.error.URLError("sensitive network detail"), Response({"ok": True})])
        self.assertEqual(client.request("GET", "_apis/git/repositories/Website"), {"ok": True})
        self.assertEqual(len(opener.calls), 3)
        self.assertEqual(sum(self.clock.sleeps), 5)
        exhausted, io_ = self.client([http.client.BadStatusLine("SECRET")] * 2, max_attempts=2)
        with self.assertRaisesRegex(az.AzureReadIncomplete, "budget exhausted") as result:
            exhausted.request("GET", "_apis/build/builds")
        self.assertNotIn("SECRET", str(result.exception))
        self.assertEqual(len(io_.calls), 2)

    def test_successful_cache_read_keeps_original_age_and_fresh_bypasses(self):
        client, opener = self.client([Response({"rev": 1}), Response({"rev": 2})])
        first = client.request_response("GET", "_apis/git/repositories/Website")
        self.clock.now += 2
        cached = client.request_response("GET", "_apis/git/repositories/Website")
        self.assertTrue(cached.cache_hit)
        self.assertEqual(cached.observed_at, first.observed_at)
        self.assertEqual(client.request("GET", "_apis/git/repositories/Website", fresh=True), {"rev": 2})
        self.assertEqual(len(opener.calls), 2)

    def test_uncertain_writes_are_attempted_once_and_sanitized(self):
        for failure in (urllib.error.URLError("SECRET"), http.client.IncompleteRead(b"SECRET"),
                        urllib.error.HTTPError("https://SECRET", 503, "SECRET", {}, None),
                        Response(status=200, raw=b"SECRET")):
            with self.subTest(failure=type(failure).__name__):
                client, opener = self.client([failure], capabilities={"read", "board_write"})
                with self.assertRaises(az.AzureUncertainWrite) as result:
                    client.request("PATCH", "_apis/wit/workitems/17", data=[{"op": "test", "path": "/rev", "value": 1}], capability="board_write", before_write=lambda: None)
                self.assertNotIn("SECRET", str(result.exception))
                self.assertEqual(len(opener.calls), 1)

    def test_write_requires_action_authorization_callback_before_any_effect(self):
        client, opener = self.client([], capabilities={"read", "board_write"})
        with self.assertRaisesRegex(az.AzureError, "authorization"):
            client.request("PATCH", "_apis/wit/workitems/17", data=[], capability="board_write")
        self.assertEqual(opener.calls, [])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_write_authority_is_rechecked_after_shared_throttle_wait(self):
        first, _ = self.client([Response({}, headers={"Retry-After": "4"})])
        first.request("GET", "_apis/git/repositories/Website")
        deadline = self.clock() + 2
        client, opener = self.client([], capabilities={"read", "board_write"})
        checked = []

        def authorize():
            checked.append(self.clock())
            if self.clock() >= deadline:
                raise PermissionError("grant expired")

        with self.assertRaisesRegex(PermissionError, "grant expired"):
            client.request("PATCH", "_apis/wit/workitems/17", data=[],
                           capability="board_write", before_write=authorize)
        self.assertEqual(len(checked), 1)
        self.assertGreaterEqual(checked[0], deadline)
        self.assertEqual(sum(self.clock.sleeps), 4)
        self.assertEqual(opener.calls, [])

    def test_revision_conflict_is_not_retried(self):
        client, opener = self.client([urllib.error.HTTPError("https://SECRET", 412, "SECRET", {}, None)], capabilities={"read", "board_write"})
        with self.assertRaises(az.AzureRevisionConflict) as result:
            client.request("PATCH", "_apis/wit/workitems/17", data=[], capability="board_write", before_write=lambda: None)
        self.assertEqual(result.exception.status, 412)
        self.assertEqual(len(opener.calls), 1)

    def test_valid_json_with_truncated_content_length_is_incomplete(self):
        for method, capability, path in (("GET", "read", "_apis/git/repositories/Website"),
                                         ("PATCH", "board_write", "_apis/wit/workitems/17")):
            client, opener = self.client([Response({}, headers={"Content-Length": "100"})], capabilities={"read", "board_write"})
            expected = az.AzureReadIncomplete if method == "GET" else az.AzureUncertainWrite
            with self.assertRaises(expected):
                client.request(method, path, data=[] if method == "PATCH" else None, capability=capability, before_write=lambda: None)
            self.assertEqual(len(opener.calls), 1)

    def test_capability_and_url_rejections_are_inert(self):
        client, opener = self.client([], capabilities={"read", "board_write", "draft_pr"})
        calls = [
            ("GET", "https://other.invalid/Instablinds/Instablinds/_apis/wit/workitems", {}),
            ("GET", "https://dev.azure.com/Other/Instablinds/_apis/wit/workitems", {}),
            ("GET", "_apis/../../Other", {}),
            ("GET", "_apis/%252e%252e/Other", {}),
            ("POST", "_apis/build/builds", {"capability": "draft_pr"}),
            ("PATCH", "_apis/git/repositories/Website/pullrequests/1", {"capability": "draft_pr"}),
            ("POST", "_apis/git/repositories/Website/pullrequests", {"capability": "draft_pr", "data": {"isDraft": False}}),
            ("POST", "_apis/git/repositories/Website/pushes", {"capability": "draft_pr", "data": {"refUpdates": [{"name": "refs/heads/main", "oldObjectId": "0" * 40}]}}),
        ]
        for method, path, kwargs in calls:
            with self.subTest(path=path), self.assertRaises(az.AzureError):
                client.request(method, path, **kwargs)
        self.assertEqual(opener.calls, [])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_push_authorization_accepts_only_strict_create_only_task_branches(self):
        for branch in ("feature/test", "develop-staging-sr04-evidence"):
            with self.subTest(branch=branch):
                client, opener = self.client([Response({})], capabilities={"read", "draft_pr"})
                client.request(
                    "POST",
                    "_apis/git/repositories/Website/pushes",
                    capability="draft_pr",
                    data={"refUpdates": [{
                        "name": "refs/heads/" + branch,
                        "oldObjectId": "0" * 40,
                        "newObjectId": "1" * 40,
                    }]},
                    before_write=lambda: None,
                )
                self.assertEqual(len(opener.calls), 1)
        for branch in ("main", "develop", "feature/", "develop-", "develop/x", "develop-../main",
                       "develop-x:main", "+develop-x", "feature/x//y"):
            with self.subTest(branch=branch):
                client, opener = self.client([], capabilities={"read", "draft_pr"})
                with self.assertRaises(az.AzureError):
                    client.request(
                        "POST",
                        "_apis/git/repositories/Website/pushes",
                        capability="draft_pr",
                        data={"refUpdates": [{
                            "name": "refs/heads/" + branch,
                            "oldObjectId": "0" * 40,
                            "newObjectId": "1" * 40,
                        }]},
                        before_write=lambda: None,
                    )
                self.assertEqual(opener.calls, [])

    def test_pagination_continuation_and_skip_have_complete_explicit_queries(self):
        client, opener = self.client([Response({"count": 1, "value": [{"id": 1}]}, headers={"x-ms-continuationtoken": "abc"}),
                                     Response({"count": 1, "value": [{"id": 2}]})])
        collection = client.paged("_apis/git/repositories/Website/refs")
        self.assertTrue(collection.complete)
        self.assertEqual([item["id"] for item in collection.items], [1, 2])
        self.assertIn("continuationToken=abc", opener.calls[1].full_url)
        client, opener = self.client([Response({"value": [{"pullRequestId": 1}]}), Response({"value": []})])
        self.assertTrue(client.paged("_apis/git/repositories/Website/pullrequests", page_size=1, pagination="skip").complete)
        self.assertIn("%24skip=1", opener.calls[1].full_url)

    def test_pagination_missing_page_repeated_token_and_changed_native_id_fail_closed(self):
        cases = [
            [Response({"count": 2, "value": [{"id": 1}]})],
            [Response({"value": [{"id": 1}]}, headers={"x-ms-continuationtoken": "x"}),
             Response({"value": [{"id": 2}]}, headers={"x-ms-continuationtoken": "x"})],
            [Response({"value": [{"id": 1, "rev": 1}]}, headers={"x-ms-continuationtoken": "x"}),
             Response({"value": [{"id": 1, "rev": 2}]})],
            [Response({"value": [{"id": 1}]}, headers={"x-ms-continuationtoken": "x"}),
             urllib.error.HTTPError("", 404, "secret", {}, None)],
        ]
        for responses in cases:
            with self.subTest(count=len(responses)):
                client, _ = self.client(responses)
                collection = client.paged("_apis/build/builds")
                self.assertFalse(collection.complete)
                self.assertTrue(collection.blockers)
        client, opener = self.client([Response({"value": [{"id": 1}]}, headers={"x-ms-continuationtoken": "x"})], max_pages=1)
        self.assertFalse(client.paged("_apis/build/builds").complete)
        self.assertEqual(len(opener.calls), 1)
        full, _ = self.client([Response({"value": [{"id": 1}]})])
        self.assertFalse(full.paged("_apis/build/builds", page_size=1).complete)

    def test_batch_size_cache_expansion_and_incomplete_ids(self):
        def batch(request):
            body = json.loads(request.data)
            self.assertEqual(body["$expand"], "All")
            self.assertLessEqual(len(body["ids"]), 200)
            return Response({"value": [{"id": key, "rev": 1, "fields": {}} for key in body["ids"]]})
        client, opener = self.client([batch, batch])
        result = client.get_work_items(range(1, 202))
        self.assertTrue(result.complete)
        self.assertEqual(len(result.items), 201)
        self.assertTrue(all(item["relations"] == [] for item in result.items))
        self.assertEqual(len(opener.calls), 2)
        self.assertTrue(client.get_work_items(range(1, 202)).complete)
        self.assertEqual(len(opener.calls), 2)
        broken, _ = self.client([Response({"value": [{"id": 1}]})])
        self.assertFalse(broken.get_work_items([1, 2]).complete)

    def test_lock_is_shared_between_processes(self):
        ctx = multiprocessing.get_context("fork")
        entered, release = ctx.Event(), ctx.Event()
        process = ctx.Process(target=lock_process, args=(str(self.root), entered, release))
        process.start()
        try:
            self.assertTrue(entered.wait(5), "child failed to enter the throttle")
            with self.assertRaisesRegex(az.AzureError, "shared Azure throttle"):
                with az.SharedThrottle(self.root, max_wait=0).slot():
                    self.fail("parallel process bypassed shared flock")
        finally:
            release.set()
            process.join(5)
            if process.is_alive():
                process.terminate()
                process.join(5)
        self.assertEqual(process.exitcode, 0)

    def test_success_retry_after_deadline_survives_process_exit(self):
        ctx = multiprocessing.get_context("fork")
        output = ctx.Queue()
        receipts = []
        for first in (True, False):
            process = ctx.Process(target=deadline_process, args=(str(self.root), first, output))
            process.start()
            process.join(5)
            if process.is_alive():
                process.terminate()
                process.join(5)
                self.fail("deadline fixture process did not terminate")
            self.assertEqual(process.exitcode, 0)
            receipts.append(output.get(timeout=2))
        output.close()
        self.assertEqual(receipts, [{"calls": 1, "slept": 0, "result": {"ok": True}},
                                    {"calls": 1, "slept": 4, "result": {"ok": True}}])


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.manifest = graph({1: [], 2: [1]})
        self.items = [raw_item(1, "Done", successors=[2]), raw_item(2, deps=[1])]

    def project(self, *, items=None, manifest=None, auth=None, **kwargs):
        return az.project_snapshot({"complete": True, "observed_at": az.timestamp(self.clock()), "items": self.items if items is None else items},
                                   organization="Instablinds", project="Instablinds", expected_manifest=self.manifest if manifest is None else manifest,
                                   authority=authority(self.manifest) if auth is None else auth, clock=self.clock, **kwargs)

    def test_namespaced_revision_state_and_native_dependencies_are_preserved(self):
        result = self.project()
        self.assertTrue(result["complete"])
        self.assertTrue(result["dependency_complete"])
        second = result["items"][1]
        self.assertEqual((second["id"], second["revision"], second["state"], second["dependencies"]), (ident(2), 1, "To Do", [ident(1)]))
        self.assertTrue(second["eligible"])
        self.assertFalse(result["items"][0]["eligible"])

    def test_live_project_guid_shape_requires_verified_self_identity(self):
        # The pilot returned this GUID path for both row self URLs and links;
        # its project name remains the configured namespace, not the GUID.
        manifest = graph({18: [], 21: [18]})
        items = [with_project_guid(raw_item(18, "Done", successors=[21])),
                 with_project_guid(raw_item(21, deps=[18], revision=4))]
        report = self.project(items=items, manifest=manifest, auth=authority(manifest))
        self.assertTrue(report["dependency_complete"])
        self.assertEqual(report["native_dependency_count"], 1)
        self.assertEqual(report["items"][1]["dependencies"], [ident(18)])
        self.assertEqual(report["items"][1]["revision"], 4)
        self.assertTrue(report["items"][1]["eligible"])
        self.assertEqual(az.verified_project_alias(items[1], "Instablinds", "Instablinds"), PROJECT_GUID)
        self.assertNotIn(PROJECT_GUID, json.dumps(report))

    def test_guid_dependency_without_matching_self_proof_never_qualifies(self):
        base = with_project_guid(raw_item(2, deps=[1]))
        variants = []
        missing = deepcopy(base)
        del missing["url"]
        variants.append(missing)
        for url in (None, base["url"].replace("/2", "/3"),
                    base["url"].replace("/Instablinds/", "/Other/", 1),
                    base["url"].replace(PROJECT_GUID, "OtherProject"),
                    base["url"].replace(PROJECT_GUID, OTHER_PROJECT_GUID)):
            variants.append({**deepcopy(base), "url": url})
        foreign = deepcopy(base)
        foreign["fields"]["System.TeamProject"] = "OtherProject"
        variants.append(foreign)
        for item in variants:
            with self.subTest(self_url=item.get("url")):
                report = self.project(items=[self.items[0], item])
                self.assertFalse(report["complete"])
                self.assertFalse(report["dependency_complete"])
                self.assertEqual(report["eligible_count"], 0)
                self.assertIn("unresolved-native-dependency", report["items"][1]["blockers"])

    def test_dependency_url_keeps_strict_origin_path_and_identifier_guards(self):
        prefix = f"https://dev.azure.com/Instablinds/{PROJECT_GUID}/_apis/wit/workItems/"
        invalid = [None, 2, prefix + "0", prefix + "02", prefix + "%32", prefix + "2/", prefix + "2?",
                   prefix + "2#", prefix + "2?api-version=7.1", prefix + "2#fragment", prefix + "../2",
                   prefix + "2%2f3", prefix + "%2e%2e", prefix + "2%5c3", prefix + "2%zz",
                   prefix.replace("https://", "http://") + "2", prefix.replace("dev.azure.com", "dev.azure.com:443") + "2",
                   prefix.replace("dev.azure.com", "actor@dev.azure.com") + "2",
                   prefix.replace("dev.azure.com", "dev.azure.com.attacker.test") + "2",
                   prefix.replace("/Instablinds/", "/Other/", 1) + "2",
                   prefix.replace(PROJECT_GUID, OTHER_PROJECT_GUID) + "2",
                   prefix.replace(PROJECT_GUID, "OtherProject") + "2", "https://[invalid/2", "\n" + prefix + "2"]
        for url in invalid:
            with self.subTest(url=url), self.assertRaises(az.AzureError):
                az._relation_id("Instablinds", "Instablinds", url, project_alias=PROJECT_GUID)
        for url in ("https://dev.azure.com/Instablinds/_apis/wit/workItems/2",
                    "https://dev.azure.com/Instablinds/Instablinds/_apis/wit/workitems/2"):
            self.assertEqual(az._relation_id("Instablinds", "Instablinds", url), ident(2))
        with self.assertRaises(az.AzureError):
            az._relation_id("Instablinds", "Instablinds", prefix + "2")

    def test_mixed_verified_self_guids_cannot_relabel_one_project(self):
        items = [with_project_guid(self.items[0]), with_project_guid(self.items[1], OTHER_PROJECT_GUID)]
        report = self.project(items=items)
        self.assertIn("inconsistent-native-project-identity", report["blockers"])
        self.assertFalse(report["complete"])
        self.assertFalse(report["dependency_complete"])
        self.assertEqual(report["eligible_count"], 0)

    def test_missing_authority_self_asserted_completeness_and_pending_dependency_block(self):
        blocked = self.project(auth={"complete": True, "execution_authorized": True})
        self.assertEqual(blocked["eligible_count"], 0)
        self.assertIn("dependency-contract-approval-not-established", blocked["blockers"])
        items = [raw_item(1, successors=[2]), raw_item(2, deps=[1])]
        self.assertIn("dependency-not-completed:" + ident(1), self.project(items=items)["items"][1]["blockers"])
        bad_contract = {"schema_version": 1, "complete": True}
        self.assertEqual(self.project(manifest=bad_contract)["eligible_count"], 0)

    def test_unknown_missing_cross_project_and_unresolved_relations_block(self):
        unknown = raw_item(1, "Unexpected")
        no_relations = raw_item(1)
        del no_relations["relations"]
        wrong_project = raw_item(1)
        wrong_project["fields"]["System.TeamProject"] = "Other"
        unresolved = raw_item(1, deps=[2])
        unresolved["relations"][0]["url"] = "https://dev.azure.com/Other/_apis/wit/workItems/2"
        for item in (unknown, no_relations, wrong_project, unresolved, {"id": 1, "fields": {}}):
            with self.subTest(item=item):
                report = self.project(items=[item])
                self.assertFalse(report["complete"])
                self.assertFalse(report["dependency_complete"])
                self.assertEqual(report["eligible_count"], 0)
        sensitive = raw_item(1, "SECRET")
        sensitive["fields"]["System.Title"] = "SECRET"
        report = self.project(items=[sensitive])
        self.assertNotIn("SECRET", json.dumps(report))

    def test_reciprocal_missing_unresolved_closure_cycles_and_stale_snapshots_block(self):
        report = self.project(items=[raw_item(1, "Done"), raw_item(2, deps=[1])])
        self.assertIn("incomplete-reciprocal-native-dependency", report["blockers"])
        report = self.project(items=[raw_item(2, deps=[1])])
        self.assertIn("unresolved-dependency-closure", report["blockers"])
        report = self.project(items=[raw_item(1, "Done", successors=[2])], manifest=graph({1: []}))
        self.assertIn("unresolved-dependency-closure", report["blockers"])
        report = self.project(items=[raw_item(1, "Done", successors=[2]), raw_item(2)])
        self.assertIn("incomplete-reciprocal-native-dependency", report["blockers"])
        cyclic = graph({1: [2], 2: [1]})
        report = self.project(items=[raw_item(1, deps=[2], successors=[2]), raw_item(2, deps=[1], successors=[1])], manifest=cyclic, auth=authority(cyclic))
        self.assertIn("cyclic-dependency-graph", report["blockers"])
        for observed in (None, "not-a-date", az.timestamp(self.clock() - 301), az.timestamp(self.clock() + 10)):
            report = az.project_snapshot({"complete": True, "observed_at": observed, "items": self.items}, organization="Instablinds", project="Instablinds",
                                         expected_manifest=self.manifest, authority=authority(self.manifest), clock=self.clock)
            self.assertIn("missing-or-stale-observation", report["blockers"])
            self.assertEqual(report["eligible_count"], 0)

    def test_expected_missing_edges_cannot_be_authorized_by_old_board_approval(self):
        items = [raw_item(1, "Done"), raw_item(2)]
        result = self.project(items=items)
        self.assertFalse(result["dependency_complete"])
        self.assertEqual(result["missing_dependency_edges"], [[ident(2), ident(1)]])
        supplement = graph({2: [1]})
        report = self.project(items=items, supplement=supplement)
        self.assertIn("dependency-supplement-not-explicitly-approved", report["blockers"])
        explicit = authority(self.manifest, dependency_supplement_sha256=az.canonical_digest(supplement), supplement_approval_record="test-exact-edge-approval")
        report = self.project(items=items, supplement=supplement, auth=explicit)
        self.assertTrue(report["dependency_complete"])
        self.assertTrue(report["items"][1]["eligible"])
        self.assertEqual(report["native_dependency_count"], 0)
        supplement["dependencies"][ident(2)].append(ident(3))
        self.assertEqual(self.project(items=items, supplement=supplement, auth=explicit)["eligible_count"], 0)

    def test_long_chain_uses_bounded_iterative_cycle_detection(self):
        count = 1200
        manifest = graph({key: [key - 1] if key > 1 else [] for key in range(1, count + 1)})
        items = [raw_item(key, "Done", deps=[key - 1] if key > 1 else [], successors=[key + 1] if key < count else []) for key in range(1, count + 1)]
        self.assertTrue(self.project(items=items, manifest=manifest, auth=authority(manifest))["dependency_complete"])

    def test_website_fixture_preserves_37_nodes_71_edges_and_grants_no_authority(self):
        fixture = json.loads((ROOT / "tests/fixtures/azure-website-dependencies.expected.json").read_text())
        self.assertEqual(len(fixture["dependencies"]), 37)
        self.assertEqual(sum(map(len, fixture["dependencies"].values())), 71)
        self.assertEqual(fixture["approval_status"], "unapproved")
        self.assertFalse(fixture["execution_authorized"])
        self.assertTrue(all(key.startswith("azdo:Instablinds:Instablinds:") for key in fixture["dependencies"]))

    def test_current_53_applied_edges_leave_exactly_18_prerequisites_blocking(self):
        fixture = json.loads((ROOT / "tests/fixtures/azure-website-dependencies.expected.json").read_text())
        rollout = {17, 18, 19, 21, 22, 24, 26, 28, 30, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43}
        applied = {int(key.rsplit(":", 1)[1]): [int(dep.rsplit(":", 1)[1]) for dep in deps] if int(key.rsplit(":", 1)[1]) in rollout else []
                   for key, deps in fixture["dependencies"].items()}
        successors = {key: [] for key in applied}
        for target, dependencies in applied.items():
            for dep in dependencies:
                successors[dep].append(target)
        items = [raw_item(key, deps=deps, successors=successors[key]) for key, deps in applied.items()]
        for native_items in (items, [with_project_guid(item) for item in items]):
            with self.subTest(project_guid="url" in native_items[0]):
                report = self.project(items=native_items, manifest=fixture, auth={})
                self.assertEqual(report["native_dependency_count"], 53)
                self.assertEqual(len(report["missing_dependency_edges"]), 18)
                self.assertEqual(report["eligible_count"], 0)
                self.assertFalse(report["dependency_complete"])
                self.assertIn("execution-authority-not-established", report["blockers"])

    def test_provider_reads_both_directions_before_project_qualification(self):
        predecessor = with_project_guid(raw_item(1, "Done", successors=[2]))
        selected = with_project_guid(raw_item(2, deps=[1], successors=[3]))
        successor = with_project_guid(raw_item(3, deps=[2]))
        client = types.SimpleNamespace(organization="Instablinds", project="Instablinds", clock=self.clock)
        collection = lambda values: az.ReadCollection(items=values, observed_at=az.timestamp(self.clock()))
        client.get_work_items = mock.Mock(side_effect=[collection([selected]), collection([predecessor, successor]),
                                                      collection([predecessor, selected, successor])])
        report = az.AzureBoardsProvider(client).inspect([2])
        self.assertEqual([sorted(call.args[0]) for call in client.get_work_items.call_args_list], [[2], [1, 3], [1, 2, 3]])
        self.assertTrue(report["complete"])
        self.assertEqual(report["native_dependency_count"], 2)
        self.assertFalse(report["dependency_complete"])  # No reviewed contract was supplied.
        self.assertEqual(report["eligible_count"], 0)

    def test_org_scoped_successor_fetch_checks_actual_project_and_stops_foreign_fanout(self):
        selected = raw_item(1, "Done", successors=[2])
        foreign = raw_item(2, deps=[1], successors=[999])
        foreign["fields"]["System.TeamProject"] = "OtherProject"
        client = types.SimpleNamespace(organization="Instablinds", project="Instablinds", clock=self.clock)
        collection = lambda values: az.ReadCollection(items=values, observed_at=az.timestamp(self.clock()))
        client.get_work_items = mock.Mock(side_effect=[collection([selected]), collection([foreign]), collection([selected, foreign])])
        report = az.AzureBoardsProvider(client).inspect([1])
        self.assertEqual([sorted(call.args[0]) for call in client.get_work_items.call_args_list], [[1], [2], [1, 2]])
        self.assertFalse(report["complete"])
        self.assertFalse(report["dependency_complete"])
        self.assertEqual(report["eligible_count"], 0)
        self.assertIn("missing-or-cross-project-work-item", report["items"][1]["blockers"])

    def test_successor_closure_keeps_max_item_budget_and_partial_read_blocks(self):
        selected = raw_item(1, "Done", successors=[2])
        first = az.ReadCollection(items=[selected], observed_at=az.timestamp(self.clock()))
        client = types.SimpleNamespace(organization="Instablinds", project="Instablinds", clock=self.clock)
        client.get_work_items = mock.Mock(return_value=first)
        report = az.AzureBoardsProvider(client, max_items=1).inspect([1])
        self.assertIn("dependency-closure-budget-exhausted", report["read_blockers"])
        self.assertEqual(client.get_work_items.call_count, 1)
        client.get_work_items = mock.Mock(side_effect=[first, az.ReadCollection(complete=False, blockers=["missing-successor-row"])])
        report = az.AzureBoardsProvider(client).inspect([1])
        self.assertIn("missing-successor-row", report["read_blockers"])
        self.assertFalse(report["complete"])
        self.assertEqual(report["eligible_count"], 0)

    def test_fresh_recheck_cannot_change_project_alias_or_project_field_at_same_revision(self):
        initial = [with_project_guid(item) for item in self.items]
        alias_drift = [with_project_guid(item, OTHER_PROJECT_GUID) for item in self.items]
        project_drift = deepcopy(initial)
        project_drift[0]["fields"]["System.TeamProject"] = "OtherProject"
        for changed in (alias_drift, project_drift):
            with self.subTest(changed=changed[0]["fields"]["System.TeamProject"]):
                client = types.SimpleNamespace(organization="Instablinds", project="Instablinds", clock=self.clock)
                collection = lambda values: az.ReadCollection(items=values, observed_at=az.timestamp(self.clock()))
                client.get_work_items = mock.Mock(side_effect=[collection(initial), collection(changed)])
                report = az.AzureBoardsProvider(client).inspect([2], expected_manifest=self.manifest, authority=authority(self.manifest))
                self.assertTrue(set(report["read_blockers"]) & {"project-identity-changed-during-inspection", "invalid-project-identity-during-inspection"})
                self.assertFalse(report["complete"])
                self.assertEqual(report["eligible_count"], 0)

    def test_provider_fresh_revision_drift_and_incomplete_batch_block(self):
        client = types.SimpleNamespace(organization="Instablinds", project="Instablinds", clock=self.clock)
        first = az.ReadCollection(items=self.items, observed_at=az.timestamp(self.clock()))
        changed = az.ReadCollection(items=[{**self.items[0], "rev": 2}, self.items[1]], observed_at=az.timestamp(self.clock()))
        client.get_work_items = mock.Mock(side_effect=[first, changed])
        report = az.AzureBoardsProvider(client).inspect([2], expected_manifest=self.manifest, authority=authority(self.manifest))
        self.assertIn("revision-changed-during-inspection", report["read_blockers"])
        self.assertEqual(report["eligible_count"], 0)
        self.assertTrue(all(call.kwargs["fresh"] for call in client.get_work_items.call_args_list))
        client.get_work_items = mock.Mock(return_value=az.ReadCollection(complete=False, blockers=["missing-page"]))
        self.assertEqual(az.AzureBoardsProvider(client).inspect([2])["eligible_count"], 0)


class EvidenceAndCliTests(unittest.TestCase):
    def test_policy_endpoint_preview_version_skip_and_sanitized_nested_records(self):
        clock = Clock()
        client = types.SimpleNamespace(clock=clock, organization="Instablinds", project="Instablinds")
        client.request = mock.Mock(side_effect=[{"id": "repo", "name": "Website", "project": {"id": "project"}},
                                               {"records": [{"id": "task", "state": "completed", "result": "succeeded", "log": {"secret": "NOPE"}}]}])
        client.paged = mock.Mock(side_effect=[
            az.ReadCollection(items=[{"name": "refs/heads/develop", "objectId": "abc"}]),
            az.ReadCollection(items=[{"pullRequestId": 4, "status": "active", "isDraft": True,
                                      "sourceRefName": "refs/heads/feature/test", "targetRefName": "refs/heads/develop",
                                      "lastMergeSourceCommit": {"commitId": "abc", "author": "NOPE"}}]),
            az.ReadCollection(items=[{"id": 1, "type": {"id": "kind", "url": "NOPE"}, "settings": {"secret": "NOPE", "requiredReviewerIds": ["NOPE"], "minimumApproverCount": 2}}]),
            az.ReadCollection(items=[{"id": 9, "sourceVersion": "abc", "status": "completed", "result": "succeeded"}]),
            az.ReadCollection(items=[{"evaluationId": "e", "status": "approved"}]),
        ])
        report = az.AzureBoardsProvider(client).repository_evidence("Website")
        self.assertTrue(report["complete"])
        self.assertNotIn("NOPE", json.dumps(report))
        self.assertEqual(client.paged.call_args_list[2].args[0], "_apis/git/policy/configurations")
        check = client.paged.call_args_list[4]
        self.assertEqual(check.kwargs["query"]["api-version"], "7.1-preview.1")
        self.assertEqual(check.kwargs["pagination"], "skip")
        self.assertFalse(report["deployment_authority"])

    def test_unknown_or_malformed_timeline_is_incomplete_but_in_progress_is_valid(self):
        for records, valid in (([{"id": "x", "state": "invented"}], False), (["not-a-record"], False),
                               ([{"id": "x", "state": "completed", "result": None}], False),
                               ([{"id": "x", "state": "inProgress", "result": None}], True)):
            client = types.SimpleNamespace(clock=Clock(), organization="Instablinds", project="Instablinds")
            client.request = mock.Mock(side_effect=[{"id": "repo"}, {"records": records}])
            client.paged = mock.Mock(side_effect=[az.ReadCollection(items=[{"name": "refs/heads/develop", "objectId": "abc"}]),
                                                  az.ReadCollection(), az.ReadCollection(),
                                                  az.ReadCollection(items=[{"id": 9, "sourceVersion": "abc", "status": "inProgress", "result": None}])])
            with self.subTest(records=records):
                self.assertEqual(az.AzureBoardsProvider(client).repository_evidence("Website")["complete"], valid)

    def test_auth_rejects_foreign_home_and_config_before_subprocess(self):
        actual = az.pwd.getpwuid(os.getuid()).pw_dir
        for env in ({"HOME": "/home/another-person"}, {"HOME": actual, "AZURE_CONFIG_DIR": "/home/another-person/.azure"}):
            with mock.patch.dict(os.environ, env, clear=False), mock.patch.object(az.subprocess, "run") as run:
                with self.assertRaises(az.AzureError):
                    az.azure_cli_headers()
                run.assert_not_called()

    def test_auth_failure_never_discloses_captured_details(self):
        actual = az.pwd.getpwuid(os.getuid()).pw_dir
        with mock.patch.dict(os.environ, {"HOME": actual, "AZURE_CONFIG_DIR": actual + "/.azure"}), mock.patch.object(az.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "SECRET", "SECRET")):
            with self.assertRaises(az.AzureError) as result:
                az.azure_cli_headers()
        self.assertNotIn("SECRET", str(result.exception))

    def test_real_throttle_rejects_wrong_identity_without_creating_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(az.AzureError):
                with az.SharedThrottle(Path(tmp)).slot():
                    self.fail("wrong identity root passed")
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_dry_run_and_snapshot_leave_all_files_unchanged_without_auth_or_network(self):
        loader = importlib.machinery.SourceFileLoader("azure_inspect_cli_test", str(ROOT / "atlas-agent-azure-inspect"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        cli = importlib.util.module_from_spec(spec)
        loader.exec_module(cli)
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            config = folder / "config.json"
            config.write_text(json.dumps({"schema_version": 1, "provider": "azure-devops", "repository": {"organization": "Instablinds", "project": "Instablinds", "name": "Website", "url": "https://dev.azure.com/Instablinds/Instablinds/_git/Website", "base_branch": "develop"}, "capabilities": ["read"], "models": {"default": {"model": "gpt-6-astra", "reasoning": "max"}}, "sandbox": "workspace-write", "approval_policy": "on-request"}))
            snapshot = folder / "snapshot.json"
            snapshot.write_text(json.dumps({"items": [raw_item(17)], "complete": True, "observed_at": az.timestamp()}))
            before = {str(path): path.read_bytes() for path in folder.rglob("*") if path.is_file()}
            for extra in (["--dry-run"], ["--snapshot", str(snapshot)]):
                with self.subTest(extra=extra), mock.patch.object(cli, "azure_cli_headers", side_effect=AssertionError("auth called")), mock.patch.object(cli, "AzureDevOpsClient", side_effect=AssertionError("network client created")), contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(cli.main(["--config", str(config), "--ids", "17", *extra]), 0)
                report = json.loads(output.getvalue())
                self.assertEqual(report["eligible_count"], 0)
                self.assertEqual(report["effective_configuration"]["models"]["implementation"]["model"], "gpt-6-astra")
            after = {str(path): path.read_bytes() for path in folder.rglob("*") if path.is_file()}
            self.assertEqual(before, after)

    def test_inspection_input_rejects_foreign_identity_before_file_read(self):
        loader = importlib.machinery.SourceFileLoader("azure_inspect_path_test", str(ROOT / "atlas-agent-azure-inspect"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        cli = importlib.util.module_from_spec(spec)
        loader.exec_module(cli)
        with mock.patch.object(Path, "read_text", side_effect=AssertionError("read attempted")):
            with self.assertRaises(az.AzureError):
                cli._read_json("/home/another-person/private/snapshot.json")


if __name__ == "__main__":
    unittest.main()
