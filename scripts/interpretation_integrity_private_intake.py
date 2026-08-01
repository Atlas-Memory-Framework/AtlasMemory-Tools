#!/usr/bin/env python3
"""Fail-closed intake for one explicitly selected private Codex root JSONL.

The tool never discovers files. Source text is held only in memory while the
selected identities are checked; content-free receipts contain no paths, ids,
digests, timestamps, quotations, or diagnostic echoes.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import secrets
import stat
import sys
import time
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence

import interpretation_integrity_eval as integrity


POLICY_VERSION = "interpretation-integrity.private-intake.v0"
SELECTION_VERSION = "interpretation-integrity.private-selection.v0"
ENVELOPE_VERSION = "interpretation-integrity.direct-envelope.v0"
EVENT_FIELDS = {"type", "message", "text_elements", "images", "local_images", "audio", "local_audio"}
RESPONSE_FIELDS = {"type", "role", "content", "id", "internal_chat_message_metadata_passthrough"}
SELECTION_FIELDS = {
    "schema_version",
    "root_session_id",
    "source_prefix_length",
    "source_prefix_digest",
    "complete_record_count",
    "selections",
}
SELECTION_ITEM_FIELDS = {"turn_id", "message_id", "envelope_digest"}


class HeldFile:
    """An owned regular file held by descriptor and checked against its path."""

    def __init__(self, path: Path, *, exact_mode: int | None = None, parent_fd: int | None = None, leaf_name: str | None = None):
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        try:
            self.fd = os.open(leaf_name if parent_fd is not None else path, flags, dir_fd=parent_fd)
        except OSError as exc:
            raise integrity.IntegrityError("private input open failed") from exc
        self.path = path
        self.parent_fd = parent_fd
        self.leaf_name = leaf_name
        self.before = os.fstat(self.fd)
        if not stat.S_ISREG(self.before.st_mode) or self.before.st_uid != os.getuid():
            os.close(self.fd)
            raise integrity.IntegrityError("private input type or owner rejected")
        if exact_mode is not None and stat.S_IMODE(self.before.st_mode) != exact_mode:
            os.close(self.fd)
            raise integrity.IntegrityError("private input mode rejected")

    def read_initial(self) -> bytes:
        return self.read_prefix(self.before.st_size)

    def read_prefix(self, length: int) -> bytes:
        chunks: list[bytes] = []
        offset = 0
        while offset < length:
            part = os.pread(self.fd, min(1024 * 1024, length - offset), offset)
            if not part:
                break
            chunks.append(part)
            offset += len(part)
        data = b"".join(chunks)
        if len(data) != length:
            raise integrity.IntegrityError("private input changed during intake")
        return data

    def assert_path_identity(self) -> os.stat_result:
        after = os.fstat(self.fd)
        if any(getattr(self.before, field) != getattr(after, field) for field in ("st_dev", "st_ino", "st_mode", "st_uid")):
            raise integrity.IntegrityError("private input identity changed during intake")
        try:
            if self.parent_fd is None:
                current = self.path.lstat()
            else:
                current = os.stat(self.leaf_name, dir_fd=self.parent_fd, follow_symlinks=False)
        except OSError as exc:
            raise integrity.IntegrityError("private input path changed during intake") from exc
        if stat.S_ISLNK(current.st_mode) or current.st_dev != self.before.st_dev or current.st_ino != self.before.st_ino:
            raise integrity.IntegrityError("private input path changed during intake")
        return after

    def assert_immutable(self, original: bytes) -> None:
        after = self.assert_path_identity()
        immutable_fields = ("st_size", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(self.before, field) != getattr(after, field) for field in immutable_fields):
            raise integrity.IntegrityError("private selection changed during intake")
        if self.read_prefix(len(original)) != original:
            raise integrity.IntegrityError("private selection changed during intake")

    def assert_stable_source(self, prefix: bytes) -> None:
        after = self.assert_path_identity()
        if after.st_size < self.before.st_size:
            raise integrity.IntegrityError("private source shrank during intake")
        if self.read_prefix(len(prefix)) != prefix:
            raise integrity.IntegrityError("private source prefix changed during intake")

    def close(self) -> None:
        os.close(self.fd)


class HeldDirectory:
    """A receipt-derived directory held so child opens cannot race path swaps."""

    def __init__(self, path: Path, *, parent_fd: int | None = None, leaf_name: str | None = None):
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_DIRECTORY", 0)
        try:
            self.fd = os.open(leaf_name if parent_fd is not None else path, flags, dir_fd=parent_fd)
        except OSError as exc:
            raise integrity.IntegrityError("private directory open failed") from exc
        self.path = path
        self.parent_fd = parent_fd
        self.leaf_name = leaf_name
        self.before = os.fstat(self.fd)
        if not stat.S_ISDIR(self.before.st_mode) or self.before.st_uid != os.getuid() or stat.S_IMODE(self.before.st_mode) != 0o700:
            os.close(self.fd)
            raise integrity.IntegrityError("private directory rejected")

    def assert_unchanged(self) -> None:
        after = os.fstat(self.fd)
        if any(getattr(self.before, field) != getattr(after, field) for field in ("st_dev", "st_ino", "st_mode", "st_uid")):
            raise integrity.IntegrityError("private directory changed during intake")
        try:
            if self.parent_fd is None:
                current = self.path.lstat()
            else:
                current = os.stat(self.leaf_name, dir_fd=self.parent_fd, follow_symlinks=False)
        except OSError as exc:
            raise integrity.IntegrityError("private directory path changed during intake") from exc
        if stat.S_ISLNK(current.st_mode) or (current.st_dev, current.st_ino) != (self.before.st_dev, self.before.st_ino):
            raise integrity.IntegrityError("private directory path changed during intake")

    def close(self) -> None:
        os.close(self.fd)


def _reject_json_constant(_value: str) -> None:
    raise integrity.IntegrityError("non-finite JSON number rejected")


def write_json_at_noclobber(directory: HeldDirectory, name: str, value: Mapping[str, Any]) -> tuple[int, int]:
    """Atomically publish a new 0600 JSON file relative to a held directory."""
    pure = PurePosixPath(name)
    if pure.is_absolute() or len(pure.parts) != 1 or name in {"", ".", ".."}:
        raise integrity.IntegrityError("private output name rejected")
    try:
        data = (json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise integrity.IntegrityError("private output serialization rejected") from exc

    temporary = f".{name}.{secrets.token_hex(16)}.tmp"
    descriptor = -1
    linked = False
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary, flags, 0o600, dir_fd=directory.fd)
        offset = 0
        while offset < len(data):
            written = os.write(descriptor, data[offset:])
            if written <= 0:
                raise integrity.IntegrityError("private output write failed")
            offset += written
        os.fsync(descriptor)
        item = os.fstat(descriptor)
        if not stat.S_ISREG(item.st_mode) or item.st_uid != os.getuid() or stat.S_IMODE(item.st_mode) != 0o600:
            raise integrity.IntegrityError("private output file rejected")
        os.link(temporary, name, src_dir_fd=directory.fd, dst_dir_fd=directory.fd, follow_symlinks=False)
        linked = True
        os.unlink(temporary, dir_fd=directory.fd)
        os.fsync(directory.fd)
        published = os.stat(name, dir_fd=directory.fd, follow_symlinks=False)
        if stat.S_ISLNK(published.st_mode) or (published.st_dev, published.st_ino) != (item.st_dev, item.st_ino):
            raise integrity.IntegrityError("private output publication rejected")
        return published.st_dev, published.st_ino
    except OSError as exc:
        raise integrity.IntegrityError("private output publication rejected") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if not linked:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary, dir_fd=directory.fd)


def assert_output_identity(directory: HeldDirectory, name: str, identity: tuple[int, int]) -> None:
    try:
        item = os.stat(name, dir_fd=directory.fd, follow_symlinks=False)
    except OSError as exc:
        raise integrity.IntegrityError("private output path changed during intake") from exc
    if stat.S_ISLNK(item.st_mode) or (item.st_dev, item.st_ino) != identity:
        raise integrity.IntegrityError("private output path changed during intake")


def cleanup_created_output(directory: HeldDirectory, name: str, identity: tuple[int, int] | None) -> None:
    if identity is None:
        return
    try:
        item = os.stat(name, dir_fd=directory.fd, follow_symlinks=False)
        if not stat.S_ISLNK(item.st_mode) and (item.st_dev, item.st_ino) == identity:
            os.unlink(name, dir_fd=directory.fd)
            os.fsync(directory.fd)
    except FileNotFoundError:
        return


def stable_complete_prefix(data: bytes) -> bytes:
    end = data.rfind(b"\n")
    if end < 0:
        raise integrity.IntegrityError("source has no complete record")
    return data[: end + 1]


def parse_jsonl(prefix: bytes) -> list[Mapping[str, Any]]:
    if not prefix.endswith(b"\n"):
        raise integrity.IntegrityError("source prefix is incomplete")
    records: list[Mapping[str, Any]] = []
    for raw_line in prefix[:-1].split(b"\n"):
        if not raw_line.strip():
            raise integrity.IntegrityError("source contains an empty complete record")
        try:
            line = raw_line.decode("utf-8", "strict")
            value = json.loads(
                line,
                object_pairs_hook=integrity._reject_duplicate_keys,
                parse_constant=_reject_json_constant,
            )
        except (UnicodeError, json.JSONDecodeError, integrity.IntegrityError) as exc:
            raise integrity.IntegrityError("source contains an invalid complete record") from exc
        if not isinstance(value, dict):
            raise integrity.IntegrityError("source contains a non-object record")
        records.append(value)
    if not records:
        raise integrity.IntegrityError("source has no complete records")
    return records


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _require_identifier(value: Any) -> str:
    if not _nonempty_string(value):
        raise integrity.IntegrityError("source identity rejected")
    integrity.require_nfc_text(value, "private source identity")
    return value


def _validate_text_elements(message: str, value: Any) -> None:
    if not isinstance(value, list):
        raise integrity.IntegrityError("direct event text elements rejected")
    encoded = message.encode("utf-8", "strict")
    prior_end = 0
    for element in value:
        if not isinstance(element, dict) or set(element) != {"byte_range", "placeholder"}:
            raise integrity.IntegrityError("direct event text element shape rejected")
        byte_range = element["byte_range"]
        placeholder = element["placeholder"]
        if not isinstance(byte_range, dict) or set(byte_range) != {"start", "end"}:
            raise integrity.IntegrityError("direct event byte range shape rejected")
        start, end = byte_range["start"], byte_range["end"]
        if isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int) or not isinstance(end, int):
            raise integrity.IntegrityError("direct event byte range rejected")
        if not (0 <= start < end <= len(encoded)) or start < prior_end:
            raise integrity.IntegrityError("direct event byte range rejected")
        if not isinstance(placeholder, str):
            raise integrity.IntegrityError("direct event placeholder rejected")
        integrity.require_nfc_text(placeholder, "private source placeholder")
        try:
            selected = encoded[start:end].decode("utf-8", "strict")
        except UnicodeDecodeError as exc:
            raise integrity.IntegrityError("direct event byte range rejected") from exc
        if selected != placeholder:
            raise integrity.IntegrityError("direct event placeholder mismatch")
        prior_end = end


def _validate_pair(response: Mapping[str, Any], event: Mapping[str, Any]) -> tuple[str, str, str, Mapping[str, Any]]:
    if response.get("type") != "response_item" or not isinstance(response.get("payload"), dict):
        raise integrity.IntegrityError("direct event is not adjacent to its response item")
    response_payload = response["payload"]
    if set(response_payload) != RESPONSE_FIELDS:
        raise integrity.IntegrityError("response item envelope rejected")
    metadata = response_payload["internal_chat_message_metadata_passthrough"]
    content = response_payload["content"]
    if (
        response_payload["type"] != "message"
        or response_payload["role"] != "user"
        or not _nonempty_string(response_payload["id"])
        or not isinstance(metadata, dict)
        or set(metadata) != {"turn_id"}
        or not _nonempty_string(metadata["turn_id"])
        or not isinstance(content, list)
        or len(content) != 1
        or not isinstance(content[0], dict)
        or set(content[0]) != {"type", "text"}
        or content[0]["type"] != "input_text"
        or not isinstance(content[0]["text"], str)
    ):
        raise integrity.IntegrityError("response item envelope rejected")
    message_id = _require_identifier(response_payload["id"])
    turn_id = _require_identifier(metadata["turn_id"])
    text = content[0]["text"]
    integrity.require_nfc_text(text, "private source response text")

    if event.get("type") != "event_msg" or not isinstance(event.get("payload"), dict):
        raise integrity.IntegrityError("direct event envelope rejected")
    event_payload = event["payload"]
    if set(event_payload) != EVENT_FIELDS or event_payload["type"] != "user_message":
        raise integrity.IntegrityError("direct event envelope rejected")
    message = event_payload["message"]
    if not isinstance(message, str):
        raise integrity.IntegrityError("selected unsupported modality")
    integrity.require_nfc_text(message, "private source message")
    if message != text:
        raise integrity.IntegrityError("paired response and direct event mismatch")
    for media_field in ("images", "local_images", "audio", "local_audio"):
        if not isinstance(event_payload[media_field], list) or event_payload[media_field]:
            raise integrity.IntegrityError("selected unsupported modality")
    _validate_text_elements(message, event_payload["text_elements"])

    envelope = {
        "schema_version": ENVELOPE_VERSION,
        "response_item": response,
        "event_msg": event,
    }
    return turn_id, message_id, envelope_digest(envelope), envelope


def envelope_digest(envelope: Any) -> str:
    try:
        encoded = (json.dumps(envelope, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise integrity.IntegrityError("direct envelope serialization rejected") from exc
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _validate_selection(
    selection: Mapping[str, Any],
    *,
    root_session_id: str,
    prefix: bytes,
    complete_record_count: int,
) -> dict[tuple[str, str, str], Mapping[str, Any]]:
    if not isinstance(selection, dict) or set(selection) != SELECTION_FIELDS:
        raise integrity.IntegrityError("private selection shape rejected")
    if selection["schema_version"] != SELECTION_VERSION or selection["root_session_id"] != root_session_id:
        raise integrity.IntegrityError("private selection binding rejected")
    if (
        isinstance(selection["source_prefix_length"], bool)
        or not isinstance(selection["source_prefix_length"], int)
        or selection["source_prefix_length"] != len(prefix)
        or selection["source_prefix_digest"] != integrity.sha256_bytes(prefix)
        or isinstance(selection["complete_record_count"], bool)
        or not isinstance(selection["complete_record_count"], int)
        or selection["complete_record_count"] != complete_record_count
    ):
        raise integrity.IntegrityError("private selection prefix binding rejected")
    requested = selection["selections"]
    if not isinstance(requested, list) or not requested:
        raise integrity.IntegrityError("private selection identities rejected")
    requested_by_key: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for item in requested:
        if not isinstance(item, dict) or set(item) != SELECTION_ITEM_FIELDS:
            raise integrity.IntegrityError("private selection entry rejected")
        turn_id = _require_identifier(item["turn_id"])
        message_id = _require_identifier(item["message_id"])
        if not isinstance(item["envelope_digest"], str) or not integrity.HASH_RE.fullmatch(item["envelope_digest"]):
            raise integrity.IntegrityError("private selection digest rejected")
        key = (root_session_id, turn_id, message_id)
        if key in requested_by_key:
            raise integrity.IntegrityError("private selection identity repeated")
        requested_by_key[key] = item
    return requested_by_key


def validate_records(
    records: Sequence[Mapping[str, Any]],
    selection: Mapping[str, Any],
    *,
    prefix: bytes,
) -> tuple[list[Mapping[str, Any]], int, int]:
    if not records:
        raise integrity.IntegrityError("source has no complete records")
    first = records[0]
    payload = first.get("payload")
    if first.get("type") != "session_meta" or not isinstance(payload, dict) or payload.get("source") != "cli":
        raise integrity.IntegrityError("source session envelope rejected")
    root_session_id = _require_identifier(payload.get("id"))
    requested_by_key = _validate_selection(
        selection,
        root_session_id=root_session_id,
        prefix=prefix,
        complete_record_count=len(records),
    )

    admitted: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    seen: dict[tuple[str, str, str], str] = {}
    for index, record in enumerate(records[1:], 1):
        event_payload = record.get("payload")
        if record.get("type") != "event_msg" or not isinstance(event_payload, dict) or event_payload.get("type") != "user_message":
            continue
        if index == 0:
            raise integrity.IntegrityError("direct event is missing its response item")
        turn_id, message_id, digest, _envelope = _validate_pair(records[index - 1], record)
        key = (root_session_id, turn_id, message_id)
        prior = seen.get(key)
        if prior is not None and prior != digest:
            raise integrity.IntegrityError("source identity conflict")
        seen[key] = digest
        if key in requested_by_key:
            if requested_by_key[key]["envelope_digest"] != digest:
                raise integrity.IntegrityError("private selection envelope mismatch")
            admitted[key] = {"identity": list(key), "envelope_digest": digest}

    if set(requested_by_key) != set(admitted):
        raise integrity.IntegrityError("private selection was not admitted")
    return [admitted[key] for key in sorted(admitted)], 0, 0


def _load_selection(data: bytes) -> Mapping[str, Any]:
    try:
        text = data.decode("utf-8", "strict")
        value = json.loads(
            text,
            object_pairs_hook=integrity._reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeError, json.JSONDecodeError, integrity.IntegrityError) as exc:
        raise integrity.IntegrityError("private selection document rejected") from exc
    if not isinstance(value, dict):
        raise integrity.IntegrityError("private selection document rejected")
    return value


def validate_exact_files(source_path: Path, selection_path: Path, run_receipt: Path, receipt_name: str) -> Mapping[str, Any]:
    run_root = integrity.resolve_run_root(run_receipt)
    expected_selection = integrity.resolve_private_child(run_root, "raw/selection.json")
    if not selection_path.is_absolute() or ".." in selection_path.parts or selection_path != expected_selection:
        raise integrity.IntegrityError("private selection location rejected")
    if source_path == selection_path:
        raise integrity.IntegrityError("private input aliases rejected")

    pure_receipt_name = PurePosixPath(receipt_name)
    if pure_receipt_name.is_absolute() or len(pure_receipt_name.parts) != 1 or receipt_name in {"", ".", ".."}:
        raise integrity.IntegrityError("private receipt name rejected")

    root_directory: HeldDirectory | None = None
    raw_directory: HeldDirectory | None = None
    sanitized_directory: HeldDirectory | None = None
    source: HeldFile | None = None
    selection_file: HeldFile | None = None
    crosswalk_identity: tuple[int, int] | None = None
    receipt_identity: tuple[int, int] | None = None
    try:
        root_directory = HeldDirectory(run_root)
        raw_directory = HeldDirectory(run_root / "raw", parent_fd=root_directory.fd, leaf_name="raw")
        sanitized_directory = HeldDirectory(run_root / "sanitized", parent_fd=root_directory.fd, leaf_name="sanitized")
        if raw_directory.before.st_dev != root_directory.before.st_dev or sanitized_directory.before.st_dev != root_directory.before.st_dev:
            raise integrity.IntegrityError("private run directory device rejected")
        source = HeldFile(source_path)
        selection_file = HeldFile(selection_path, exact_mode=0o600, parent_fd=raw_directory.fd, leaf_name="selection.json")
        if selection_file.before.st_dev != root_directory.before.st_dev:
            raise integrity.IntegrityError("private selection device rejected")
        if (source.before.st_dev, source.before.st_ino) == (selection_file.before.st_dev, selection_file.before.st_ino):
            raise integrity.IntegrityError("private input aliases rejected")

        source_initial = source.read_initial()
        prefix = stable_complete_prefix(source_initial)
        records = parse_jsonl(prefix)
        selection_bytes = selection_file.read_initial()
        selection = _load_selection(selection_bytes)
        admitted, conflicts, unsupported = validate_records(records, selection, prefix=prefix)
        source.assert_stable_source(prefix)
        selection_file.assert_immutable(selection_bytes)
        root_directory.assert_unchanged()
        raw_directory.assert_unchanged()
        sanitized_directory.assert_unchanged()

        crosswalk = {
            "schema_version": "interpretation-integrity.private-crosswalk.v0",
            "expires_at_epoch": int(time.time()) + 3600,
            "root_session_id": selection["root_session_id"],
            "source_prefix_length": selection["source_prefix_length"],
            "source_prefix_digest": selection["source_prefix_digest"],
            "complete_record_count": selection["complete_record_count"],
            "selections": admitted,
        }
        receipt = {
            "schema_version": "interpretation-integrity.private-source-receipt.v0",
            "policy_version": POLICY_VERSION,
            "selected_count": len(admitted),
            "identity_conflict_count": conflicts,
            "unsupported_modality_count": unsupported,
            "raw_content_copied": False,
            "source_identifiers_in_receipt": False,
            "authority_effect": "none",
            "atlas_native_capability": False,
        }
        crosswalk_identity = write_json_at_noclobber(raw_directory, "source-crosswalk.json", crosswalk)
        receipt_identity = write_json_at_noclobber(sanitized_directory, receipt_name, receipt)

        source.assert_stable_source(prefix)
        selection_file.assert_immutable(selection_bytes)
        root_directory.assert_unchanged()
        raw_directory.assert_unchanged()
        sanitized_directory.assert_unchanged()
        assert_output_identity(raw_directory, "source-crosswalk.json", crosswalk_identity)
        assert_output_identity(sanitized_directory, receipt_name, receipt_identity)
        return receipt
    except Exception:
        if sanitized_directory is not None:
            cleanup_created_output(sanitized_directory, receipt_name, receipt_identity)
        if raw_directory is not None:
            cleanup_created_output(raw_directory, "source-crosswalk.json", crosswalk_identity)
        raise
    finally:
        if selection_file is not None:
            selection_file.close()
        if source is not None:
            source.close()
        if sanitized_directory is not None:
            sanitized_directory.close()
        if raw_directory is not None:
            raw_directory.close()
        if root_directory is not None:
            root_directory.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--source-file", required=True)
    validate.add_argument("--selection-file", required=True)
    validate.add_argument("--run-receipt", required=True)
    validate.add_argument("--receipt-name", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        receipt = validate_exact_files(Path(args.source_file), Path(args.selection_file), Path(args.run_receipt), args.receipt_name)
        print(json.dumps(receipt, sort_keys=True))
        return 0
    except (integrity.IntegrityError, OSError):
        print("interpretation-integrity private intake rejected", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
