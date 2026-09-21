from __future__ import annotations

import copy
import importlib.util
import json
import os
import pwd
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


ev = load_module("interpretation_integrity_eval", "scripts/interpretation_integrity_eval.py")
sys.modules["interpretation_integrity_eval"] = ev
intake = load_module("interpretation_integrity_private_intake", "scripts/interpretation_integrity_private_intake.py")

EVAL = ROOT / "evals/interpretation_integrity"
FIX = ROOT / "tests/fixtures/interpretation_integrity"
SOURCE_SHAPES = ev.load_json(FIX / "source_log_shapes.v0.json")


@pytest.fixture(autouse=True)
def synthetic_identity_home(tmp_path, monkeypatch):
    # Tests never enter the real identity's sessions or credential directories.
    monkeypatch.setattr(pwd, "getpwuid", lambda _uid: SimpleNamespace(pw_dir=str(tmp_path)))
    monkeypatch.setitem(sys.modules, "interpretation_integrity_private_intake", intake)


def meta(root="root-synthetic", source="cli"):
    return {"timestamp": "synthetic-time", "type": "session_meta", "payload": {"source": source, "id": root}}


def response(turn="turn-a", message_id="message-a", message="Synthetic direct input.", **payload_changes):
    payload = {
        "type": "message",
        "role": "user",
        "content": [{"type": "input_text", "text": message}],
        "id": message_id,
        "internal_chat_message_metadata_passthrough": {"turn_id": turn},
    }
    payload.update(payload_changes)
    return {"timestamp": "synthetic-time", "type": "response_item", "payload": payload}


def event(message="Synthetic direct input.", *, text_elements=None, **payload_changes):
    payload = {
        "type": "user_message",
        "message": message,
        "text_elements": [] if text_elements is None else text_elements,
        "images": [],
        "local_images": [],
        "audio": [],
        "local_audio": [],
    }
    payload.update(payload_changes)
    return {"timestamp": "synthetic-time", "type": "event_msg", "payload": payload}


def pair(turn="turn-a", message_id="message-a", message="Synthetic direct input.", **event_changes):
    return [response(turn, message_id, message), event(message, **event_changes)]


