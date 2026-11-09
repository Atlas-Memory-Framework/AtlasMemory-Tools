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


class SelectedBuildAcquisitionTests(unittest.TestCase):
    def build(self, number=9, **changes):
        return {"id": number, "repository": {"id": PROJECT_GUID.upper()},
                "status": "completed", "result": "succeeded", "sourceVersion": "a" * 40,
                "sourceBranch": "refs/heads/feature/selected", **changes}

    def inspect(self, ids, *, metadata=None, listed=(), repository_id=PROJECT_GUID,
                timeline=None, fresh=True):
        client = types.SimpleNamespace(clock=Clock(), organization="Instablinds", project="Instablinds")
        def request(method, path, **kwargs):
            self.assertEqual(method, "GET")
            if path.startswith("_apis/git/repositories/"):
                return {"id": repository_id}
            if path.endswith("/timeline"):
                response = {"records": []} if timeline is None else timeline
            else:
                number = int(path.rsplit("/", 1)[-1])
                response = self.build(number) if metadata is None else metadata[number]
            if isinstance(response, Exception):
                raise response
            return deepcopy(response)
        client.request = mock.Mock(side_effect=request)
        client.paged = mock.Mock(side_effect=[
            az.ReadCollection(items=[{"name": "refs/heads/develop", "objectId": "a" * 40}]),
            az.ReadCollection(), az.ReadCollection(), az.ReadCollection(items=list(listed))])
        report = az.AzureBoardsProvider(client).repository_evidence("Website", build_ids=ids, fresh=fresh)
        return report, client.request.call_args_list[1:]

    def test_binding_sidecar_matches_frozen_planning_examples_without_extra_gets(self):
        repository_id = "11111111-2222-3333-4444-555555555555"
        valid = {"build_id": 9, "repository_id": repository_id, "definition_id": 7,
                 "definition_revision": 3, "bindings_complete": True,
                 "binding_missing_fields": [], "binding_malformed_fields": []}
        missing_revision = {"build_id": 9, "repository_id": repository_id, "definition_id": 7,
                            "bindings_complete": False, "binding_missing_fields": ["build.definition_revision"],
                            "binding_malformed_fields": []}
        foreign = {"build_id": 9, "bindings_complete": False, "binding_missing_fields": [],
                   "binding_malformed_fields": ["build.repository_id"]}
        for listed in (False, True):
            for native, expected in ((self.build(repository={"id": repository_id}, definition={"id": 7, "revision": 3}), valid),
                                     (self.build(repository={"id": repository_id}, definition={"id": 7}), missing_revision),
                                     (self.build(repository={"id": OTHER_PROJECT_GUID}, definition={"id": 7, "revision": 3}), foreign)):
                with self.subTest(listed=listed, native=native):
                    report, calls = self.inspect([9], listed=[native] if listed else [], metadata={9: native}, repository_id=repository_id)
                    self.assertEqual(report["build_bindings"], [expected])
                    self.assertEqual(len(calls), 1 if listed or expected == foreign else 2)
                    self.assertEqual(calls[0].args[1], "_apis/build/builds/9/timeline" if listed else "_apis/build/builds/9")
                    self.assertEqual(report["complete"], listed or expected != foreign)
                    if listed and expected == foreign:
                        self.assertEqual(len(report["builds"]), 1)
                        self.assertEqual(len(report["timelines"]), 1)

    def test_binding_definition_missing_and_malformed_values_do_not_change_acquisition(self):
        for definition, missing, malformed in ((None, ["build.definition_id", "build.definition_revision"], []),
                ({}, ["build.definition_id", "build.definition_revision"], []),
                ({"id": 7, "revision": None}, ["build.definition_revision"], []),
                ("PRIVATE_SENTINEL", [], ["build.definition_id", "build.definition_revision"]),
                ([], [], ["build.definition_id", "build.definition_revision"])):
            with self.subTest(definition=definition):
                report, calls = self.inspect([9], metadata={9: self.build(definition=definition)})
                row = report["build_bindings"][0]
                self.assertTrue(report["complete"])
                self.assertEqual(len(calls), 2)
                self.assertEqual(row["binding_missing_fields"], missing)
                self.assertEqual(row["binding_malformed_fields"], malformed)
                self.assertFalse(row["bindings_complete"])
                self.assertEqual(row["repository_id"], PROJECT_GUID.lower())
                self.assertNotIn("PRIVATE_SENTINEL", json.dumps(row))
        for field, code in (("id", "definition_id"), ("revision", "definition_revision")):
            for value in (True, False, 0, -1, 2**31, 1.0, "7", [], {}, "PRIVATE_SENTINEL"):
                with self.subTest(field=field, value=value):
                    definition = {"id": 7, "revision": 3, field: value}
                    report, calls = self.inspect([9], metadata={9: self.build(definition=definition)})
                    row = report["build_bindings"][0]
                    self.assertEqual(row["binding_malformed_fields"], ["build." + code])
                    self.assertNotIn(code, row)
                    self.assertTrue(report["complete"])
                    self.assertEqual(len(calls), 2)
        report, _ = self.inspect([9], metadata={9: self.build(definition={"id": 2**31 - 1, "revision": 2**31 - 1})})
        self.assertTrue(report["build_bindings"][0]["bindings_complete"])
        self.assertEqual(report["build_bindings"][0]["definition_revision"], 2**31 - 1)

    def test_binding_identity_failures_strip_all_values_and_keep_fixed_diagnostics(self):
        cases = [(self.build(id=None), ["build.id"], []),
                 (self.build(repository=None), ["build.repository_id"], []),
                 (self.build(repository={}), ["build.repository_id"], []),
                 (self.build(repository={"id": None}), ["build.repository_id"], [])]
        cases += [(self.build(id=value), [], ["build.id"]) for value in (True, 9.0, "9", 0, -1, 10, 2**31)]
        cases += [(self.build(repository=value), [], ["build.repository_id"]) for value in ([], "PRIVATE_SENTINEL", {"id": OTHER_PROJECT_GUID}, {"id": 7}, {"id": PROJECT_GUID + "\n"})]
        for native, missing, malformed in cases:
            native["definition"] = {"id": 7, "revision": 3}
            with self.subTest(native=native):
                report, calls = self.inspect([9], metadata={9: native})
                self.assertEqual(report["build_bindings"], [{"build_id": 9, "bindings_complete": False,
                    "binding_missing_fields": missing, "binding_malformed_fields": malformed}])
                self.assertEqual(len(calls), 1)
                self.assertEqual(report["builds"], [])
                self.assertEqual(report["timelines"], [])
                self.assertNotIn("PRIVATE_SENTINEL", json.dumps(report["build_bindings"]))
        report, _ = self.inspect([9], repository_id="invalid-selected-repository", metadata={9: self.build(definition={"id": 7, "revision": 3})})
        self.assertEqual(report["build_bindings"][0]["binding_malformed_fields"], ["build.repository_id"])
        self.assertNotIn("repository_id", report["build_bindings"][0])

    def test_binding_unavailable_and_rejected_acquisition_are_distinct(self):
        for native in (None, [], "PRIVATE_SENTINEL", az.AzureError("PRIVATE_SENTINEL")):
            with self.subTest(native=native):
                report, calls = self.inspect([9], metadata={9: native})
                self.assertEqual(report["build_bindings"], [{"build_id": 9, "bindings_complete": False,
                    "binding_missing_fields": ["build.definition_id", "build.definition_revision", "build.id", "build.repository_id"],
                    "binding_malformed_fields": []}])
                self.assertEqual(len(calls), 1)
                self.assertNotIn("PRIVATE_SENTINEL", json.dumps(report))
        for changes in ({"sourceVersion": "bad"}, {"sourceBranch": "bad"}, {"status": "unknown"}, {"result": "unknown"}):
            with self.subTest(changes=changes):
                native = self.build(definition={"id": 7, "revision": 3}, **changes)
                report, calls = self.inspect([9], metadata={9: native})
                self.assertTrue(report["build_bindings"][0]["bindings_complete"])
                self.assertFalse(report["complete"])
                self.assertEqual(report["builds"], [])
                self.assertEqual(report["timelines"], [])
                self.assertEqual(len(calls), 1)

    def test_duplicate_binding_rows_normalize_before_conflict_detection(self):
        first = self.build(definition={"id": 7, "revision": 3})
        same = self.build(repository={"id": PROJECT_GUID.lower(), "private": "PRIVATE_SENTINEL"},
                          definition={"id": 7, "revision": 3, "name": "PRIVATE_SENTINEL"})
        report, calls = self.inspect([9, 9], listed=[first, same])
        self.assertEqual(len(report["build_bindings"]), 1)
        self.assertTrue(report["build_bindings"][0]["bindings_complete"])
        self.assertEqual(len(report["builds"]), 2)
        self.assertEqual(len(calls), 1)
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(report["build_bindings"]))
        for different in (self.build(definition={"id": 8, "revision": 3}), self.build(definition={"id": 7}),
                          self.build(repository={"id": OTHER_PROJECT_GUID}, definition={"id": 7, "revision": 3})):
            with self.subTest(different=different):
                report, calls = self.inspect([9], listed=[first, different])
                self.assertEqual(report["build_bindings"], [{"build_id": 9, "bindings_complete": False,
                    "binding_missing_fields": [], "binding_malformed_fields": ["build.id"]}])
                self.assertTrue(report["complete"])
                self.assertEqual(len(report["builds"]), 2)
                self.assertEqual(len(calls), 1)

    def test_binding_selection_count_privacy_and_per_row_byte_bounds(self):
        report, calls = self.inspect([33, *range(32, 0, -1), 1, True, "2", 0])
        rows = report["build_bindings"]
        self.assertEqual([row["build_id"] for row in rows], list(range(1, 33)))
        self.assertEqual(len(calls), 64)
        sizes = [len(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")) for row in rows]
        self.assertTrue(all(size <= 512 for size in sizes))
        self.assertLessEqual(sum(sizes), 16384)
        native = self.build(definition={"id": 7, "revision": 3, "name": "PRIVATE_SENTINEL" * 10000},
                            repository={"id": PROJECT_GUID, "url": "PRIVATE_SENTINEL" * 10000},
                            queueTime="1991-01-01T00:59:60+01:00")
        report, _ = self.inspect([9], metadata={9: native})
        self.assertTrue(report["build_bindings"][0]["bindings_complete"])
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(report["build_bindings"]))
        self.assertEqual(report["builds"][0]["queueTime"], native["queueTime"])
        fallback = az._bounded_build_binding({"build_id": 9, "repository_id": "PRIVATE_SENTINEL" * 1000})
        self.assertEqual(fallback, {"build_id": 9, "bindings_complete": False,
            "binding_missing_fields": ["build.definition_id", "build.definition_revision", "build.id", "build.repository_id"],
            "binding_malformed_fields": []})
        self.assertLessEqual(len(json.dumps(fallback, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")), 512)
        report, calls = self.inspect([False, "9", 0])
        self.assertEqual(report["build_bindings"], [])
        self.assertEqual(calls, [])

    def test_binding_legacy_no_selection_omits_explicit_sidecar_and_preserves_fields(self):
        native = self.build(definition={"id": 7, "revision": 3})
        report, calls = self.inspect([], listed=[native])
        self.assertNotIn("build_bindings", report)
        self.assertNotIn("build_source_bindings", report)
        self.assertNotIn("build_time_bindings", report)
        self.assertEqual(set(report["default_build_bindings"]), {"repository_definition", "source", "time"})
        self.assertEqual(report["builds"], [{key: native.get(key) for key in (
            "id", "buildNumber", "status", "result", "sourceBranch", "sourceVersion", "queueTime", "startTime", "finishTime")}])
        self.assertEqual(report["timeline_scope"], "first-ten-listed-builds")
        self.assertEqual(report["requested_build_ids"], [])
        self.assertTrue(report["complete"])
        self.assertEqual(len(calls), 1)

    def source_build(self, **changes):
        return self.build(definition={"id": 7, "revision": 3},
                          sourceBranch="refs/heads/PRIVATE_SENTINEL/é", **changes)

    def source_expected(self, **changes):
        return {"build_id": 9, "source_commit_sha": "a" * 40,
                "source_ref_sha256": "d8f2d99dcb8151ef9a5d5aaa0b7445a4507d2cd979934c9dd2784a37fea6bf54",
                "bindings_complete": True, "binding_missing_fields": [], "binding_malformed_fields": [], **changes}

    def test_source_binding_exact_listed_and_fetched_failed_build_oracle(self):
        native = self.source_build(result="failed", logs={"url": "PRIVATE_SENTINEL"}, name="PRIVATE_SENTINEL")
        for listed in (False, True):
            with self.subTest(listed=listed):
                report, calls = self.inspect([9], listed=[native] if listed else [], metadata={9: native}, fresh=False)
                self.assertEqual(report["build_source_bindings"], [self.source_expected()])
                expected = [mock.call("GET", "_apis/build/builds/9/timeline", fresh=False)]
                if not listed:
                    expected.insert(0, mock.call("GET", "_apis/build/builds/9", fresh=True))
                self.assertEqual(calls, expected)
                self.assertEqual(report["builds"][0]["result"], "failed")
                self.assertTrue(report["complete"])
                self.assertFalse(report["deployment_authority"])
                self.assertNotIn("PRIVATE_SENTINEL", json.dumps(report["build_source_bindings"]))

    def test_source_binding_commit_and_ref_diagnostics_preserve_valid_sibling(self):
        for field, code, sibling in (("sourceVersion", "build.source_commit_sha", "source_commit_sha"),
                                     ("sourceBranch", "build.source_ref_sha256", "source_ref_sha256")):
            invalid = (["A" * 40, "a" * 39, "a" * 41, "a" * 40 + "\n", "ａ" * 40]
                       if field == "sourceVersion" else ["refs/", "heads/feature", " refs/heads/x", "REFS/heads/x",
                           "refs/" + "a" * 252, "refs/" + "é" * 126, "refs/\ud800", "refs/\udfff"])
            invalid += [True, False, 17, 9.0, {}, []]
            for absent, value in [(True, None), (False, None), *[(False, v) for v in invalid]]:
                native = self.source_build()
                if absent:
                    native.pop(field)
                else:
                    native[field] = value
                expected = self.source_expected(bindings_complete=False,
                    binding_missing_fields=[code] if value is None else [],
                    binding_malformed_fields=[] if value is None else [code])
                expected.pop(sibling)
                with self.subTest(field=field, absent=absent, value=value):
                    for listed in (False, True):
                        report, calls = self.inspect([9], listed=[native] if listed else [], metadata={9: native})
                        self.assertEqual(report["build_source_bindings"], [expected])
                        self.assertTrue(report["build_bindings"][0]["bindings_complete"])
                        self.assertEqual(len(calls), 1)
        native = self.source_build(sourceVersion=None)
        native["sourceBranch"] = False
        report, _ = self.inspect([9], metadata={9: native})
        self.assertEqual(report["build_source_bindings"], [{"build_id": 9, "bindings_complete": False,
            "binding_missing_fields": ["build.source_commit_sha"], "binding_malformed_fields": ["build.source_ref_sha256"]}])

    def test_source_binding_ref_exact_utf8_bytes_fixed_hashes_and_control_refusals(self):
        vectors = [("refs/" + "a" * 251, "0e8183f72dcec371b52b86b538425921caa526b0c71ed5f6c08d746c797b25a3"),
                   ("refs/" + "é" * 125 + "a", "d5a44c31e39d691f4b41dce56983cd9d4e1bdacb7f525fa5167a1bc5f6b86463"),
                   ("refs/heads/e\u0301", "536c33e130b4ec89661daf059a9ed6cc81b31b9ea87ea2342e76668263955f25"),
                   ("refs/heads/É", "4ad20fb09d7854b06ec2897a10ec4e533ca9cac0bd9f72e240fd9ce0806a0143"),
                   ("refs/heads/é ", "37680ba3723b4d12e4375f1d81fe1448149925c61829816969fd40bed1b49b4a")]
        for branch, digest in vectors:
            with self.subTest(branch=branch):
                native = self.source_build()
                native["sourceBranch"] = branch
                report, _ = self.inspect([9], metadata={9: native})
                self.assertEqual(report["build_source_bindings"], [self.source_expected(source_ref_sha256=digest)])
                self.assertEqual(report["builds"][0]["sourceBranch"], branch)
        for codepoint in [*range(32), *range(127, 160)]:
            native = self.source_build()
            native["sourceBranch"] = "refs/heads/" + chr(codepoint)
            with self.subTest(codepoint=codepoint):
                report, calls = self.inspect([9], metadata={9: native})
                expected = self.source_expected(bindings_complete=False, binding_malformed_fields=["build.source_ref_sha256"])
                expected.pop("source_ref_sha256")
                self.assertEqual(report["build_source_bindings"], [expected])
                self.assertEqual(len(calls), 1)

    def test_source_binding_attachment_guards_keep_only_observed_identity_diagnostics(self):
        cases = [(self.source_build(id=None), ["build.id"], []),
                 (self.source_build(repository=None), ["build.repository_id"], []),
                 (self.source_build(repository={}), ["build.repository_id"], []),
                 (self.source_build(repository={"id": None}), ["build.repository_id"], [])]
        absent = self.source_build()
        absent.pop("id")
        cases.append((absent, ["build.id"], []))
        cases += [(self.source_build(id=value), [], ["build.id"]) for value in (True, False, 9.0, "9", 0, -1, 10, 2**31)]
        cases += [(self.source_build(repository=value), [], ["build.repository_id"])
                  for value in ([], False, "PRIVATE_SENTINEL", {"id": OTHER_PROJECT_GUID}, {"id": 7}, {"id": PROJECT_GUID + "\n"})]
        for native, missing, malformed in cases:
            native.pop("sourceVersion")
            native["sourceBranch"] = "PRIVATE_SENTINEL"
            with self.subTest(native=native):
                report, calls = self.inspect([9], metadata={9: native})
                self.assertEqual(report["build_source_bindings"], [{"build_id": 9, "bindings_complete": False,
                    "binding_missing_fields": missing, "binding_malformed_fields": malformed}])
                self.assertEqual(len(calls), 1)
                self.assertEqual(report["builds"], [])
        # The selected repository and native repository each contribute causes;
        # malformed wins when the same repository code is also missing.
        for selected, repository, missing, malformed in (
                (None, {"id": PROJECT_GUID}, ["build.repository_id"], []),
                (None, [], [], ["build.repository_id"]),
                ("bad", None, [], ["build.repository_id"]),
                (PROJECT_GUID, None, ["build.repository_id"], []),
                (7, {"id": PROJECT_GUID}, [], ["build.repository_id"])):
            with self.subTest(selected=selected, repository=repository):
                self.assertEqual(az._selected_build_source_binding(self.source_build(repository=repository), 9, selected),
                    {"build_id": 9, "bindings_complete": False,
                     "binding_missing_fields": missing, "binding_malformed_fields": malformed})

    def test_source_binding_unavailable_rejected_acquisition_and_other_families_are_independent(self):
        unavailable = {"build_id": 9, "bindings_complete": False,
            "binding_missing_fields": ["build.id", "build.repository_id", "build.source_commit_sha", "build.source_ref_sha256"],
            "binding_malformed_fields": []}
        for native in (None, [], False, "PRIVATE_SENTINEL", az.AzureError("PRIVATE_SENTINEL")):
            with self.subTest(native=native):
                report, calls = self.inspect([9], metadata={9: native})
                self.assertEqual(report["build_source_bindings"], [unavailable])
                self.assertEqual(len(calls), 1)
                self.assertNotIn("PRIVATE_SENTINEL", json.dumps(report))
        report, _ = self.inspect([9], metadata={9: {"error": "PRIVATE_SENTINEL"}})
        self.assertEqual(report["build_source_bindings"], [{"build_id": 9, "bindings_complete": False,
            "binding_missing_fields": ["build.id", "build.repository_id"], "binding_malformed_fields": []}])
        for field in ("status", "result"):
            native = self.source_build(**{field: "PRIVATE_SENTINEL"})
            with self.subTest(field=field):
                report, calls = self.inspect([9], metadata={9: native})
                self.assertEqual(report["build_source_bindings"], [self.source_expected()])
                self.assertTrue(report["build_bindings"][0]["bindings_complete"])
                self.assertFalse(report["complete"])
                self.assertEqual(report["builds"], [])
                self.assertEqual(report["timelines"], [])
                self.assertEqual(len(calls), 1)
        native = self.source_build(startTime="PRIVATE_SENTINEL", queueTime="1991-01-01T00:59:60+01:00")
        native["definition"]["revision"] = "PRIVATE_SENTINEL"
        report, _ = self.inspect([9], metadata={9: native})
        self.assertEqual(report["build_source_bindings"], [self.source_expected()])
        self.assertFalse(report["build_bindings"][0]["bindings_complete"])
        self.assertTrue(report["complete"])
        self.assertIsNone(report["builds"][0]["startTime"])
        self.assertEqual(report["builds"][0]["queueTime"], native["queueTime"])

    def test_source_binding_duplicates_compare_normalized_source_family_only(self):
        first = self.source_build()
        irrelevant = self.source_build(repository={"id": PROJECT_GUID.lower(), "url": "PRIVATE_SENTINEL"},
                                       queueTime="PRIVATE_SENTINEL", result="failed", name="PRIVATE_SENTINEL")
        irrelevant["definition"] = {"id": 8, "revision": 4}
        report, calls = self.inspect([9, 9], listed=[first, irrelevant])
        self.assertEqual(report["build_source_bindings"], [self.source_expected()])
        self.assertEqual(report["build_bindings"][0]["binding_malformed_fields"], ["build.id"])
        self.assertEqual(len(calls), 1)
        for field, value in (("sourceVersion", "b" * 40), ("sourceBranch", "refs/heads/other"),
                             ("sourceBranch", None), ("repository", {"id": OTHER_PROJECT_GUID})):
            other = deepcopy(first)
            other[field] = value
            for listed in ([first, other], [other, first]):
                with self.subTest(field=field, value=value, listed=listed):
                    report, calls = self.inspect([9], listed=listed)
                    self.assertEqual(report["build_source_bindings"], [{"build_id": 9, "bindings_complete": False,
                        "binding_missing_fields": [], "binding_malformed_fields": ["build.id"]}])
                    self.assertEqual(len(calls), 1)
        first["sourceBranch"], irrelevant["sourceBranch"] = "bad", "different-invalid"
        report, _ = self.inspect([9], listed=[first, irrelevant])
        expected = self.source_expected(bindings_complete=False, binding_malformed_fields=["build.source_ref_sha256"])
        expected.pop("source_ref_sha256")
        self.assertEqual(report["build_source_bindings"], [expected])

    def test_source_binding_selection_privacy_and_exact_byte_cap(self):
        metadata = {number: dict(self.source_build(), id=number) for number in range(1, 34)}
        report, calls = self.inspect([33, *range(32, 0, -1), 9, True, "2", 0, 2**31], metadata=metadata)
        rows = report["build_source_bindings"]
        self.assertEqual(rows, [self.source_expected(build_id=number) for number in range(1, 33)])
        self.assertEqual(len(calls), 64)
        self.assertNotIn(mock.call("GET", "_apis/build/builds/33", fresh=True), calls)
        self.assertIn("selected-build-acquisition-budget-exhausted", report["blockers"])
        def encoded(row):
            return json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")
        self.assertTrue(all(len(encoded(row)) <= 512 for row in rows))
        self.assertLessEqual(sum(len(encoded(row)) for row in rows), 16384)
        native = self.source_build(logs={"url": "PRIVATE_SENTINEL" * 10000}, name="PRIVATE_SENTINEL" * 10000)
        maximum = 2**31 - 1
        native["id"] = maximum
        report, _ = self.inspect([maximum], metadata={maximum: native})
        self.assertEqual(report["build_source_bindings"], [self.source_expected(build_id=maximum)])
        padded = {"build_id": 9, "padding": ""}
        padded["padding"] = "x" * (512 - len(encoded(padded)))
        self.assertEqual(len(encoded(padded)), 512)
        self.assertEqual(az._bounded_build_source_binding(padded), padded)
        padded["padding"] += "x"
        fallback = az._bounded_build_source_binding(padded)
        self.assertEqual(fallback, {"build_id": 9, "bindings_complete": False,
            "binding_missing_fields": ["build.id", "build.repository_id", "build.source_commit_sha", "build.source_ref_sha256"],
            "binding_malformed_fields": []})
        self.assertLessEqual(len(encoded(fallback)), 512)
        for listed_id in (True, 9.0, "9"):
            native = self.source_build()
            report, calls = self.inspect([9], listed=[dict(native, id=listed_id)], metadata={9: native})
            self.assertEqual(report["build_source_bindings"], [self.source_expected()])
            self.assertEqual(len(calls), 2)
        report, calls = self.inspect([False, "9", 0], listed=[self.source_build()])
        self.assertEqual(report["build_source_bindings"], [])
        self.assertEqual(calls, [])
        self.assertIn("selected-build-metadata-unavailable", report["blockers"])
        report, calls = self.inspect([], listed=[self.source_build()])
        self.assertNotIn("build_source_bindings", report)
        self.assertEqual(len(calls), 1)

    def test_missing_feature_build_is_acquired_fresh_before_timeline(self):
        report, calls = self.inspect([9], fresh=False)
        self.assertEqual(calls, [mock.call("GET", "_apis/build/builds/9", fresh=True),
                                 mock.call("GET", "_apis/build/builds/9/timeline", fresh=False)])
        self.assertTrue(report["complete"])
        self.assertEqual(report["builds"], [{"id": 9, "buildNumber": None, "status": "completed",
            "result": "succeeded", "sourceBranch": "refs/heads/feature/selected", "sourceVersion": "a" * 40,
            "queueTime": None, "startTime": None, "finishTime": None}])
        self.assertEqual(report["timelines"], [{"build_id": 9, "records": []}])
        self.assertEqual(report["timeline_scope"], "explicit-build-ids")
        self.assertFalse(report["deployment_authority"])

    def test_listed_rows_keep_order_and_shape_and_fetched_rows_append_in_selected_order(self):
        listed = [self.build(8), self.build(3)]
        report, calls = self.inspect([9, 3, 7, 9], listed=listed)
        self.assertTrue(report["complete"])
        self.assertEqual([row["id"] for row in report["builds"]], [8, 3, 7, 9])
        self.assertEqual(report["builds"][0]["sourceBranch"], listed[0]["sourceBranch"])
        self.assertEqual([call.args[1] for call in calls], ["_apis/build/builds/7", "_apis/build/builds/9",
            "_apis/build/builds/3/timeline", "_apis/build/builds/7/timeline", "_apis/build/builds/9/timeline"])

    def test_failed_build_is_valid_observation_and_survives_timeline_failure(self):
        metadata = {9: self.build(result="failed")}
        report, _ = self.inspect([9], metadata=metadata)
        self.assertTrue(report["complete"])
        self.assertEqual(report["builds"][0]["result"], "failed")
        report, _ = self.inspect([9], metadata=metadata, timeline=az.AzureReadIncomplete("timeline unavailable"))
        self.assertFalse(report["complete"])
        self.assertEqual(report["builds"][0]["result"], "failed")
        self.assertEqual(report["timelines"], [])

    def test_malformed_or_foreign_metadata_suppresses_attachment_and_timeline(self):
        invalid = [None, [], "PRIVATE_SENTINEL", az.AzureError("PRIVATE_SENTINEL"),
                   self.build(repository=None), self.build(repository={}), self.build(repository=[]),
                   self.build(repository={"id": "PRIVATE_SENTINEL"}),
                   self.build(repository={"id": OTHER_PROJECT_GUID}),
                   self.build(id=10), self.build(id=True), self.build(id=9.0),
                   self.build(status="PRIVATE_SENTINEL"), self.build(status=[]),
                   self.build(result="PRIVATE_SENTINEL"), self.build(result={}), self.build(result=None),
                   self.build(sourceVersion=None), self.build(sourceVersion="A" * 40),
                   self.build(sourceVersion="a" * 39), self.build(sourceVersion="a" * 40 + "\n"),
                   self.build(sourceBranch=None), self.build(sourceBranch="refs/"),
                   self.build(sourceBranch="heads/feature/PRIVATE_SENTINEL"),
                   self.build(sourceBranch="refs/heads/PRIVATE_SENTINEL\n"),
                   self.build(sourceBranch="refs/heads/" + "é" * 123),
                   self.build(sourceBranch="refs/heads/\x85PRIVATE_SENTINEL")]
        for key in ("id", "repository", "status", "result", "sourceVersion", "sourceBranch"):
            missing = self.build()
            del missing[key]
            invalid.append(missing)
        for native in invalid:
            with self.subTest(native=native):
                report, calls = self.inspect([9], metadata={9: native})
                self.assertFalse(report["complete"])
                self.assertEqual(report["blockers"], ["selected-build-metadata-unavailable"])
                self.assertEqual(report["builds"], [])
                self.assertEqual(report["timelines"], [])
                self.assertEqual(len(calls), 1)
                self.assertNotIn("PRIVATE_SENTINEL", json.dumps(report))
        for repository_id in ("PRIVATE_SENTINEL", 17):
            with self.subTest(repository_id=repository_id):
                report, calls = self.inspect([9], repository_id=repository_id)
                self.assertEqual(report["blockers"], ["selected-build-metadata-unavailable"])
                self.assertEqual(report["builds"], [])
                self.assertEqual(len(calls), 1)

    def test_explicit_ids_are_strict_deduplicated_sorted_and_capped(self):
        report, calls = self.inspect([33, *range(32, 0, -1), 2, True, "9", 0, -1, 2**31, 1.0, {}, []])
        self.assertFalse(report["complete"])
        self.assertEqual(report["blockers"], ["selected-build-acquisition-budget-exhausted", "selected-build-metadata-unavailable"])
        self.assertEqual([row["id"] for row in report["builds"]], list(range(1, 33)))
        self.assertEqual([row["build_id"] for row in report["timelines"]], list(range(1, 33)))
        self.assertEqual(len(calls), 64)
        self.assertTrue(all(call.kwargs["fresh"] for call in calls))
        self.assertNotIn("_apis/build/builds/33", [call.args[1] for call in calls])
        report, calls = self.inspect(list(range(33, 0, -1)))
        self.assertFalse(report["complete"])
        self.assertEqual(report["blockers"], ["selected-build-acquisition-budget-exhausted"])
        self.assertEqual(len(report["builds"]), 32)
        self.assertEqual(len(report["timelines"]), 32)
        self.assertEqual(len(calls), 64)
        report, calls = self.inspect([2**31 - 1, 2**31 - 1])
        self.assertTrue(report["complete"])
        self.assertEqual(len(calls), 2)

    def test_wholly_invalid_explicit_selection_never_falls_back_to_listed_builds(self):
        report, calls = self.inspect([False, "9", 0], listed=[self.build()])
        self.assertFalse(report["complete"])
        self.assertEqual(report["timeline_scope"], "explicit-build-ids")
        self.assertEqual(calls, [])
        report, calls = self.inspect([], listed=[self.build()])
        self.assertTrue(report["complete"])
        self.assertEqual(report["timeline_scope"], "first-ten-listed-builds")
        self.assertEqual(calls, [mock.call("GET", "_apis/build/builds/9/timeline", fresh=True)])

    def test_listed_id_match_requires_native_integer(self):
        for number in (True, 1.0, "1"):
            with self.subTest(number=number):
                report, calls = self.inspect([1], listed=[self.build(number)])
                self.assertEqual(calls[0], mock.call("GET", "_apis/build/builds/1", fresh=True))
                self.assertEqual(type(report["builds"][-1]["id"]), int)

    def test_source_branch_and_optional_fields_use_utf8_byte_limits(self):
        for suffix, accepted in (("a" * 251, True), ("a" * 252, False), ("é" * 125 + "a", True), ("é" * 126, False)):
            with self.subTest(suffix=suffix):
                report, calls = self.inspect([9], metadata={9: self.build(sourceBranch="refs/" + suffix)})
                self.assertEqual(report["complete"], accepted)
                self.assertEqual(len(calls), 2 if accepted else 1)
        for number, retained in (("é" * 64, True), ("é" * 65, False)):
            with self.subTest(number=number):
                report, _ = self.inspect([9], metadata={9: self.build(buildNumber=number)})
                self.assertTrue(report["complete"])
                self.assertEqual(report["builds"][0]["buildNumber"], number if retained else None)
        for value in ("2026-11-09", "2026-11-09 06:00:00Z", "2026-11-09T06:00:00+00:99",
                      "2026-11-09T06:00:00." + "1" * 45 + "Z", "2026-11-09T06:00:00Z\n", 17):
            with self.subTest(timestamp=value):
                report, _ = self.inspect([9], metadata={9: self.build(queueTime=value)})
                self.assertTrue(report["complete"])
                self.assertIsNone(report["builds"][0]["queueTime"])

    def test_leap_second_timestamps_preserve_exact_strings_in_all_optional_fields(self):
        values = [
            "1990-12-31T23:59:60Z", "1990-12-31T15:59:60-08:00",
            "1991-01-01T00:59:60+01:00", "1990-12-31t23:59:60z",
            "1990-12-31T23:59:60.123456789Z", "1991-01-01t00:59:60.25+01:00",
            "1990-12-31T23:59:60+00:00", "1990-12-31T23:59:60-00:00",
            "1991-01-01T23:58:60+23:59", "1990-12-31T00:00:60-23:59",
            "1972-06-30T23:59:60Z", "2016-12-31T23:59:60Z",
            "2017-01-01T00:59:60+01:00", "1990-12-31T23:59:60." + "1" * 43 + "Z",
        ]
        for value in values:
            for field in ("queueTime", "startTime", "finishTime"):
                with self.subTest(value=value, field=field):
                    report, calls = self.inspect([9], metadata={9: self.build(**{field: value}, private="PRIVATE_SENTINEL")})
                    self.assertTrue(report["complete"])
                    self.assertEqual(report["builds"][0][field], value)
                    self.assertEqual(len(calls), 2)
                    self.assertFalse(report["deployment_authority"])
                    self.assertNotIn("PRIVATE_SENTINEL", json.dumps(report))
                    encoded = json.dumps(report["builds"][0], sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")
                    self.assertLessEqual(len(encoded), 2048)

    def test_all_frozen_published_insertion_dates_are_observable(self):
        dates = (
            "1972-06-30", "1972-12-31", "1973-12-31", "1974-12-31", "1975-12-31",
            "1976-12-31", "1977-12-31", "1978-12-31", "1979-12-31", "1981-06-30",
            "1982-06-30", "1983-06-30", "1985-06-30", "1987-12-31", "1989-12-31",
            "1990-12-31", "1992-06-30", "1993-06-30", "1994-06-30", "1995-12-31",
            "1997-06-30", "1998-12-31", "2005-12-31", "2008-12-31", "2012-06-30",
            "2015-06-30", "2016-12-31",
        )
        for day in dates:
            with self.subTest(day=day):
                value = day + "T23:59:60Z"
                fields = dict.fromkeys(("queueTime", "startTime", "finishTime"), value)
                report, _ = self.inspect([9], metadata={9: self.build(**fields)})
                self.assertTrue(report["complete"])
                for field in fields:
                    self.assertEqual(report["builds"][0][field], value)

    def test_invalid_leap_second_timestamps_become_null_without_losing_metadata(self):
        values = [
            "1990-12-31T23:59:61Z", "1990-12-31T23:59:99Z",
            "1990-13-31T23:59:60Z", "1990-12-32T23:59:60Z", "1990-02-29T23:59:60Z",
            "1990-12-31T24:59:60Z", "1990-12-31T23:60:60Z",
            "1990-12-31T23:59:60+24:00", "1990-12-31T23:59:60+00:60",
            "1990-12-31T23:59:60+0000", "1990-12-31T23:59:60",
            "1990-12-31T23:58:60Z", "1990-12-31T22:59:60Z",
            "1990-12-31T23:59:60+01:00", "1991-01-01T00:59:60-01:00",
            "1990-12-30T23:59:60Z", "1971-12-31T23:59:60Z", "2026-06-30T23:59:60Z",
            "2028-12-31T23:59:60Z", "0001-01-01T00:00:60+23:59", "9999-12-31T23:59:60-23:59",
            "1990-12-31T23:59:60.Z", "1990-12-31T23:59:60,5Z",
            "1990-12-31T23:59:60." + "1" * 44 + "Z", "1990-12-31T23:59:60Z\n",
            "1990-12-31T23:59:60ZPRIVATE_SENTINEL", "1990-12-31T23:59:６０Z", None, 60,
        ]
        for value in values:
            for field in ("queueTime", "startTime", "finishTime"):
                with self.subTest(value=value, field=field):
                    report, calls = self.inspect([9], metadata={9: self.build(**{field: value})})
                    self.assertTrue(report["complete"])
                    self.assertEqual(report["builds"][0]["id"], 9)
                    self.assertIsNone(report["builds"][0][field])
                    self.assertEqual(len(calls), 2)
                    self.assertNotIn("PRIVATE_SENTINEL", json.dumps(report))

    def test_optional_fields_are_sanitized_without_copying_private_metadata(self):
        for value in ("PRIVATE_SENTINEL\n", "PRIVATE_SENTINEL" * 10, {"private": "PRIVATE_SENTINEL"}, "\ud800"):
            with self.subTest(value=value):
                native = self.build(buildNumber=value, queueTime="PRIVATE_SENTINEL", startTime="2026-01-01T00:00:00",
                    finishTime="2026-02-30T00:00:00Z", private="PRIVATE_SENTINEL",
                    definition={"private": "PRIVATE_SENTINEL"})
                report, _ = self.inspect([9], metadata={9: native})
                self.assertTrue(report["complete"])
                self.assertNotIn("PRIVATE_SENTINEL", json.dumps(report))
                self.assertIsNone(report["builds"][0]["buildNumber"])
                for key in ("queueTime", "startTime", "finishTime"):
                    self.assertIsNone(report["builds"][0][key])
        native = self.build(buildNumber="é" * 64, queueTime="2026-11-09T06:00:00Z",
            startTime="2026-11-09T01:00:00.1234567-05:00", finishTime="2026-11-09t06:01:00z")
        report, _ = self.inspect([9], metadata={9: native})
        for key in ("buildNumber", "queueTime", "startTime", "finishTime"):
            self.assertEqual(report["builds"][0][key], native[key])
        encoded = json.dumps(report["builds"][0], sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")
        self.assertLessEqual(len(encoded), 2048)

class ConsolidatedReaderTests(unittest.TestCase):
    """Real reader + fake transport: native evidence is never a public fixture."""
    def build(self, number=9, **changes):
        return {"id": number, "repository": {"id": PROJECT_GUID.upper()},
                "definition": {"id": 7, "revision": 3}, "sourceVersion": "a" * 40,
                "sourceBranch": "refs/heads/PRIVATE_SENTINEL/é", "status": "completed", "result": "failed",
                "queueTime": "2026-11-09T15:00:00Z", "startTime": "2026-11-09T15:01:00Z",
                "finishTime": "2026-11-09T15:02:00Z", **changes}

    def pr(self, **changes):
        return {"pullRequestId": 4, "status": "active", "isDraft": False,
                "sourceRefName": "refs/heads/PRIVATE_SENTINEL/é", "targetRefName": "refs/heads/develop",
                "lastMergeSourceCommit": {"commitId": "a" * 40}, "lastMergeTargetCommit": {"commitId": "b" * 40},
                **changes}

    def records(self):
        return [{"id": self.guid(1), "type": "Stage", "state": "completed", "result": "skipped", "identifier": "stage"},
                {"id": self.guid(2), "parentId": self.guid(1), "type": "Job", "state": "completed", "result": "failed", "identifier": "job", "attempt": 2},
                {"id": self.guid(3), "parentId": self.guid(2), "type": "Task", "state": "inProgress", "result": None}]

    @staticmethod
    def guid(number):
        return "00000000-0000-0000-0000-%012x" % number

    def observe(self, *, ids=(9,), listed=(), metadata=None, records=None, prs=None,
                repository=None, configured="Website", incomplete=()):
        client = types.SimpleNamespace(clock=Clock(), organization="Instablinds", project="Instablinds")
        repository = {"id": PROJECT_GUID, "project": {"id": OTHER_PROJECT_GUID}} if repository is None else repository
        def request(method, path, **kwargs):
            self.assertEqual(method, "GET")
            if path.startswith("_apis/git/repositories/"):
                return deepcopy(repository)
            if path.endswith("/timeline"):
                value = self.records() if records is None else records
                if isinstance(value, Exception):
                    raise value
                return deepcopy(value if isinstance(value, dict) else {"records": value})
            number = int(path.rsplit("/", 1)[-1])
            value = self.build(number) if metadata is None else metadata[number]
            if isinstance(value, Exception):
                raise value
            return deepcopy(value)
        def paged(path, **kwargs):
            if path.endswith("/refs"):
                values, family = [{"name": "refs/heads/develop", "objectId": "b" * 40}], "refs"
            elif path.endswith("/pullrequests"):
                values, family = [self.pr()] if prs is None else prs, "prs"
            elif path == "_apis/build/builds":
                values, family = list(listed), "builds"
            else:
                values, family = [], "policies"
            return az.ReadCollection(items=deepcopy(values), complete=family not in incomplete)
        client.request = mock.Mock(side_effect=request)
        client.paged = mock.Mock(side_effect=paged)
        result = az.AzureBoardsProvider(client).repository_evidence(configured, build_ids=ids)
        return result, client

    def test_complete_native_observation_retains_failed_skipped_and_running_states(self):
        report, client = self.observe()
        self.assertTrue(report["complete"])
        self.assertTrue(report["binding_coverage_complete"])
        self.assertTrue(report["bindings_complete"])
        self.assertEqual(report["build_time_bindings"][0], {"build_id": 9, "status": "completed", "result": "failed",
            "queue_time": "2026-11-09T15:00:00Z", "start_time": "2026-11-09T15:01:00Z", "finish_time": "2026-11-09T15:02:00Z",
            "bindings_complete": True, "binding_missing_fields": [], "binding_malformed_fields": []})
        timeline = report["timeline_bindings"][0]
        self.assertTrue(timeline["bindings_complete"])
        self.assertEqual([r.get("result") for r in timeline["records"]], ["skipped", "failed", None])
        self.assertEqual([r.get("state") for r in timeline["records"]], ["completed", "completed", "inProgress"])
        self.assertFalse(report["deployment_authority"])
        self.assertEqual([c.args[1] for c in client.request.call_args_list], ["_apis/git/repositories/Website", "_apis/build/builds/9", "_apis/build/builds/9/timeline"])
        self.assertFalse(any("definition" in c.args[0] for c in client.paged.call_args_list))
        self.assertEqual(report["budget"]["reader_bytes"], az._repository_binding_size(report))
        self.assertIsNone(report["budget"]["public_bytes"])
        for key in ("observation", "pull_requests", "builds", "timelines"):
            self.assertEqual(report["binding_coverage"][key], {"returned_count": 1, "projected_count": 1,
                "bound_count": 1, "malformed_count": 0, "omitted_count": 0, "upstream_complete": True,
                "count_capped": False, "byte_capped": False})

    def test_build_time_requiredness_and_optional_native_invalidity(self):
        for state in az._BUILD_STATUSES:
            for result in (None, "none", "succeeded", "failed", "canceled"):
                native = self.build(status=state, result=result, startTime=None, finishTime=None)
                row = az._build_time_binding(native, 9, PROJECT_GUID)
                expected = []
                if state in ("completed", "inProgress", "cancelling"):
                    expected.append("build.start_time")
                if state == "completed":
                    expected.append("build.finish_time")
                    if result in (None, "none"):
                        expected.append("build.result")
                with self.subTest(state=state, result=result):
                    self.assertEqual(row["binding_missing_fields"], sorted(expected))
                    self.assertEqual(row["bindings_complete"], not expected)
                    if state != "completed":
                        self.assertEqual(row["result"], result)
        for key in ("queueTime", "startTime", "finishTime"):
            for value in (True, 1, [], {}, "PRIVATE_SENTINEL", "2026-02-30T00:00:00Z", "2028-12-31T23:59:60Z", "x" * 65):
                native = self.build(status="notStarted", **{key: value})
                report, _ = self.observe(metadata={9: native})
                row = report["build_time_bindings"][0]
                with self.subTest(key=key, value=value):
                    code = {"queueTime": "queue_time", "startTime": "start_time", "finishTime": "finish_time"}[key]
                    self.assertEqual(row["binding_malformed_fields"], ["build." + code])
                    self.assertNotIn(code, row)
                    self.assertFalse(report["bindings_complete"])
                    self.assertNotIn("PRIVATE_SENTINEL", json.dumps(row))
        native = self.build(queueTime="1991-01-01T00:59:60+01:00")
        report, _ = self.observe(metadata={9: native})
        self.assertEqual(report["build_time_bindings"][0]["queue_time"], native["queueTime"])
        self.assertTrue(report["build_time_bindings"][0]["bindings_complete"])
        for state in (None, [], {}, "PRIVATE_SENTINEL"):
            row = az._build_time_binding(self.build(status=state, startTime=None, finishTime=None), 9, PROJECT_GUID)
            self.assertEqual(row["binding_missing_fields"], ["build.status"] if state is None else [])
            self.assertEqual(row["binding_malformed_fields"], [] if state is None else ["build.status"])

    def test_native_time_precedes_fetched_legacy_sanitization(self):
        native = self.build(status="notStarted", startTime="PRIVATE_SENTINEL", finishTime=None)
        report, _ = self.observe(metadata={9: native})
        self.assertIsNone(report["builds"][0]["startTime"])
        self.assertEqual(report["build_time_bindings"][0]["binding_malformed_fields"], ["build.start_time"])
        self.assertTrue(report["complete"])
        self.assertTrue(report["binding_coverage_complete"])
        self.assertFalse(report["bindings_complete"])

    def test_pr_native_requiredness_digests_and_malformed_optional(self):
        digest = "d8f2d99dcb8151ef9a5d5aaa0b7445a4507d2cd979934c9dd2784a37fea6bf54"
        for state in ("active", "abandoned", "completed"):
            for draft in (False, True):
                report, _ = self.observe(prs=[self.pr(status=state, isDraft=draft)])
                row = report["pr_bindings"][0]
                self.assertEqual(row["source_ref_sha256"], digest)
                self.assertEqual(row["binding_missing_fields"], ["pr.merge_commit_sha"] if state == "completed" else [])
                self.assertEqual(row["bindings_complete"], state != "completed")
        for key, value, code in (("lastMergeCommit", [], "pr.merge_commit_sha"),
                                 ("lastMergeCommit", {"commitId": "PRIVATE_SENTINEL"}, "pr.merge_commit_sha"),
                                 ("lastMergeSourceCommit", {"commitId": True}, "pr.source_commit_sha"),
                                 ("sourceRefName", "refs/heads/\x00", "pr.source_ref_sha256"),
                                 ("targetRefName", "refs/", "pr.target_ref_sha256")):
            report, _ = self.observe(prs=[self.pr(**{key: value})])
            row = report["pr_bindings"][0]
            self.assertEqual(row["binding_malformed_fields"], [code])
            self.assertFalse(row["bindings_complete"])
            self.assertNotIn("PRIVATE_SENTINEL", json.dumps(row))
        for value in (None, False, 0, -1, 1.0, "4", 2147483648):
            report, _ = self.observe(prs=[self.pr(pullRequestId=value)])
            self.assertEqual(report["pr_bindings"], [])
            self.assertEqual(report["binding_coverage"]["pull_requests"]["malformed_count"], 1)
            self.assertFalse(report["binding_coverage_complete"])

    def test_duplicate_family_conflicts_never_choose_a_winner(self):
        first = self.pr()
        other = self.pr(lastMergeSourceCommit={"commitId": "c" * 40})
        for values in ([first, other], [other, first]):
            report, _ = self.observe(prs=values)
            self.assertEqual(report["pr_bindings"], [{"pull_request_id": 4, "bindings_complete": False,
                "binding_missing_fields": [], "binding_malformed_fields": ["pr.id"]}])
            self.assertEqual(len(report["pull_requests"]), 2)
            self.assertFalse(report["binding_coverage_complete"])
            self.assertEqual(report["binding_coverage"]["pull_requests"]["malformed_count"], 2)
        report, _ = self.observe(prs=[first, deepcopy(first)])
        self.assertEqual(len(report["pr_bindings"]), 1)
        first, second = self.build(), self.build(startTime="2026-11-09T15:01:01Z")
        report, client = self.observe(listed=[first, second])
        self.assertEqual(report["build_time_bindings"], [{"build_id": 9, "bindings_complete": False,
            "binding_missing_fields": [], "binding_malformed_fields": ["build.id"]}])
        self.assertTrue(report["build_source_bindings"][0]["bindings_complete"])
        self.assertTrue(report["build_bindings"][0]["bindings_complete"])
        self.assertEqual(len(client.request.call_args_list), 2)

    def test_default_transport_uses_only_actual_first_ten_selected_rows(self):
        builds = [self.build(i) for i in range(1, 12)]
        report, client = self.observe(ids=[], listed=builds)
        self.assertEqual(report["requested_build_ids"], [])
        self.assertEqual(report["timeline_scope"], "first-ten-listed-builds")
        for key in ("build_bindings", "build_source_bindings", "build_time_bindings"):
            self.assertNotIn(key, report)
        self.assertEqual(set(report["default_build_bindings"]), {"repository_definition", "source", "time"})
        for rows in report["default_build_bindings"].values():
            self.assertEqual([r["build_id"] for r in rows], list(range(1, 11)))
        self.assertEqual(len(client.request.call_args_list), 11)
        report, _ = self.observe(ids=[], listed=[self.build(id=True), self.build(id=0), self.build(9)])
        for rows in report["default_build_bindings"].values():
            self.assertEqual([r["build_id"] for r in rows], [9])
        self.assertFalse(report["binding_coverage_complete"])
        self.assertIn("observation.request_ids", report["binding_malformed_fields"])
        # A duplicate outside the selected first ten cannot change their facts.
        builds = [self.build(i) for i in range(1, 11)] + [self.build(1, sourceVersion="b" * 40)]
        report, _ = self.observe(ids=[], listed=builds)
        self.assertEqual(report["default_build_bindings"]["source"][0]["source_commit_sha"], "a" * 40)

    def test_request_repository_and_unknown_collection_coverage(self):
        report, client = self.observe(ids=[False, "9", 0, -1, 1.0, 2147483648])
        self.assertEqual(report["request_ids_invalid_count"], 6)
        self.assertEqual(report["requested_build_ids"], [])
        self.assertEqual(report["timeline_scope"], "explicit-build-ids")
        self.assertEqual(len(client.request.call_args_list), 1)
        self.assertNotIn("default_build_bindings", report)
        report, _ = self.observe(configured=OTHER_PROJECT_GUID)
        self.assertIn("observation.repository_id", report["binding_malformed_fields"])
        self.assertEqual(report["repository_id"], PROJECT_GUID)
        self.assertFalse(report["bindings_complete"])
        for family in ("refs", "prs", "policies", "builds"):
            report, _ = self.observe(incomplete=(family,))
            self.assertFalse(report["binding_coverage_complete"])
            self.assertFalse(report["bindings_complete"])

    def test_full_native_relation_digest_facts_and_canonical_identities(self):
        records = self.records()
        records[0]["id"] = records[0]["id"].upper()
        report, _ = self.observe(records=records)
        container = report["timeline_bindings"][0]
        index = [{"native_position": i, "id": record["id"].lower(), "type": record["type"],
                  "parent_id": record.get("parentId")} for i, record in enumerate(records)]
        import hashlib
        digest = hashlib.sha256(json.dumps(index, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()).hexdigest()
        self.assertEqual(container["native_parent_index_sha256"], digest)
        self.assertEqual(len(container["parent_validation_facts"]), 2)
        for fact, child, parent, kind in zip(container["parent_validation_facts"], (2, 3), (1, 2), ("Stage", "Job")):
            self.assertEqual(fact, {"schema_version": "atlas-tools.azure-parent-validation.v1", "build_id": 9,
                "child_id": self.guid(child), "parent_id": self.guid(parent), "parent_type": kind,
                "child_occurrences": 1, "parent_occurrences": 1, "resolution": "resolved", "acyclic": True,
                "index_sha256": digest, "native_record_count": 3})
            self.assertLessEqual(len(az._compact_binding_bytes(fact)), 512)
        private = json.dumps(container)
        for sentinel in ("PRIVATE_SENTINEL", "identifier\"", "startTime", "errorCount", "log"):
            self.assertNotIn(sentinel, private)

    def test_native_parent_missing_duplicate_type_and_full_cycle_failures(self):
        for mutation, resolution, parent_count, missing in (
                (lambda r: r.pop(0), "missing", 0, True),
                (lambda r: r.append(deepcopy(r[0])), "ambiguous", 2, False),
                (lambda r: r[0].update(type="Task"), "invalid", 1, False),
                (lambda r: r[0].update(parentId=self.guid(2)), "invalid", 1, False),
                (lambda r: r[1].update(parentId=self.guid(2)), "invalid", 1, False)):
            records = self.records()
            mutation(records)
            report, _ = self.observe(records=records)
            container = report["timeline_bindings"][0]
            job = next(r for r in container["records"] if r.get("id") == self.guid(2))
            fact = next(f for f in container["parent_validation_facts"] if f["child_id"] == self.guid(2))
            self.assertEqual(fact["resolution"], resolution)
            self.assertEqual(fact["parent_occurrences"], parent_count)
            self.assertFalse(fact["acyclic"])
            self.assertFalse(job["bindings_complete"])
            self.assertIn("timeline.parent_resolution", job["binding_missing_fields" if missing else "binding_malformed_fields"])
        # The entire chain is inspected, including a cycle well beyond the cap.
        records = [{"id": self.guid(1), "parentId": self.guid(500), "type": "Job", "state": "pending", "identifier": "child"}]
        records += [{"id": self.guid(i), "parentId": self.guid(i+1), "type": "Phase", "state": "pending"} for i in range(500, 1600)]
        records.append({"id": self.guid(1600), "parentId": self.guid(1500), "type": "Phase", "state": "pending"})
        typed, _ = az._typed_timeline({"records": records}, 9, True)
        self.assertEqual(typed["returned_record_count"], 1102)
        self.assertFalse(typed["records"][0]["bindings_complete"])
        self.assertEqual(typed["parent_validation_facts"][0]["resolution"], "invalid")
        self.assertFalse(typed["parent_validation_facts"][0]["acyclic"])

    def test_typed_diagnostics_survive_legacy_timeline_rejection(self):
        for key, value, code in (("state", "PRIVATE_SENTINEL", "timeline.state"),
                                 ("result", "PRIVATE_SENTINEL", "timeline.result"),
                                 ("id", [], "timeline.id")):
            records = self.records()
            records[0][key] = value
            report, _ = self.observe(records=records)
            self.assertEqual(report["timelines"], [])
            self.assertEqual(len(report["timeline_bindings"]), 1)
            self.assertFalse(report["complete"])
            self.assertIn(code, report["timeline_bindings"][0]["binding_malformed_fields"])
            self.assertNotIn("PRIVATE_SENTINEL", json.dumps(report["timeline_bindings"]))
        for key, value, code in (("type", "PRIVATE_SENTINEL", "timeline.type"),
                                 ("attempt", True, "timeline.attempt"),
                                 ("identifier", "", "timeline.identifier_sha256"),
                                 ("parentId", "bad", "timeline.parent_id")):
            records = self.records()
            records[0][key] = value
            report, _ = self.observe(records=records)
            container = report["timeline_bindings"][0]
            self.assertIn(code, container["binding_malformed_fields"])
            self.assertFalse(container["bindings_complete"])
            if key == "type":
                self.assertTrue(container["states_recognized"])
                self.assertEqual(set(container["records"][0]), {"id", "bindings_complete", "binding_missing_fields", "binding_malformed_fields"})
        records = self.records()
        records[0].pop("identifier")
        records[0]["name"] = "PRIVATE_SENTINEL"
        report, _ = self.observe(records=records)
        self.assertIn("timeline.identifier_sha256", report["timeline_bindings"][0]["records"][0]["binding_missing_fields"])

    def test_foreign_listed_build_cannot_attach_typed_children_or_facts(self):
        report, client = self.observe(listed=[self.build(repository={"id": OTHER_PROJECT_GUID})])
        self.assertEqual(len(report["timelines"]), 1)  # inherited legacy guard
        self.assertEqual(len(client.request.call_args_list), 2)
        container = report["timeline_bindings"][0]
        self.assertFalse(container["bindings_complete"])
        self.assertEqual(container["parent_validation_facts"], [])
        self.assertTrue(all("timeline.build_id" in r["binding_malformed_fields"] for r in container["records"]))

    def test_record_count_cap_uses_native_order_digest_and_full_state_denominator(self):
        records = [{"id": self.guid(i), "type": "Stage", "identifier": "stage-%d" % i, "state": "completed", "result": "skipped"} for i in range(257, 0, -1)]
        records[0]["state"] = "PRIVATE_SENTINEL"
        typed, positions = az._typed_timeline({"records": records}, 9, True)
        self.assertEqual(typed["record_count"], 257)
        self.assertEqual(typed["returned_record_count"], 257)
        self.assertEqual(typed["projected_record_count"], 256)
        self.assertEqual([r["id"] for r in typed["records"]], [self.guid(i) for i in range(1, 257)])
        self.assertEqual(positions, list(range(256, 0, -1)))
        self.assertFalse(typed["states_recognized"])
        self.assertIn("timeline.state", typed["binding_malformed_fields"])
        report, _ = self.observe(records=records)
        self.assertTrue(report["binding_coverage"]["timelines"]["count_capped"])
        self.assertTrue(report["timeline_bindings"][0]["records_truncated"])
        self.assertEqual(report["timeline_bindings"][0]["record_count"], 257)
        self.assertLessEqual(report["budget"]["reader_bytes"], 98304)
        self.assertFalse(report["binding_coverage_complete"])

    def test_byte_omission_preserves_actual_omitted_parent_fact_and_legacy_pairing(self):
        records = [{"id": self.guid(1), "parentId": self.guid(999), "type": "Job", "identifier": "child", "state": "pending"}]
        records += [{"id": self.guid(i), "type": "Stage", "identifier": "stage-%d" % i, "state": "completed", "result": "skipped"} for i in range(2, 180)]
        records.append({"id": self.guid(999), "type": "Stage", "identifier": "parent", "state": "pending"})
        report, _ = self.observe(records=list(reversed(records)))
        container = report["timeline_bindings"][0]
        self.assertTrue(report["budget"]["aggregate_truncated"])
        self.assertTrue(report["binding_coverage"]["timelines"]["byte_capped"])
        self.assertFalse(report["binding_coverage"]["timelines"]["count_capped"])
        self.assertEqual(container["record_count"], len(records))
        self.assertEqual(container["returned_record_count"], len(records))
        self.assertEqual(container["projected_record_count"], len(container["records"]))
        self.assertNotIn(self.guid(999), [r["id"] for r in container["records"]])
        self.assertTrue(container["records"][0]["bindings_complete"])
        self.assertEqual(container["parent_validation_facts"][0]["parent_id"], self.guid(999))
        self.assertEqual(container["parent_validation_facts"][0]["parent_occurrences"], 1)
        self.assertEqual(container["parent_validation_facts"][0]["resolution"], "resolved")
        self.assertEqual(container["parent_validation_facts"][0]["native_record_count"], len(records))
        self.assertFalse(container["bindings_complete"])
        self.assertFalse(report["bindings_complete"])
        self.assertEqual({r["id"] for r in report["timelines"][0]["records"]}, {r["id"] for r in container["records"]})
        # Legacy retained native order is preserved while typed GUID order sorts.
        self.assertEqual([r["id"] for r in report["timelines"][0]["records"]], list(reversed([r["id"] for r in container["records"]])))
        self.assertEqual(report["budget"]["reader_bytes"], az._repository_binding_size(report))
        # One more tail record plus its legacy copy would exceed the envelope.
        restored = deepcopy(report)
        next_native = records[len(container["records"])]
        typed, _ = az._typed_timeline({"records": [next_native]}, 9, True)
        restored["timeline_bindings"][0]["records"].append(typed["records"][0])
        restored["timelines"][0]["records"].append({key: next_native.get(key) for key in (
            "id", "parentId", "type", "state", "result", "startTime", "finishTime", "errorCount", "warningCount")})
        restored["timeline_bindings"][0]["projected_record_count"] += 1
        self.assertGreater(az._reader_byte_count(restored), 98304)

    def test_count_and_byte_fitting_retains_deterministic_32_by_256_prefix(self):
        records = [{"id": self.guid(i), "type": "Stage", "identifier": "x" * 256,
                    "state": "completed", "result": "skipped"} for i in range(1, 257)]
        report, client = self.observe(ids=list(range(1, 33)), records=records)
        self.assertEqual(len(client.request.call_args_list), 65)
        self.assertEqual(report["requested_build_ids"], list(range(1, 33)))
        self.assertTrue(report["budget"]["aggregate_truncated"])
        self.assertFalse(report["binding_coverage_complete"])
        self.assertFalse(report["bindings_complete"])
        self.assertEqual(report["binding_coverage"]["timelines"]["returned_count"], 32)
        self.assertEqual(report["binding_coverage"]["timelines"]["projected_count"], 32)
        self.assertFalse(report["binding_coverage"]["timelines"]["count_capped"])
        self.assertTrue(report["binding_coverage"]["timelines"]["byte_capped"])
        self.assertEqual(report["budget"]["reader_bytes"], az._repository_binding_size(report))
        self.assertLessEqual(report["budget"]["reader_bytes"], 98304)
        retained = [(row["build_id"], record["id"]) for row in report["timeline_bindings"] for record in row["records"]]
        native = [(number, self.guid(i)) for number in range(1, 33) for i in range(1, 257)]
        self.assertEqual(retained, native[:len(retained)])
        for typed, legacy in zip(report["timeline_bindings"], report["timelines"]):
            self.assertEqual(typed["record_count"], 256)
            self.assertEqual(typed["returned_record_count"], 256)
            self.assertEqual(len(typed["records"]), len(legacy["records"]))

    def test_native_invalid_build_identity_and_failed_repository_are_explicit(self):
        for number in (True, 1.0, "9", 0, -1, 2147483648):
            report, _ = self.observe(ids=[], listed=[self.build(id=number)])
            self.assertEqual(report["timeline_bindings"], [])
            self.assertTrue(all(not rows for rows in report["default_build_bindings"].values()))
            self.assertFalse(report["binding_coverage_complete"])
        report, _ = self.observe(metadata={9: self.build(10)})
        self.assertEqual(report["binding_coverage"]["builds"]["malformed_count"], 1)
        self.assertFalse(report["binding_coverage_complete"])
        for repository, malformed in (({}, False), ({"id": None}, False), ({"id": 0}, True), ({"id": False}, True), ({"id": ""}, True)):
            report, client = self.observe(repository=repository)
            self.assertFalse(report["observed"])
            self.assertEqual(len(client.request.call_args_list), 1)
            self.assertFalse(report["budget"]["report_omitted"])
            self.assertIn("observation.repository_id", report["binding_malformed_fields" if malformed else "binding_missing_fields"])
            self.assertEqual(report["binding_missing_fields"], sorted(report["binding_missing_fields"]))

    def test_missing_required_data_is_distinct_from_malformed_object_count(self):
        native = self.build(queueTime=None, definition={"id": 7})
        report, _ = self.observe(metadata={9: native})
        self.assertFalse(report["bindings_complete"])
        self.assertTrue(report["binding_coverage_complete"])
        self.assertEqual(report["binding_coverage"]["builds"]["malformed_count"], 0)
        self.assertIn("build.queue_time", report["binding_missing_fields"])
        self.assertIn("build.definition_revision", report["binding_missing_fields"])
        self.assertEqual(report["binding_malformed_fields"], [])

    def test_cached_whole_serialization_matches_standard_pretty_bytes(self):
        frozen = {"z": ["é", "e\u0301", "\n", "\x00", None, True, 1, 1.5], "a": {"id": "a" * 40}}
        encoder = az._PrivatePrettySerializer([frozen])
        evidence = {"repository_evidence": {"mutable": [frozen, {"native": frozen}], "counter": 0}}
        for counter in (0, 9, 10, 98304):
            evidence["repository_evidence"]["counter"] = counter
            expected = json.dumps(evidence, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
            self.assertEqual(encoder(evidence), expected)
        evidence["repository_evidence"]["mutable"].pop()
        self.assertEqual(encoder(evidence), json.dumps(evidence, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False))
        self.assertEqual(encoder({}), "{}")
        self.assertEqual(encoder([]), "[]")

    def test_parent_facts_consume_aggregate_bytes_and_leave_with_exact_children(self):
        records = [{"id": self.guid(i), "parentId": self.guid(999), "type": "Job", "identifier": "job-%d" % i,
                    "state": "pending"} for i in range(1, 181)]
        records.append({"id": self.guid(999), "type": "Stage", "identifier": "root", "state": "pending"})
        report, _ = self.observe(records=records)
        container = report["timeline_bindings"][0]
        self.assertEqual(container["returned_record_count"], 181)
        self.assertLess(len(container["records"]), 181)
        self.assertEqual([f["child_id"] for f in container["parent_validation_facts"]], [r["id"] for r in container["records"]])
        self.assertTrue(all(r["bindings_complete"] for r in container["records"]))
        self.assertTrue(all(f["resolution"] == "resolved" and f["acyclic"] and f["native_record_count"] == 181
                            and f["index_sha256"] == container["native_parent_index_sha256"]
                            and len(az._compact_binding_bytes(f)) <= 512 for f in container["parent_validation_facts"]))
        self.assertEqual(report["budget"]["reader_bytes"], az._repository_binding_size(report))
        self.assertTrue(report["binding_coverage"]["timelines"]["byte_capped"])
        self.assertFalse(report["binding_coverage"]["timelines"]["count_capped"])
        self.assertNotIn(self.guid(999), [r["id"] for r in container["records"]])

    def test_actual_repository_fitting_exact_boundary_then_one_byte_over(self):
        base, _ = self.observe(listed=[self.build(buildNumber="")], records=[], prs=[])
        size = base["budget"]["reader_bytes"]
        padding = "x" * (98304 - size - (len(str(98304)) - len(str(size))))
        exact, _ = self.observe(listed=[self.build(buildNumber=padding)], records=[], prs=[])
        self.assertEqual(exact["budget"]["reader_bytes"], 98304)
        self.assertEqual(az._repository_binding_size(exact), 98304)
        self.assertFalse(exact["budget"]["aggregate_truncated"])
        self.assertTrue(exact["bindings_complete"])
        over, _ = self.observe(listed=[self.build(buildNumber=padding + "x")], records=[], prs=[])
        self.assertTrue(over["budget"]["aggregate_truncated"])
        self.assertEqual(over["timeline_bindings"], [])
        self.assertEqual(over["timelines"], [])
        self.assertEqual(over["builds"][0]["buildNumber"], padding + "x")
        self.assertLessEqual(over["budget"]["reader_bytes"], 98304)
        self.assertFalse(over["bindings_complete"])

    def test_whole_parent_omission_removes_binding_sidecars_and_preserves_counts(self):
        for ids in ((9,), ()):
            report, _ = self.observe(ids=ids, listed=[self.build(buildNumber="x" * 100000)])
            self.assertEqual(report["builds"], [])
            self.assertEqual(report["pull_requests"], [])
            self.assertEqual(report["pr_bindings"], [])
            self.assertEqual(report["timeline_bindings"], [])
            self.assertEqual(report["timelines"], [])
            if ids:
                for key in ("build_bindings", "build_source_bindings", "build_time_bindings"):
                    self.assertEqual(report[key], [])
                for suffix in ("metadata", "timeline", "repository", "definition", "source"):
                    self.assertEqual(report["selected_builds_without_" + suffix], [9])
            else:
                self.assertTrue(all(not rows for rows in report["default_build_bindings"].values()))
            for key in ("builds", "pull_requests", "timelines"):
                coverage = report["binding_coverage"][key]
                self.assertEqual(coverage["returned_count"], 1)
                self.assertEqual(coverage["projected_count"], 0)
                self.assertEqual(coverage["omitted_count"], 1)
                self.assertTrue(coverage["byte_capped"])
                self.assertEqual(coverage["malformed_count"], 0)

    def test_rejected_legacy_metadata_does_not_erase_independent_valid_bindings(self):
        report, _ = self.observe(metadata={9: self.build(sourceVersion="bad")})
        self.assertEqual(report["selected_builds_without_metadata"], [9])
        self.assertEqual(report["selected_builds_without_source"], [9])
        self.assertEqual(report["selected_builds_without_repository"], [])
        self.assertEqual(report["selected_builds_without_definition"], [])
        self.assertTrue(report["build_bindings"][0]["bindings_complete"])
        self.assertFalse(report["bindings_complete"])
        for changes in ({"status": "abandoned"}, {"isDraft": True}):
            report, _ = self.observe(prs=[self.pr(), self.pr(**changes)])
            self.assertEqual(report["pr_bindings"], [{"pull_request_id": 4, "bindings_complete": False,
                "binding_missing_fields": [], "binding_malformed_fields": ["pr.id"]}])

    def test_exact_revised_timeline_fixture_and_native_index_normalization(self):
        records = self.records()
        records[0].update(identifier="PRIVATE_SENTINEL.Stage", attempt=1, result="succeeded")
        records[1].update(identifier="PRIVATE_SENTINEL.Job", result="succeeded")
        records[2].update(state="completed", result="succeeded")
        report, _ = self.observe(records=records)
        container = report["timeline_bindings"][0]
        self.assertEqual(set(container), {"build_id", "record_count", "returned_record_count", "projected_record_count",
            "states_recognized", "records_truncated", "records", "bindings_complete", "binding_missing_fields",
            "binding_malformed_fields", "native_parent_index_sha256", "parent_validation_facts"})
        self.assertEqual(container["native_parent_index_sha256"], "af166f0eccdde323e2b70248277ed83b59f178ffea68c8cb9d144fee25f69a4a")
        self.assertEqual(container["records"][0]["identifier_sha256"], "6b27dff2c21aa7b1a0e478b4781ed8be168c4d6dc2ef5510a2af40d2c5244a68")
        self.assertEqual(container["records"][1]["identifier_sha256"], "670827e831da41b79957612af487e0b3569de26a3083a2f7dbcffc9ac36ddcec")
        raw = [{"id": "bad", "type": [], "parentId": False, "state": "pending"}, None]
        container, _ = az._typed_timeline({"records": raw}, 9, True)
        import hashlib
        normalized = [{"native_position": i, "id": None, "type": None, "parent_id": None} for i in range(2)]
        digest = hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()).hexdigest()
        self.assertEqual(container["native_parent_index_sha256"], digest)
        self.assertFalse(container["bindings_complete"])
        self.assertEqual(container["parent_validation_facts"], [])
        self.assertEqual(container["returned_record_count"], 2)
        self.assertIn("timeline.records", container["binding_malformed_fields"])

    def test_duplicate_unknown_type_tail_does_not_remove_another_child_fact(self):
        records = [{"id": self.guid(1), "parentId": self.guid(999), "type": "Job", "identifier": "job", "attempt": 1, "state": "pending"},
                   {"id": self.guid(1), "parentId": self.guid(999), "type": "unknown", "attempt": 2, "state": "pending"},
                   {"id": self.guid(999), "type": "Stage", "identifier": "root", "state": "pending"}]
        saw_single_child = False
        for padding in range(90000, 98001, 100):
            report, _ = self.observe(listed=[self.build(buildNumber="x" * padding)], records=records)
            if not report["timeline_bindings"]:
                continue
            container = report["timeline_bindings"][0]
            expected = [r["id"] for r in container["records"] if "parent_id" in r and "type" in r]
            self.assertEqual([f["child_id"] for f in container["parent_validation_facts"]], expected)
            saw_single_child |= len(container["records"]) == 1 and container["records"][0].get("type") == "Job"
        self.assertTrue(saw_single_child)

    def test_invalid_legacy_default_timeline_response_still_counts_before_projection(self):
        report, _ = self.observe(ids=[], listed=[self.build(2147483648)], records=[])
        self.assertEqual(report["timeline_bindings"], [])
        self.assertEqual(len(report["timelines"]), 1)
        self.assertEqual(report["binding_coverage"]["timelines"], {"returned_count": 1, "projected_count": 1,
            "bound_count": 0, "malformed_count": 1, "omitted_count": 0, "upstream_complete": False,
            "count_capped": False, "byte_capped": False})
        report, _ = self.observe(ids=[], listed=[self.build(2147483648)], records={"records": None})
        self.assertEqual(report["binding_coverage"]["timelines"]["returned_count"], 1)
        self.assertEqual(report["binding_coverage"]["timelines"]["projected_count"], 0)
        self.assertEqual(report["binding_coverage"]["timelines"]["omitted_count"], 1)
        self.assertEqual(report["binding_coverage"]["timelines"]["malformed_count"], 1)

    def test_whole_timeline_tail_order_includes_untyped_legacy_default_container(self):
        listed = [self.build(buildNumber=""), self.build(2147483648)]
        baseline, _ = self.observe(ids=[], listed=listed, records=[], prs=[])
        size = baseline["budget"]["reader_bytes"]
        padding = "x" * (98305 - size - (len(str(98305)) - len(str(size))))
        listed[0]["buildNumber"] = padding
        report, _ = self.observe(ids=[], listed=listed, records=[], prs=[])
        self.assertTrue(report["budget"]["aggregate_truncated"])
        self.assertEqual([row["build_id"] for row in report["timeline_bindings"]], [9])
        self.assertEqual([row["build_id"] for row in report["timelines"]], [9])
        self.assertEqual(report["binding_coverage"]["timelines"]["returned_count"], 2)
        self.assertEqual(report["binding_coverage"]["timelines"]["projected_count"], 1)
        self.assertEqual(report["binding_coverage"]["timelines"]["omitted_count"], 1)

    def test_exact_private_byte_boundary_and_fixed_fallback(self):
        evidence = {"budget": {"reader_bytes": 0}, "padding": ""}
        size = az._reader_byte_count(evidence)
        evidence["padding"] = "x" * (98304 - size - (len(str(98304)) - len(str(size))))
        self.assertEqual(az._reader_byte_count(evidence), 98304)
        evidence["padding"] += "x"
        self.assertEqual(az._reader_byte_count(evidence), 98305)
        fallback = az._minimal_repository_evidence()
        self.assertIsNone(fallback["budget"]["reader_bytes"])
        self.assertIsNone(fallback["reported_complete"])
        self.assertFalse(fallback["bindings_complete"])
        self.assertTrue(fallback["budget"]["report_omitted"])
        self.assertLess(az._repository_binding_size(fallback), 98304)
        for family in fallback["binding_coverage"].values():
            self.assertIsNone(family["returned_count"])
            self.assertIsNone(family["omitted_count"])
        # Non-finite legacy native values cannot leak through allow_nan=False.
        report, _ = self.observe(listed=[self.build(buildNumber=float("nan"))])
        self.assertEqual(report, fallback)


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