def encode_jsonl(records) -> bytes:
    return b"".join((json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8") for item in records)


def make_selection(records, selected=None, **changes):
    prefix = encode_jsonl(records)
    root = records[0]["payload"]["id"]
    found_by_key = {}
    for index, record in enumerate(records):
        payload = record.get("payload", {})
        if record.get("type") == "event_msg" and payload.get("type") == "user_message":
            turn, message_id, digest, _ = intake._validate_pair(records[index - 1], record)
            if selected is None or (turn, message_id) in selected:
                item = {"turn_id": turn, "message_id": message_id, "envelope_digest": digest}
                prior = found_by_key.get((turn, message_id))
                if prior is not None and prior != item:
                    raise ValueError("test fixture contains a conflicting repeated identity")
                found_by_key[(turn, message_id)] = item
    document = {
        "schema_version": intake.SELECTION_VERSION,
        "root_session_id": root,
        "source_prefix_length": len(prefix),
        "source_prefix_digest": ev.sha256_bytes(prefix),
        "complete_record_count": len(records),
        "selections": list(found_by_key.values()),
    }
    document.update(changes)
    return document


def selection_for_shape(shape, records, prefix):
    specification = shape.get("selection")
    if not isinstance(specification, dict):
        raise ValueError("executable source shape requires a selection specification")
    mode = specification.get("mode")
    if mode == "paired_indices":
        indices = specification.get("response_indices")
        if not isinstance(indices, list) or not indices:
            raise ValueError("paired_indices requires response indices")
        root = records[0].get("payload", {}).get("id")
        entries = []
        for index in indices:
            if isinstance(index, bool) or not isinstance(index, int) or index < 0 or index + 1 >= len(records):
                raise ValueError("source shape has an invalid response index")
            turn_id, message_id, digest, _ = intake._validate_pair(records[index], records[index + 1])
            entries.append({"turn_id": turn_id, "message_id": message_id, "envelope_digest": digest})
    elif mode == "unmatched":
        root = specification.get("root_session_id")
        entries = [{
            "turn_id": specification.get("turn_id"),
            "message_id": specification.get("message_id"),
            "envelope_digest": "sha256:" + "0" * 64,
        }]
    else:
        raise ValueError("source shape has an unknown selection mode")
    return {
        "schema_version": intake.SELECTION_VERSION,
        "root_session_id": root,
        "source_prefix_length": len(prefix),
        "source_prefix_digest": ev.sha256_bytes(prefix),
        "complete_record_count": len(records),
        "selections": entries,
    }


def execute_source_shape(shape):
    if not isinstance(shape, dict) or not isinstance(shape.get("shape_id"), str):
        raise ValueError("source shape envelope is malformed")
    if shape.get("expected") not in {"accept", "reject"}:
        raise ValueError("source shape expected outcome is malformed")
    has_records = "records" in shape
    has_raw = "raw_jsonl" in shape
    if has_records == has_raw:
        raise ValueError("source shape must provide exactly one source representation")
    if has_records:
        if not isinstance(shape["records"], list):
            raise ValueError("source shape records are malformed")
        complete = encode_jsonl(shape["records"])
        raw = complete + shape.get("partial_tail", "").encode("utf-8")
    else:
        if not isinstance(shape["raw_jsonl"], str):
            raise ValueError("source shape raw JSONL is malformed")
        raw = shape["raw_jsonl"].encode("utf-8")
    try:
        prefix = intake.stable_complete_prefix(raw)
        records = intake.parse_jsonl(prefix)
        selection = selection_for_shape(shape, records, prefix)
        admitted, _, _ = intake.validate_records(records, selection, prefix=prefix)
        actual = "accept"
        selected_count = len(admitted)
    except ev.IntegrityError:
        actual = "reject"
        selected_count = 0
    if actual != shape["expected"]:
        raise AssertionError(f"source shape {shape['shape_id']} expected {shape['expected']} but produced {actual}")
    if actual == "accept" and selected_count != shape.get("expected_selected_count"):
        raise AssertionError(f"source shape {shape['shape_id']} selected-count contradiction")
    return actual, selected_count


def write_bytes(path: Path, data: bytes, mode=0o600):
    path.write_bytes(data)
    os.chmod(path, mode)


def create_run(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    if not (repo / ".git").exists():
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (repo / ".gitignore").write_text("artifacts/\n", encoding="utf-8")
    base = repo / "artifacts/private/interpretation_integrity"
    receipt = base / "active-run-receipt.json"
    ev.init_private_run(base, EVAL / "privacy_policy.v0.json", receipt, repo_root=repo)
    return receipt, ev.resolve_run_root(receipt)


def write_inputs(tmp_path, records, selection_document=None, *, tail=b""):
    source_root = tmp_path / "sources"
    source_root.mkdir(mode=0o700)
    source = source_root / "source.jsonl"
    prefix = encode_jsonl(records)
    write_bytes(source, prefix + tail)
    receipt, root = create_run(tmp_path)
    manifest = root / "raw/selection.json"
    document = selection_document or make_selection(records)
    write_bytes(manifest, json.dumps(document, ensure_ascii=False).encode("utf-8"))
    return source, manifest, receipt, root, prefix


def validate_in_memory(records, selection_document=None):
    prefix = encode_jsonl(records)
    return intake.validate_records(records, selection_document or make_selection(records), prefix=prefix)


def test_observed_paired_root_envelope_is_accepted_without_echo(tmp_path):
    message = "Synthetic direct input with café."
    encoded = message.encode("utf-8")
    start = encoded.index("café".encode())
    records = [meta(), *pair(message=message, text_elements=[{"byte_range": {"start": start, "end": len(encoded)}, "placeholder": "café."}])]
    source, manifest, receipt, root, _ = write_inputs(tmp_path, records)
    result = intake.validate_exact_files(source, manifest, receipt, "intake-receipt.json", source_root=source.parent)
    ev.validate_document(result, EVAL / "private_source_receipt.schema.json")
    serialized = json.dumps(result)
    assert message not in serialized and "turn-a" not in serialized and str(source) not in serialized
    assert result["selected_count"] == 1 and result["raw_content_copied"] is False
    assert (root / "raw/source-crosswalk.json").stat().st_mode & 0o777 == 0o600


def test_old_invented_identity_shape_is_rejected():
    old = [
        {"type": "session_meta", "payload": {"source": "cli", "root_thread_id": "root-synthetic", "parent_thread_id": None}},
        {"type": "event_msg", "turn_id": "turn-a", "message_id": "message-a", "direct": True, "payload": {"type": "user_message", "message": "Synthetic direct input."}},
    ]
    with pytest.raises(ev.IntegrityError):
        intake.validate_records(old, {}, prefix=encode_jsonl(old))


@pytest.mark.parametrize(
    "records",
    [
        [meta(), event()],
        [meta(), response(), {"type": "synthetic-gap", "payload": {}}, event()],
        [meta(), response(), event(), event()],
    ],
)
def test_missing_nonadjacent_or_unpaired_duplicate_event_does_not_admit_invented_identity(records):
    prefix = encode_jsonl(records)
    selection = {
        "schema_version": intake.SELECTION_VERSION,
        "root_session_id": "root-synthetic",
        "source_prefix_length": len(prefix),
        "source_prefix_digest": ev.sha256_bytes(prefix),
        "complete_record_count": len(records),
        "selections": [{"turn_id": "turn-a", "message_id": "message-a", "envelope_digest": "sha256:" + "0" * 64}],
    }
    with pytest.raises(ev.IntegrityError):
        intake.validate_records(records, selection, prefix=prefix)


def test_unpaired_role_user_response_is_ignored_as_injected_context():
    records = [meta(), response("injected-turn", "injected-message", "Injected synthetic context."), *pair()]
    selected = make_selection(records, selected={("turn-a", "message-a")})
    admitted, conflicts, unsupported = validate_in_memory(records, selected)
    assert len(admitted) == 1 and conflicts == 0 and unsupported == 0


@pytest.mark.parametrize(
    "records",
    [
        [meta(), response(message="alpha"), event(message="beta")],
        [meta(), response(content=[{"type": "input_text", "text": "Synthetic direct input.", "extra": True}]), event()],
        [meta(), response(extra="forbidden"), event()],
        [meta(), response(), event(extra="forbidden")],
        [meta(), response(), event(images=["synthetic-image"])],
        [meta(), response(), event(audio=None)],
    ],
)
def test_response_direct_mismatch_extra_fields_and_media_fail_closed(records):
    prefix = encode_jsonl(records)
    with pytest.raises(ev.IntegrityError):
        intake._validate_pair(records[-2], records[-1])
    assert prefix


def test_same_identity_same_envelope_is_idempotent_but_conflict_blocks():
    repeated = [meta(), *pair(message="alpha"), *pair(message="alpha")]
    admitted, _, _ = validate_in_memory(repeated, make_selection(repeated))
    assert len(admitted) == 1
    conflict = [meta(), *pair(message="alpha"), *pair(message="beta")]
    selection = make_selection([meta(), *pair(message="alpha")])
    prefix = encode_jsonl(conflict)
    selection.update(source_prefix_length=len(prefix), source_prefix_digest=ev.sha256_bytes(prefix), complete_record_count=len(conflict))
    with pytest.raises(ev.IntegrityError, match="conflict"):
        intake.validate_records(conflict, selection, prefix=prefix)


def test_same_content_different_identity_remains_distinct():
    records = [meta(), *pair("turn-a", "message-a", "same"), *pair("turn-b", "message-b", "same")]
    admitted, _, _ = validate_in_memory(records)
    assert len(admitted) == 2


def test_digest_binds_presence_and_text_elements():
    plain = [meta(), *pair(message="Synthetic direct input.")]
    element = [{"byte_range": {"start": 0, "end": 9}, "placeholder": "Synthetic"}]
    annotated = [meta(), *pair(message="Synthetic direct input.", text_elements=element)]
    assert make_selection(plain)["selections"][0]["envelope_digest"] != make_selection(annotated)["selections"][0]["envelope_digest"]
    altered = make_selection(plain)
    prefix = encode_jsonl(annotated)
    altered.update(source_prefix_length=len(prefix), source_prefix_digest=ev.sha256_bytes(prefix), complete_record_count=len(annotated))
    with pytest.raises(ev.IntegrityError, match="envelope mismatch"):
        intake.validate_records(annotated, altered, prefix=prefix)


@pytest.mark.parametrize(
    "elements",
    [
        [{"byte_range": [0, 1], "placeholder": "S"}],
        [{"byte_range": {"start": 0, "end": 99}, "placeholder": "Synthetic"}],
        [{"byte_range": {"start": 1, "end": 2}, "placeholder": "x"}],
        [{"byte_range": {"start": 0, "end": 9}, "placeholder": "Mismatch"}],
        [{"byte_range": {"start": 0, "end": 9}, "placeholder": "Synthetic"}, {"byte_range": {"start": 8, "end": 10}, "placeholder": "c "}],
        [{"byte_range": {"start": 0, "end": 9}, "placeholder": "Synthetic", "extra": True}],
    ],
)
def test_text_element_bounds_boundaries_overlap_and_shape_are_strict(elements):
    with pytest.raises(ev.IntegrityError):
        intake._validate_pair(response(), event(text_elements=elements))


def test_text_element_must_begin_and_end_on_utf8_boundaries():
    message = "Café"
    with pytest.raises(ev.IntegrityError):
        intake._validate_pair(
            response(message=message),
            event(message=message, text_elements=[{"byte_range": {"start": 4, "end": 5}, "placeholder": "synthetic"}]),
        )


@pytest.mark.parametrize("message", ["Cafe\u0301", "\ud800"])
def test_direct_text_must_already_be_nfc_unicode_scalar_text(message):
    with pytest.raises(ev.IntegrityError):
        intake._validate_pair(response(message=message), event(message=message))


def test_partial_final_record_is_excluded_and_selection_binds_complete_prefix(tmp_path):
    records = [meta(), *pair()]
    source, manifest, receipt, _, prefix = write_inputs(tmp_path, records, tail=b'{"partial":')
    result = intake.validate_exact_files(source, manifest, receipt, "intake-receipt.json", source_root=source.parent)
    assert result["selected_count"] == 1
    assert source.stat().st_size > len(prefix)


def test_append_only_growth_preserves_source_prefix(tmp_path):
    path = tmp_path / "source.jsonl"
    original = encode_jsonl([meta(), *pair()])
    write_bytes(path, original)
    held = intake.HeldFile(path)
    try:
        prefix = intake.stable_complete_prefix(held.read_initial())
        with path.open("ab") as stream:
            stream.write(b'{"partial":')
        held.assert_stable_source(prefix)
    finally:
        held.close()


@pytest.mark.parametrize("mutation", ["prefix", "shrink", "replace"])
def test_prefix_mutation_shrink_and_inode_replacement_fail(tmp_path, mutation):
    path = tmp_path / "source.jsonl"
    original = encode_jsonl([meta(), *pair()])
    write_bytes(path, original)
    held = intake.HeldFile(path)
    prefix = intake.stable_complete_prefix(held.read_initial())
    try:
        if mutation == "prefix":
            with path.open("r+b") as stream:
                stream.seek(0)
                stream.write(b"X")
        elif mutation == "shrink":
            os.truncate(path, len(original) - 1)
        else:
            replacement = tmp_path / "replacement.jsonl"
            write_bytes(replacement, original)
            os.replace(replacement, path)
        with pytest.raises(ev.IntegrityError):
            held.assert_stable_source(prefix)
    finally:
        held.close()


def test_complete_malformed_record_and_duplicate_json_keys_fail():
    with pytest.raises(ev.IntegrityError):
        intake.parse_jsonl(b'{"type":"session_meta"}\n{"broken":}\n')
    with pytest.raises(ev.IntegrityError):
        intake.parse_jsonl(b'{"type":"session_meta","payload":{"id":"a","id":"b"}}\n')
    with pytest.raises(ev.IntegrityError):
        intake._load_selection(b'{"schema_version":"a","schema_version":"b"}')


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_json_constants_fail_in_source_selection_and_digest(constant):
    with pytest.raises(ev.IntegrityError):
        intake.parse_jsonl(f'{{"type":"session_meta","payload":{{"number":{constant}}}}}\n'.encode())
    with pytest.raises(ev.IntegrityError):
        intake._load_selection(f'{{"number":{constant}}}'.encode())
    value = {"number": float(constant.replace("Infinity", "inf").replace("NaN", "nan"))}
    with pytest.raises(ev.IntegrityError):
        intake.envelope_digest(value)


@pytest.mark.parametrize(
    "change",
    [
        {"unknown": True},
        {"root_session_id": "other-root"},
        {"source_prefix_length": 0},
        {"source_prefix_digest": "sha256:" + "0" * 64},
        {"complete_record_count": 0},
        {"selections": []},
    ],
)
def test_selection_schema_and_prefix_binding_are_strict(change):
    records = [meta(), *pair()]
    selected = make_selection(records)
    selected.update(change)
    with pytest.raises(ev.IntegrityError):
        validate_in_memory(records, selected)


def test_selection_requires_receipt_derived_path_mode_and_immutability(tmp_path):
    records = [meta(), *pair()]
    source, manifest, receipt, root, _ = write_inputs(tmp_path, records)
    outside = tmp_path / "selection.json"
    write_bytes(outside, manifest.read_bytes())
    with pytest.raises(ev.IntegrityError, match="location"):
        intake.validate_exact_files(source, outside, receipt, "intake-receipt.json", source_root=source.parent)
    os.chmod(manifest, 0o644)
    with pytest.raises(ev.IntegrityError, match="mode"):
        intake.validate_exact_files(source, manifest, receipt, "intake-receipt.json", source_root=source.parent)

    os.chmod(manifest, 0o600)
    held = intake.HeldFile(manifest, exact_mode=0o600)
    original = held.read_initial()
    try:
        with manifest.open("ab") as stream:
            stream.write(b" ")
        with pytest.raises(ev.IntegrityError, match="selection changed"):
            held.assert_immutable(original)
    finally:
        held.close()
    assert root.exists()


def test_source_and_selection_reject_symlink_fifo_and_inode_replacement(tmp_path):
    actual = tmp_path / "actual.jsonl"
    write_bytes(actual, encode_jsonl([meta(), *pair()]))
    link = tmp_path / "source-link.jsonl"
    link.symlink_to(actual)
    with pytest.raises(ev.IntegrityError, match="open failed"):
        intake.HeldFile(link)
    fifo = tmp_path / "source-fifo"
    os.mkfifo(fifo)
    with pytest.raises(ev.IntegrityError):
        intake.HeldFile(fifo)

    held = intake.HeldFile(actual)
    replacement = tmp_path / "replacement.jsonl"
    write_bytes(replacement, actual.read_bytes())
    os.replace(replacement, actual)
    try:
        with pytest.raises(ev.IntegrityError, match="path changed"):
            held.assert_path_identity()
    finally:
        held.close()


def test_receipt_raw_directory_replacement_is_detected(tmp_path):
    receipt, root = create_run(tmp_path)
    raw = root / "raw"
    held = intake.HeldDirectory(raw)
    displaced = root / "raw-displaced"
    raw.rename(displaced)
    raw.mkdir(mode=0o700)
    try:
        with pytest.raises(ev.IntegrityError, match="directory path changed"):
            held.assert_unchanged()
    finally:
        held.close()
    assert receipt.exists()


@pytest.mark.parametrize("target_name", ["raw", "sanitized"])
def test_end_to_end_output_directory_swap_cannot_escape_held_receipt_root(tmp_path, monkeypatch, target_name):
    records = [meta(), *pair()]
    source, manifest, receipt, root, _ = write_inputs(tmp_path, records)
    original_writer = intake.write_json_at_noclobber
    swapped = False
    escape = tmp_path / f"escape-{target_name}"
    escape.mkdir(mode=0o700)

    def swapping_writer(directory, name, value):
        nonlocal swapped
        should_swap = (target_name == "raw" and name == "source-crosswalk.json") or (
            target_name == "sanitized" and name == "intake-receipt.json"
        )
        if should_swap and not swapped:
            current = root / target_name
            current.rename(root / f"{target_name}-displaced")
            current.symlink_to(escape, target_is_directory=True)
            swapped = True
        return original_writer(directory, name, value)

    monkeypatch.setattr(intake, "write_json_at_noclobber", swapping_writer)
    with pytest.raises(ev.IntegrityError, match="directory path changed"):
        intake.validate_exact_files(source, manifest, receipt, "intake-receipt.json", source_root=source.parent)
    assert list(escape.iterdir()) == []
    displaced = root / f"{target_name}-displaced"
    assert not (displaced / "source-crosswalk.json").exists()
    assert not (displaced / "intake-receipt.json").exists()


def test_outputs_are_noclobber_and_existing_file_is_unchanged(tmp_path):
    records = [meta(), *pair()]
    source, manifest, receipt, root, _ = write_inputs(tmp_path, records)
    existing = root / "raw/source-crosswalk.json"
    marker = b"synthetic-existing-output\n"
    write_bytes(existing, marker)
    with pytest.raises(ev.IntegrityError, match="publication rejected"):
        intake.validate_exact_files(source, manifest, receipt, "intake-receipt.json", source_root=source.parent)
    assert existing.read_bytes() == marker
    assert not (root / "sanitized/intake-receipt.json").exists()


def test_selection_entries_reject_unknown_keys_and_duplicate_identities():
    records = [meta(), *pair()]
    unknown = make_selection(records)
    unknown["selections"][0]["extra"] = True
    with pytest.raises(ev.IntegrityError):
        validate_in_memory(records, unknown)
    duplicate = make_selection(records)
    duplicate["selections"].append(dict(duplicate["selections"][0]))
    with pytest.raises(ev.IntegrityError):
        validate_in_memory(records, duplicate)


def test_cli_error_is_generic_and_does_not_echo_private_values(tmp_path, capsys):
    source_root = tmp_path / "sources"
    source_root.mkdir(mode=0o700)
    source = source_root / "sensitive-source-name.jsonl"
    write_bytes(source, b'{"private-secret":"do-not-echo",}\n')
    receipt, root = create_run(tmp_path)
    manifest = root / "raw/selection.json"
    write_bytes(manifest, b'{"private-selection-secret":"do-not-echo"}')
    assert intake.main(["validate", "--source-file", str(source), "--source-root", str(source_root), "--selection-file", str(manifest), "--run-receipt", str(receipt), "--receipt-name", "intake.json"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "interpretation-integrity private intake rejected"
    assert "secret" not in captured.err and str(source) not in captured.err


@pytest.mark.parametrize("shape", SOURCE_SHAPES["shapes"], ids=lambda shape: shape["shape_id"])
def test_synthetic_source_log_shape_is_executable(shape):
    execute_source_shape(shape)


def test_synthetic_source_log_shapes_are_content_safe_and_cover_adverse_contract():
    assert SOURCE_SHAPES["schema_version"] == "interpretation-integrity.source-log-shapes.v0"
    ids = {shape["shape_id"] for shape in SOURCE_SHAPES["shapes"]}
    required = {
        "observed-paired-root",
        "invented-old-envelope",
        "unpaired-user-response",
        "nonadjacent-pair",
        "pair-text-mismatch",
        "identity-conflict",
        "same-digest-distinct-identity",
        "unsupported-media",
        "text-element-boundary",
        "partial-tail",
        "operator-provenance-fork-limitation",
        "malformed-complete-record",
        "duplicate-key",
        "nonfinite-constant",
    }
    assert required <= ids
    provenance = next(shape for shape in SOURCE_SHAPES["shapes"] if shape["shape_id"] == "operator-provenance-fork-limitation")
    assert provenance["expected"] == "accept" and provenance["non_claims"]
    serialized = json.dumps(SOURCE_SHAPES)
    assert "/home/" not in serialized and "rollout-" not in serialized


def test_source_shape_executor_detects_contradictory_expected_and_malformed_fixture():
    contradictory = copy.deepcopy(SOURCE_SHAPES["shapes"][0])
    contradictory["expected"] = "reject"
    with pytest.raises(AssertionError, match="expected reject but produced accept"):
        execute_source_shape(contradictory)
    malformed = {"shape_id": "synthetic-malformed", "expected": "accept"}
    with pytest.raises(ValueError, match="exactly one source representation"):
        execute_source_shape(malformed)


@pytest.mark.parametrize("location", [
    "system", "other_identity", "home_root", "outside_selected_root", "traversal",
    "ssh", "azure", "codex_auth", "codex_root", "credential_name", "wrong_extension",
])
def test_external_source_scope_rejects_unsafe_paths_before_open(tmp_path, monkeypatch, location):
    selected = tmp_path / "sources"
    path = selected / "source.jsonl"
    if location == "system":
        selected, path = Path("/etc"), Path("/etc/synthetic.jsonl")
    elif location == "other_identity":
        selected = tmp_path.parent / "synthetic-other-identity"
        path = selected / "source.jsonl"
    elif location == "home_root":
        selected = tmp_path
    elif location == "outside_selected_root":
        path = tmp_path / "unselected/source.jsonl"
    elif location == "traversal":
        path = selected / "../unselected/source.jsonl"
    elif location in {"ssh", "azure"}:
        selected = tmp_path / (".ssh" if location == "ssh" else ".azure")
        path = selected / "source.jsonl"
    elif location == "codex_auth":
        selected, path = tmp_path / ".codex", tmp_path / ".codex/auth.jsonl"
    elif location == "codex_root":
        selected, path = tmp_path / ".codex", tmp_path / ".codex/sessions/source.jsonl"
    elif location == "credential_name":
        path = selected / "credentials.jsonl"
    elif location == "wrong_extension":
        path = selected / "source.json"
    monkeypatch.setenv("HOME", str(selected))
    monkeypatch.setattr(os, "open", lambda *_a, **_k: pytest.fail("rejected scope must not open source paths"))
    with pytest.raises(ev.IntegrityError):
        intake.HeldSource(path, source_root=selected)


def test_explicit_synthetic_codex_session_root_accepts_only_selected_subtree(tmp_path):
    codex = tmp_path / ".codex"
    codex.mkdir(mode=0o700)
    sessions = codex / "sessions"
    sessions.mkdir(mode=0o700)
    selected = sessions / "selected"
    selected.mkdir(mode=0o700)
    path = selected / "synthetic.jsonl"
    data = encode_jsonl([meta(), *pair()])
    write_bytes(path, data)
    held = intake.HeldSource(path, source_root=selected)
    try:
        assert held.read_initial() == data
        with path.open("ab") as stream:
            stream.write(b'{"partial":')
        held.assert_stable_source(data)
    finally:
        held.close()
    with pytest.raises(ev.IntegrityError):
        intake.HeldSource(path, source_root=sessions / "another")


@pytest.mark.parametrize("mutation", ["root_symlink", "ancestor_symlink", "leaf_symlink", "hardlink", "fifo", "writable_parent", "writable_leaf", "wrong_owner", "oversize"])
def test_source_descriptor_boundary_rejects_before_content_read(tmp_path, monkeypatch, mutation):
    selected = tmp_path / "sources"
    selected.mkdir(mode=0o700)
    path = selected / "source.jsonl"
    write_bytes(path, encode_jsonl([meta(), *pair()]))
    if mutation in {"root_symlink", "ancestor_symlink"}:
        displaced = tmp_path / "displaced"
        selected.rename(displaced)
        selected.symlink_to(displaced, target_is_directory=True)
        if mutation == "ancestor_symlink":
            (displaced / "child").mkdir(mode=0o700)
            write_bytes(displaced / "child/source.jsonl", b"synthetic\n")
            selected = selected / "child"
            path = selected / "source.jsonl"
    elif mutation == "leaf_symlink":
        original = selected / "original.jsonl"
        path.rename(original)
        path.symlink_to(original)
    elif mutation == "hardlink":
        os.link(path, selected / "alias.jsonl")
    elif mutation == "fifo":
        path.unlink()
        os.mkfifo(path)
    elif mutation == "writable_parent":
        selected.chmod(0o770)
    elif mutation == "writable_leaf":
        path.chmod(0o660)
    elif mutation == "wrong_owner":
        actual_uid = os.getuid()
        monkeypatch.setattr(os, "getuid", lambda: actual_uid + 1)
    elif mutation == "oversize":
        os.truncate(path, intake.MAX_SOURCE_BYTES + 1)
    monkeypatch.setattr(os, "pread", lambda *_a, **_k: pytest.fail("unsafe source must not be read"))
    with pytest.raises(ev.IntegrityError):
        intake.HeldSource(path, source_root=selected)


def test_source_ancestor_is_checked_before_opening_a_descendant(tmp_path, monkeypatch):
    target = tmp_path / "not-a-real-other-identity"
    link = tmp_path / "sources"
    link.symlink_to(target, target_is_directory=True)
    original = os.open
    opened = []

    def observed_open(name, *args, **kwargs):
        opened.append(str(name))
        return original(name, *args, **kwargs)

    monkeypatch.setattr(os, "open", observed_open)
    with pytest.raises(ev.IntegrityError):
        intake.HeldSource(link / "unread/source.jsonl", source_root=link / "unread")
    assert "unread" not in opened and "source.jsonl" not in opened


def test_source_ancestor_replacement_invalidates_held_source(tmp_path):
    selected = tmp_path / "sources"
    selected.mkdir(mode=0o700)
    path = selected / "source.jsonl"
    data = encode_jsonl([meta(), *pair()])
    write_bytes(path, data)
    held = intake.HeldSource(path, source_root=selected)
    try:
        assert held.read_initial() == data
        selected.rename(tmp_path / "displaced")
        selected.mkdir(mode=0o700)
        write_bytes(path, data)
        with pytest.raises(ev.IntegrityError):
            held.assert_stable_source(data)
    finally:
        held.close()


def reconstruction_inputs(tmp_path, monkeypatch):
    """Synthetic procedure fixture; never a scientific efficacy assertion."""
    # Scope repository identity to this synthetic procedure. The developer's
    # concurrent worktree edits are not part of its candidate or its authority.
    candidate = ev.sha256_bytes(b"synthetic-candidate-for-private-boundary-tests")
    monkeypatch.setattr(ev, "candidate_state_digest", lambda: candidate)
    source, selection, receipt, root, _ = write_inputs(tmp_path, [meta(), *pair(message="woven.")])
    intake.validate_exact_files(source, selection, receipt, "intake.json", source_root=source.parent)
    now = int(ev.time.time())
    identity = lambda name: {"principal_id": "synthetic-" + name, "session_id": "synthetic-" + name + "-session"}
    bindings = {
        "corpus_hash": ev.sha256_file(FIX / "cases.v0.json"),
        "case_schema_hash": ev.sha256_file(EVAL / "case.schema.json"),
        "rubric_hash": ev.sha256_file(EVAL / "annotation_rubric.v0.json"),
        "policy_hash": ev.sha256_file(EVAL / "privacy_policy.v0.json"),
        "candidate_state_hash": ev.candidate_state_digest(),
    }
    corpus = ev.load_json(FIX / "cases.v0.json")
    cases = []
    for case in corpus["cases"]:
        cases.append({
            "case_id": case["case_id"], "origin_class": case["synthetic_origin_class"],
            "unit_mappings": [] if case["synthetic_origin_class"] == "fully_synthetic" else [{
                "unit_id": unit["unit_id"],
                "source_units": [{"source_alias": "source-001", "source_unit_alias": "source-unit-001", "locator": {"start": 0, "end": 1}}],
                "preserved_dimensions": ["stance"], "deliberately_changed_dimensions": ["wording"],
            } for unit in case["semantic_units"]],
        })
    manifest = {
        "schema_version": "interpretation-integrity.private-derivation-manifest.v0",
        "expires_at_epoch": now + 600, "crosswalk_hash": ev.sha256_file(root / "raw/source-crosswalk.json"),
        "selection_count": 1, **bindings, "producer_identity": identity("producer"),
        "fixture_author_identity": identity("author"),
        "sources": [{"source_alias": "source-001", "disposition": "used", "reason_code": "structural_seed"}],
        "cases": cases, "authority_effect": "none",
    }
    assignment = {
        "schema_version": "interpretation-integrity.private-review-assignment.v0",
        "assignment_id": "synthetic-review", "issued_at_epoch": now - 1, "expires_at_epoch": now + 600,
        "coordinator_identity": identity("coordinator"), "reviewer_identity": identity("reviewer"),
        "reviewer_kind": "local_human", "producer_identity": identity("producer"), "fixture_author_identity": identity("author"),
        "procedure_version": "private-reconstruction-review-v1", "tool_version": "synthetic-v1",
        "prompt_hash": "sha256:" + "0" * 64, "candidate_state_hash": bindings["candidate_state_hash"],
        "allowed_input": ["selected_source_content", "derivation_manifest", "frozen_public_corpus", "annotation_rubric"],
        "allowed_output": "raw/reconstruction-review.json", "review_channel": "local_human_no_provider", "authority_effect": "none",
    }
    manifest_path, assignment_path = root / "raw/derivation-manifest.json", root / "raw/reconstruction-assignment.json"
    write_bytes(manifest_path, json.dumps(manifest).encode())
    write_bytes(assignment_path, json.dumps(assignment).encode())
    return source, selection, receipt, root, manifest_path, assignment_path, assignment, corpus


def reconstruction_review_fixture(tmp_path, monkeypatch):
    source, selection, receipt, root, manifest, assignment_path, assignment, corpus = reconstruction_inputs(tmp_path, monkeypatch)
    packet = ev.prepare_private_reconstruction(source, selection, manifest, assignment_path, receipt, "raw/reconstruction-packet.json", source_root=source.parent)
    review = {
        "schema_version": "interpretation-integrity.private-reconstruction-review.v0",
        "assignment_hash": ev.sha256_file(assignment_path), "packet_hash": ev.sha256_file(root / "raw/reconstruction-packet.json"),
        "reviewer_session_binding": ev.sha256_json(assignment["reviewer_identity"]),
        "source_results": [{"source_alias": "source-001", "disposition_result": "pass"}],
        "case_results": [{"case_id": case["case_id"], "origin_result": "pass", "failure_family_result": "pass"} for case in corpus["cases"]],
        "unit_results": [{"case_id": case["case_id"], "unit_id": unit["unit_id"], **dict.fromkeys(("actor", "expression_act", "stance", "modality", "evidence_status", "qualification", "frame_origin", "response_requirement", "severity"), "pass")} for case in corpus["cases"] for unit in case["semantic_units"]],
        "leakage_checks": dict.fromkeys(("verbatim_near_verbatim", "unique_names_entities", "distinctive_numbers_dates", "distinctive_analogy_narrative"), "pass"),
        "mosaic_result": "pass", "complete_coverage": True, "structural_fidelity": "pass",
        "reconstructability": "not_reconstructive", "authority_effect": "none",
    }
    return receipt, root, packet, assignment, review


def validate_review_fixture(receipt, output):
    return ev.validate_private_reconstruction(
        receipt, "raw/reconstruction-packet.json", "raw/reconstruction-assignment.json", "raw/reconstruction-review.json",
        EVAL / "private_reconstruction_packet.schema.json", EVAL / "private_review_assignment.schema.json",
        EVAL / "private_reconstruction_review.schema.json", output,
    )


def test_canonical_private_reconstruction_procedure_preserves_content_free_receipt(tmp_path, monkeypatch):
    receipt, root, _packet, _assignment, review = reconstruction_review_fixture(tmp_path, monkeypatch)
    write_bytes(root / "raw/reconstruction-review.json", json.dumps(review).encode())
    result = validate_review_fixture(receipt, tmp_path / "receipt.json")
    assert result["case_count"] == 24 and result["leak_count"] == 0
    assert result["authority_effect"] == "none" and result["atlas_native_capability"] is False
    assert "woven" not in json.dumps(result) and str(root) not in json.dumps(result)


@pytest.mark.parametrize("schema_slot", [0, 1, 2])
def test_private_reconstruction_rejects_replacement_schema_before_private_reads(tmp_path, monkeypatch, schema_slot):
    schemas = [EVAL / name for name in ("private_reconstruction_packet.schema.json", "private_review_assignment.schema.json", "private_reconstruction_review.schema.json")]
    schemas[schema_slot] = tmp_path / "permissive-schema.json"
    write_bytes(schemas[schema_slot], b'{"$schema":"https://json-schema.org/draft/2020-12/schema","type":"object"}')
    monkeypatch.setattr(ev, "PrivateRunAuthority", lambda *_a, **_k: pytest.fail("alternate schema must reject before private reads"))
    with pytest.raises(ev.IntegrityError):
        ev.validate_private_reconstruction(tmp_path / "unused", "raw/packet.json", "raw/assignment.json", "raw/review.json", *schemas, tmp_path / "receipt.json")
    assert not (tmp_path / "receipt.json").exists()


@pytest.mark.parametrize("mutation", [
    "empty_leakage", "missing_leakage", "extra_leakage", "false_boolean", "string_boolean", "integer_boolean",
    "false_screen_count", "missing_screen", "integer_persisted", "reviewer_not_independent", "assignment_expired",
])
def test_private_reconstruction_never_reports_pass_for_incomplete_or_false_evidence(tmp_path, monkeypatch, mutation):
    receipt, root, packet, assignment, review = reconstruction_review_fixture(tmp_path, monkeypatch)
    if mutation == "empty_leakage":
        review["leakage_checks"] = {}
    elif mutation == "missing_leakage":
        review["leakage_checks"].pop("unique_names_entities")
    elif mutation == "extra_leakage":
        review["leakage_checks"]["invented"] = "pass"
    elif mutation in {"false_boolean", "string_boolean", "integer_boolean"}:
        review["complete_coverage"] = {"false_boolean": False, "string_boolean": "false", "integer_boolean": 1}[mutation]
    elif mutation == "false_screen_count":
        packet["deterministic_screen"]["mosaic_flags"] = False
    elif mutation == "missing_screen":
        packet["deterministic_screen"].pop("mosaic_flags")
    elif mutation == "integer_persisted":
        packet["source_content_persisted"] = 0
    elif mutation == "reviewer_not_independent":
        assignment["reviewer_identity"] = assignment["producer_identity"]
    elif mutation == "assignment_expired":
        assignment["expires_at_epoch"] = int(ev.time.time()) - 1
    write_bytes(root / "raw/reconstruction-assignment.json", json.dumps(assignment).encode())
    packet["assignment_hash"] = ev.sha256_file(root / "raw/reconstruction-assignment.json")
    write_bytes(root / "raw/reconstruction-packet.json", json.dumps(packet).encode())
    review["packet_hash"] = ev.sha256_file(root / "raw/reconstruction-packet.json")
    review["assignment_hash"] = packet["assignment_hash"]
    review["reviewer_session_binding"] = ev.sha256_json(assignment["reviewer_identity"])
    write_bytes(root / "raw/reconstruction-review.json", json.dumps(review).encode())
    with pytest.raises(ev.IntegrityError):
        validate_review_fixture(receipt, tmp_path / "receipt.json")
    assert not (tmp_path / "receipt.json").exists()


@pytest.mark.parametrize("mutation", ["duplicate_key", "unknown_key", "private_enum"])
def test_private_reconstruction_cli_and_api_errors_never_echo_private_input(tmp_path, monkeypatch, capsys, mutation):
    source, selection, receipt, root, manifest, assignment_path, assignment, _corpus = reconstruction_inputs(tmp_path, monkeypatch)
    marker = "synthetic-sensitive-value-do-not-echo"
    if mutation == "duplicate_key":
        write_bytes(manifest, ('{"' + marker + '":1,"' + marker + '":2}').encode())
    elif mutation == "unknown_key":
        assignment[marker] = marker
        write_bytes(assignment_path, json.dumps(assignment).encode())
    else:
        assignment["allowed_input"][0] = marker
        write_bytes(assignment_path, json.dumps(assignment).encode())
    with pytest.raises(ev.IntegrityError) as rejected:
        ev.prepare_private_reconstruction(source, selection, manifest, assignment_path, receipt, "raw/reconstruction-packet.json", source_root=source.parent)
    assert marker not in str(rejected.value) and rejected.value.__suppress_context__
    status = ev.main([
        "prepare-private-reconstruction", "--source", str(source), "--source-root", str(source.parent),
        "--selection", str(selection), "--derivation-manifest", str(manifest), "--assignment", str(assignment_path),
        "--run-receipt", str(receipt), "--output-name", "raw/reconstruction-packet.json",
    ])
    captured = capsys.readouterr()
    assert status == 2 and captured.out == ""
    assert captured.err.strip() == "interpretation-integrity private operation rejected"
    assert marker not in captured.err and str(source) not in captured.err
    assert not (root / "raw/reconstruction-packet.json").exists()


@pytest.mark.parametrize("command", ["intake", "prepare", "review"])
@pytest.mark.parametrize("malformation", ["unknown_option", "missing_value", "unknown_command"])
def test_private_cli_parse_errors_are_content_free_before_file_open(monkeypatch, capsys, command, malformation):
    marker = "synthetic-private-diagnostic-marker"
    if command == "intake":
        module = intake
        arguments = ["validate", "--source-file", marker, "--source-root", marker,
                     "--selection-file", marker, "--run-receipt", marker, "--receipt-name", marker]
        expected = "interpretation-integrity private intake rejected"
    elif command == "prepare":
        module = ev
        arguments = ["prepare-private-reconstruction", "--source", marker, "--source-root", marker,
                     "--selection", marker, "--derivation-manifest", marker, "--assignment", marker,
                     "--run-receipt", marker, "--output-name", marker]
        expected = "interpretation-integrity private operation rejected"
    else:
        module = ev
        arguments = ["validate-private-reconstruction", "--run-receipt", marker, "--packet-name", marker,
                     "--assignment-name", marker, "--review-name", marker, "--packet-schema", marker,
                     "--assignment-schema", marker, "--review-schema", marker, "--receipt", marker]
        expected = "interpretation-integrity private operation rejected"
    if malformation == "unknown_option":
        arguments.extend(["--unexpected", marker])
    elif malformation == "missing_value":
        arguments.append(arguments[1])
    else:
        arguments[0] = marker
    monkeypatch.setattr(os, "open", lambda *_a, **_k: pytest.fail("malformed private argv must not open files"))
    assert module.main(arguments) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err.strip() == expected
    assert marker not in captured.err


def test_private_cli_choice_errors_do_not_echo_supplied_value(monkeypatch, capsys):
    marker = "synthetic-private-choice-marker"
    monkeypatch.setattr(os, "open", lambda *_a, **_k: pytest.fail("malformed private argv must not open files"))
    assert ev.main(["cleanup", "--run-receipt", marker, "--stage-id", marker, "--mode", marker,
                    "--policy", marker, "--receipt-name", marker]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err.strip() == "interpretation-integrity private operation rejected"
    assert marker not in captured.err


@pytest.mark.parametrize("module,command", [(intake, "validate"), (ev, "prepare-private-reconstruction")])
def test_private_cli_help_is_available_without_opening_files(monkeypatch, capsys, module, command):
    monkeypatch.setattr(os, "open", lambda *_a, **_k: pytest.fail("help must not open private files"))
    with pytest.raises(SystemExit) as exited:
        module.main([command, "--help"])
    captured = capsys.readouterr()
    assert exited.value.code == 0 and "--source-root" in captured.out and captured.err == ""


def test_public_cli_keeps_detailed_argument_errors(monkeypatch, capsys):
    marker = "synthetic-public-argument-marker"
    monkeypatch.setattr(os, "open", lambda *_a, **_k: pytest.fail("malformed public argv must not open files"))
    with pytest.raises(SystemExit) as exited:
        ev.main(["validate-harness-delta", "--harness", "synthetic", "--target", "synthetic",
                 "--allow-prefix", "synthetic", "--unexpected", marker])
    captured = capsys.readouterr()
    assert exited.value.code == 2 and marker in captured.err and "unrecognized arguments" in captured.err
