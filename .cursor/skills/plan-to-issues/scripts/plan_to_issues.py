# atlas-tools-generated: source=skills/plan-to-issues/scripts/plan_to_issues.py manifest=atlas-tools.v1 checksum=sha256:b574731240c31c61643b5cc55b4733f04abeea6ea30190dae659b17bf9a8192b
# atlas-tools-generated-end
from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
WORKSTREAM_ID_PATTERN = r"WS(?:\d+[A-Z]?(?:-[A-Z0-9]+)*|-[A-Z0-9]+(?:-[A-Z0-9]+)*)"
WORKSTREAM_HEADING_RE = re.compile(rf"^###\s+({WORKSTREAM_ID_PATTERN}\s+.+)$")
WORKSTREAM_BULLET_RE = re.compile(
    rf"^-\s+`?({WORKSTREAM_ID_PATTERN})`?:\s+(.+)$", re.IGNORECASE
)
# Canonical bullet block for workstreams (prefer this over ### headings when present).
WORKSTREAMS_SECTION_HEADING = "### Workstreams + merge points"
AUTOMATION_MANIFEST_SECTION_TITLE = "Automation Issue Manifest"
AUTOMATION_MANIFEST_SECTION_HEADING = f"### {AUTOMATION_MANIFEST_SECTION_TITLE}"
MANIFEST_LEAF_SECTION_HEADING = "### Leaf issues"
PHASE_HEADING_RE = re.compile(r"^####\s+(Phase\s+\d+:\s+.+)$")
MANIFEST_LEAF_ID_PATTERN = r"(?:[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+|[A-Z]+[0-9]+)"
MANIFEST_LEAF_BULLET_RE = re.compile(
    rf"^-\s+`?({MANIFEST_LEAF_ID_PATTERN})`?:\s+(.+)$", re.IGNORECASE
)
MANIFEST_LEAF_TOKEN_RE = re.compile(
    rf"(?<![A-Za-z0-9-])({MANIFEST_LEAF_ID_PATTERN})(?![A-Za-z0-9])",
    re.IGNORECASE,
)
PLAN_ID_RE = re.compile(r"\b(WS\d+)\b", re.IGNORECASE)
PROJECT_URL_RE = re.compile(
    r"^https://github\.com/(?:orgs|users)/(?P<owner>[^/]+)/projects/(?P<number>\d+)/?$",
    re.IGNORECASE,
)
ISSUE_REF_RE = re.compile(
    r"(?:(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+))?#(?P<number>\d+)\b",
    re.IGNORECASE,
)
ISSUE_URL_RE = re.compile(
    r"https://github\.com/(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/issues/(?P<number>\d+)\b",
    re.IGNORECASE,
)
ISSUE_PLAN_PATH_RE = re.compile(r"^- Plan path: `([^`]+)`\r?$", re.MULTILINE)
ISSUE_REGISTRY_ROOT_RE = re.compile(r"^- Registry root: `([^`]+)`\r?$", re.MULTILINE)
ISSUE_PLAN_KEY_RE = re.compile(r"^- Plan key: `([^`]+)`\r?$", re.MULTILINE)
ISSUE_EPIC_ID_RE = re.compile(r"^- Epic id: `([^`]+)`\r?$", re.MULTILINE)
ISSUE_SOURCE_SECTION_RE = re.compile(r"^- Source section: `([^`]+)`\r?$", re.MULTILINE)
ISSUE_PARENT_EPIC_RE = re.compile(r"^## Parent Epic\r?\n(\S+)", re.MULTILINE)
FIELD_LINE_RE = re.compile(r"^\s*-\s+(?P<key>[^:]+):\s+(?P<value>.+)$")
# Nested bullets under "Review gates (named):" (common in Full-tier plans).
REVIEW_GATES_HEADER_RE = re.compile(
    r"^(?P<indent>\s*)-\s+Review gates[^:]*:\s*(?P<rest>.*)$",
    re.IGNORECASE,
)
WORKSTREAM_TOKEN_RE = re.compile(
    rf"(?<![A-Za-z0-9-])({WORKSTREAM_ID_PATTERN})(?![A-Za-z0-9])",
    re.IGNORECASE,
)
MERGE_POINT_RE = re.compile(
    r"(?<![A-Za-z0-9-])(?:WS\d+-MP\d+|MP-[A-Z0-9]+)(?![A-Za-z0-9])",
    re.IGNORECASE,
)
# Hyphen-separated gate ids may contain camelCase segments (e.g. G-WS2-FixtureCatalog).
# Avoid `\b` after internal hyphens and do not use a charset that excludes lowercase letters.
GATE_RE = re.compile(r"(?<![A-Za-z0-9])G(?:-[A-Za-z0-9]+)+(?![A-Za-z0-9])")
DECISION_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])DR(?:-[A-Za-z0-9]+)+(?![A-Za-z0-9])", re.IGNORECASE)
ASSUMPTION_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])A\d+(?![A-Za-z0-9])", re.IGNORECASE)
RISK_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])R\d+(?![A-Za-z0-9])", re.IGNORECASE)
ASSUMPTION_RE = re.compile(r"^-\s+(A\d+):\s+(.+)$", re.MULTILINE)
RISK_RE = re.compile(r"^-\s+(R\d+)(?:\s+\([^)]+\))?:\s+(.+)$", re.MULTILINE)
DECISION_RE = re.compile(r"^-\s+(DR-[A-Z0-9-]+):\s+(.+)$", re.MULTILINE)
FILE_DELTA_RE = re.compile(
    r"^-\s+(?:\[(?P<link_text>[^\]]+)\]\([^)]+\)|`(?P<code_path>[^`]+)`)\s+-\s+[^-]+-\s+(?P<owner>[^-]+?)\s+-",
    re.MULTILINE,
)
DEFAULT_GITHUB_OWNER = "OWNER"
ROOT_REPO_SLUG = f"{DEFAULT_GITHUB_OWNER}/service"
CORE_REPO_SLUG = f"{DEFAULT_GITHUB_OWNER}/core"
ADMIN_UI_REPO_SLUG = f"{DEFAULT_GITHUB_OWNER}/admin-ui"
APP_REPO_SLUG = f"{DEFAULT_GITHUB_OWNER}/app"
INFRA_REPO_SLUG = f"{DEFAULT_GITHUB_OWNER}/infra"
REPO_SLUG_ALIASES = {
    "root": ROOT_REPO_SLUG,
    "root-repo": ROOT_REPO_SLUG,
    "service": ROOT_REPO_SLUG,
    "api-service": ROOT_REPO_SLUG,
    "core": CORE_REPO_SLUG,
    "core-lib": CORE_REPO_SLUG,
    "admin-ui": ADMIN_UI_REPO_SLUG,
    "app": APP_REPO_SLUG,
    "frontend": APP_REPO_SLUG,
    "infra": INFRA_REPO_SLUG,
}
DEFAULT_BRANCH_HINTS: dict[str, str] = {}
ALLOWED_POINT_VALUES = {1, 2, 3, 5, 8, 13}
GITHUB_LABEL_NAME_MAX_LENGTH = 50
LABEL_DIGEST_LENGTH = 8
GITHUB_ISSUE_LIST_LIMIT = 1000
GITHUB_PROJECT_ITEM_LIST_LIMIT = 1000
ALLOWED_AGENT_TYPES = {"generalPurpose", "test-engineer", "code-reviewer", "explore"}

# Frozen join-metadata transport (DR-017 / WS2). Escaped-byte budgets apply to full
# `<!-- ... -->` segments after JSON serialization of the inner envelope object.
JOIN_METADATA_SCHEMA = "atlas.registry.join.v1"
JOIN_METADATA_PRIMARY_BUDGET_BYTES = 2048
JOIN_METADATA_EXTENSION_SHARD_MAX = 3
JOIN_METADATA_EXTENSION_BUDGET_BYTES = 2048
JOIN_METADATA_TOTAL_BUDGET_BYTES = 8192
REGISTRY_PROJECTION_TEMPLATE_ID_DEFAULT = "story.default-v1"
REGISTRY_DISCOVERY_DIRS = ("projects", "gates", "policy", "automation")
REGISTRY_PROJECTABLE_DISPOSITIONS = {"reuse", "reproject"}


class JoinMetadataEncodeError(Exception):
    """Raised when join metadata cannot be encoded within frozen shard budgets."""


def _require_yaml() -> object:
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - exercised when PyYAML missing
        raise SystemExit(
            "Registry-backed projection requires PyYAML. "
            "Install with `pip install pyyaml` or use the project dev virtualenv."
        ) from exc
    return yaml


def sort_json_keys(value: object) -> object:
    """Recursively sort mapping keys lexicographically for canonical JSON."""
    if isinstance(value, dict):
        return {k: sort_json_keys(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return [sort_json_keys(v) for v in value]
    return value


def canonical_json_utf8(payload: object) -> bytes:
    """Canonical minified JSON: UTF-8 of sorted-key JSON with no ASCII escapes for unicode."""
    ordered = sort_json_keys(payload)
    text = json.dumps(ordered, separators=(",", ":"), ensure_ascii=False, sort_keys=True)
    return text.encode("utf-8")


def join_metadata_checksum_hex(preimage: object) -> str:
    return hashlib.sha256(canonical_json_utf8(preimage)).hexdigest()


def _merge_extension_fragments(extension_shards: list[dict[str, object]]) -> dict[str, object]:
    merged: dict[str, object] = {}
    shards = sorted(extension_shards, key=lambda s: int(s.get("index", 0)))
    for shard in shards:
        raw = shard.get("fragment")
        if not isinstance(raw, str):
            raise JoinMetadataEncodeError("extension shard fragment must be a string")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise JoinMetadataEncodeError(f"invalid extension shard JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise JoinMetadataEncodeError("extension shard fragment must decode to a JSON object")
        merged.update(parsed)
    return merged


def build_join_metadata_preimage(
    *,
    primary: dict[str, object],
    extension_shards: list[dict[str, object]] | None,
) -> dict[str, object]:
    """Semantic preimage dict (checksum covers this object only, before wire sharding)."""
    core = {k: v for k, v in primary.items() if k != "shard_count"}
    if extension_shards:
        overflow = _merge_extension_fragments(extension_shards)
        if overflow:
            core = {**core, "overflow": overflow}
    return sort_json_keys(core)  # type: ignore[return-value]


def _shard_comment_byte_budget(*, is_primary: bool) -> int:
    return (
        JOIN_METADATA_PRIMARY_BUDGET_BYTES
        if is_primary
        else JOIN_METADATA_EXTENSION_BUDGET_BYTES
    )


def _join_comment_wire_size(
    *,
    shard_idx: int,
    json_n: int,
    outer_n: int,
    chunk: str,
    checksum_hex: str | None,
) -> int:
    """UTF-8 byte length of a finalized join-metadata HTML comment."""
    env: dict[str, object] = {
        "i": shard_idx,
        "n": json_n,
        "p": chunk,
        "schema": JOIN_METADATA_SCHEMA,
    }
    if checksum_hex is not None:
        env["h"] = checksum_hex
    inner = json.dumps(env, separators=(",", ":"), ensure_ascii=True, sort_keys=True)
    if shard_idx == 0:
        return len(f"<!-- ATLAS_REGISTRY_METADATA:{inner} -->".encode())
    return len(
        f"<!-- ATLAS_REGISTRY_METADATA_SHARD:{shard_idx + 1}/{outer_n}:{inner} -->".encode()
    )


def encode_join_metadata_html_comments(
    preimage: dict[str, object],
    *,
    checksum_hex: str,
) -> list[str]:
    """Emit ordered hidden HTML comment blocks; fail-closed on shard/budget violations."""
    canonical_bytes = canonical_json_utf8(preimage)
    canonical_b64 = base64.b64encode(canonical_bytes).decode("ascii")

    max_blocks = 1 + JOIN_METADATA_EXTENSION_SHARD_MAX
    outer_n_placeholder = max_blocks
    chunks: list[str] = []
    pos = 0
    shard_idx = 0

    while pos < len(canonical_b64):
        if shard_idx >= max_blocks:
            raise JoinMetadataEncodeError(
                f"join metadata exceeds maximum of {max_blocks} blocks after base64 sharding"
            )
        budget = _shard_comment_byte_budget(is_primary=(shard_idx == 0))
        lo, hi = 0, len(canonical_b64) - pos
        best = 0
        while lo <= hi:
            mid = (lo + hi) // 2
            piece = canonical_b64[pos : pos + mid]
            size = _join_comment_wire_size(
                shard_idx=shard_idx,
                json_n=outer_n_placeholder,
                outer_n=outer_n_placeholder,
                chunk=piece,
                checksum_hex=checksum_hex if shard_idx == 0 else None,
            )
            if size <= budget:
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        if best == 0:
            raise JoinMetadataEncodeError(
                f"cannot pack join-metadata shard {shard_idx} within {budget} escaped bytes"
            )
        chunks.append(canonical_b64[pos : pos + best])
        pos += best
        shard_idx += 1

    total_blocks = len(chunks)
    comments: list[str] = []
    for i, chunk in enumerate(chunks):
        inner_n = total_blocks
        outer_n = total_blocks
        size = _join_comment_wire_size(
            shard_idx=i,
            json_n=inner_n,
            outer_n=outer_n,
            chunk=chunk,
            checksum_hex=checksum_hex if i == 0 else None,
        )
        limit = _shard_comment_byte_budget(is_primary=(i == 0))
        if size > limit:
            raise JoinMetadataEncodeError(
                "join metadata block exceeds per-block budget after finalizing shard counts "
                f"(block {i}, size {size}, limit {limit})"
            )
        env: dict[str, object] = {
            "i": i,
            "n": inner_n,
            "p": chunk,
            "schema": JOIN_METADATA_SCHEMA,
        }
        if i == 0:
            env["h"] = checksum_hex
        inner = json.dumps(env, separators=(",", ":"), ensure_ascii=True, sort_keys=True)
        if i == 0:
            comments.append(f"<!-- ATLAS_REGISTRY_METADATA:{inner} -->")
        else:
            comments.append(f"<!-- ATLAS_REGISTRY_METADATA_SHARD:{i + 1}/{outer_n}:{inner} -->")

    total_bytes = sum(len(c.encode("utf-8")) for c in comments)
    if total_bytes > JOIN_METADATA_TOTAL_BUDGET_BYTES:
        raise JoinMetadataEncodeError(
            f"join metadata total escaped size {total_bytes} exceeds {JOIN_METADATA_TOTAL_BUDGET_BYTES}"
        )
    return comments


def decode_join_metadata_html_comments(comments: list[str]) -> dict[str, object]:
    """Fail-closed decode for parity checks (WS2); WS3 reconcile should reuse this contract."""
    primary_re = re.compile(
        r"<!--\s*ATLAS_REGISTRY_METADATA:({.+?})\s*-->",
        re.DOTALL,
    )
    shard_re = re.compile(
        r"<!--\s*ATLAS_REGISTRY_METADATA_SHARD:(\d+)/(\d+):({.+?})\s*-->",
        re.DOTALL,
    )
    envelopes: list[tuple[int, dict[str, object]]] = []
    for raw in comments:
        text = raw.strip()
        mp = primary_re.fullmatch(text)
        if mp:
            env = json.loads(mp.group(1))
            envelopes.append((0, env))
            continue
        ms = shard_re.fullmatch(text)
        if ms:
            idx = int(ms.group(1)) - 1
            env = json.loads(ms.group(3))
            envelopes.append((idx, env))
            continue
        raise JoinMetadataEncodeError(f"unrecognized join metadata comment: {text[:120]!r}")

    envelopes.sort(key=lambda t: int(t[1].get("i", -1)))
    if not envelopes or int(envelopes[0][1].get("i", -1)) != 0:
        raise JoinMetadataEncodeError("missing primary join metadata block")
    by_idx: dict[int, dict[str, object]] = {}
    for _, env in envelopes:
        i = int(env.get("i", -1))
        if i in by_idx:
            raise JoinMetadataEncodeError(f"duplicate join metadata shard index {i}")
        by_idx[i] = env
    n = int(envelopes[0][1].get("n", 0))
    if n < 1 or n > 1 + JOIN_METADATA_EXTENSION_SHARD_MAX:
        raise JoinMetadataEncodeError("invalid shard_count in join metadata")
    if len(by_idx) != n:
        raise JoinMetadataEncodeError("incomplete join metadata shard set")
    for expect in range(n):
        if expect not in by_idx:
            raise JoinMetadataEncodeError(f"missing join metadata shard index {expect}")
        if int(by_idx[expect].get("i", -1)) != expect:
            raise JoinMetadataEncodeError("join metadata shard index mismatch")
        if int(by_idx[expect].get("n", 0)) != n:
            raise JoinMetadataEncodeError("join metadata shard count mismatch across blocks")
    h0 = by_idx[0].get("h")
    if not isinstance(h0, str) or len(h0) != 64:
        raise JoinMetadataEncodeError("missing or invalid payload checksum on primary shard")
    b64_parts = [str(by_idx[i].get("p", "")) for i in range(n)]
    canonical_b64 = "".join(b64_parts)
    try:
        canonical_bytes = base64.b64decode(canonical_b64.encode("ascii"), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise JoinMetadataEncodeError(f"invalid base64 join payload: {exc}") from exc
    preimage = json.loads(canonical_bytes.decode("utf-8"))
    if join_metadata_checksum_hex(preimage).lower() != h0.lower():
        raise JoinMetadataEncodeError("join metadata checksum mismatch after reconstruction")
    if not isinstance(preimage, dict):
        raise JoinMetadataEncodeError("join metadata preimage must be a JSON object")
    return preimage


@dataclass
class IssueDraft:
    title: str
    body: str
    labels: list[str]
    kind: str
    source_id: str
    execution_repo: str | None = None
    legacy_issue_repo: str | None = None
    legacy_issue_number: int | None = None
    base_branch: str | None = None
    suggested_points: int | None = None
    dependencies: list[str] = field(default_factory=list)
    blocks: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    merge_points: list[str] = field(default_factory=list)
    gates: list[str] = field(default_factory=list)
    highest_tier: str | None = None
    repo_targets: list[str] = field(default_factory=list)
    repo_note: str = ""
    validation_requirements: list[str] = field(default_factory=list)
    unstable_reasons: list[str] = field(default_factory=list)
    issue_ready: bool = True
    azure_closeout_only: bool = False
    status_label: str = "status:draft"
    dispatch_recommendation: str = "tracking-only"
    dispatch_mode: str | None = None
    agent_type: str | None = None
    write_scope: list[str] = field(default_factory=list)
    validation_commands: list[str] = field(default_factory=list)
    validation_scope: str = "local"
    parallel_group: str | None = None
    critical_path_rank: int | None = None
    merge_group: str | None = None
    combine_policy: str | None = None
    conflict_class: str | None = None
    validation_tier: str | None = None
    risk_tags: list[str] = field(default_factory=list)
    dependency_issue_refs: list[str] = field(default_factory=list)
    blocker_issue_refs: list[str] = field(default_factory=list)
    automation_blockers: list[str] = field(default_factory=list)
    priority: str | None = None


@dataclass
class DependencyAnalysis:
    dependencies: list[str] = field(default_factory=list)
    issue_refs: list[str] = field(default_factory=list)
    unsupported_tokens: list[str] = field(default_factory=list)
    opaque_values: list[str] = field(default_factory=list)


@dataclass
class BlockerAnalysis:
    blockers: list[str] = field(default_factory=list)
    issue_refs: list[str] = field(default_factory=list)
    opaque_values: list[str] = field(default_factory=list)


@dataclass
class RegistryPortfolioSlice:
    """Typed handoff from the registry loader to the projector (WS2)."""

    registry_root: Path
    project: dict[str, Any]
    epic: dict[str, Any]
    stories: list[dict[str, Any]]
    merge_points: dict[str, dict[str, Any]]
    gates: dict[str, dict[str, Any]]
    policies: dict[str, dict[str, Any]]
    story_paths: dict[str, Path]


@dataclass(frozen=True)
class RegistrySelection:
    """Optional selector inputs for split-tree registry roots."""

    project_id: str | None = None
    epic_id: str | None = None
    story_ids: tuple[str, ...] = ()


class RegistryLoadError(Exception):
    """Invalid or ambiguous registry slice."""


def _registry_require_execution_repo(story: Mapping[str, Any], *, story_path: Path) -> str:
    if "execution_repo" not in story:
        raise RegistryLoadError(f"{story_path.name}: missing execution_repo")
    raw = story["execution_repo"]
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        raise RegistryLoadError(f"{story_path.name}: execution_repo is empty")
    if not isinstance(raw, str):
        raise RegistryLoadError(f"{story_path.name}: execution_repo must be a string")
    return raw.strip()


def _iter_registry_yaml_paths(registry_root: Path) -> list[Path]:
    discovered_paths: list[Path] = []
    for dirname in REGISTRY_DISCOVERY_DIRS:
        candidate = registry_root / dirname
        if candidate.is_dir():
            discovered_paths.extend(sorted(path for path in candidate.rglob("*.yaml") if path.is_file()))
    if discovered_paths:
        manifest_path = registry_root / "migration" / "manifest.yaml"
        if manifest_path.is_file():
            discovered_paths.append(manifest_path)
        return discovered_paths
    return sorted(path for path in registry_root.glob("*.yaml") if path.is_file())


def _require_registry_string_list(
    raw: object, *, field_name: str, path: Path
) -> list[str]:
    if not isinstance(raw, list) or not raw:
        raise RegistryLoadError(f"{path.name}: {field_name} must be a non-empty list")
    values: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise RegistryLoadError(f"{path.name}: {field_name} must contain only non-empty strings")
        values.append(item.strip())
    return values


def _registry_index_by_kind_id(
    by_path: list[tuple[Path, dict[str, Any]]], *, kind: str, id_field: str
) -> dict[str, tuple[Path, dict[str, Any]]]:
    indexed: dict[str, tuple[Path, dict[str, Any]]] = {}
    for path, doc in by_path:
        if doc.get("kind") != kind:
            continue
        raw = doc.get(id_field)
        if not isinstance(raw, str) or not raw.strip():
            raise RegistryLoadError(f"{path.name}: {kind}.{id_field} must be a non-empty string")
        key = raw.strip()
        existing = indexed.get(key)
        if existing is not None:
            raise RegistryLoadError(
                f"duplicate {kind} {id_field}={key!r}: {existing[0].name} and {path.name}"
            )
        indexed[key] = (path, doc)
    return indexed


def _load_manifest_story_rows(
    registry_root: Path,
) -> dict[str, list[dict[str, Any]]] | None:
    manifest_path = registry_root / "migration" / "manifest.yaml"
    if not manifest_path.is_file():
        return None
    yaml_mod = _require_yaml()
    manifest = yaml_mod.safe_load(read_text(manifest_path))
    if not isinstance(manifest, dict):
        raise RegistryLoadError(f"{manifest_path.name}: document must be a mapping")
    rows = manifest.get("rows")
    if not isinstance(rows, list):
        raise RegistryLoadError(f"{manifest_path.name}: rows must be a list")
    indexed: dict[str, list[dict[str, Any]]] = {}
    for idx, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise RegistryLoadError(f"{manifest_path.name}: rows[{idx}] must be a mapping")
        if row.get("registry_kind") != "story":
            continue
        raw = row.get("registry_id")
        if not isinstance(raw, str) or not raw.strip():
            raise RegistryLoadError(
                f"{manifest_path.name}: story rows must define a non-empty registry_id"
            )
        indexed.setdefault(raw.strip(), []).append(row)
    return indexed


def _manifest_require_projectable_story(
    story_id: str,
    *,
    manifest_story_rows: dict[str, list[dict[str, Any]]] | None,
) -> dict[str, Any] | None:
    if manifest_story_rows is None:
        return None
    rows = manifest_story_rows.get(story_id)
    if not rows:
        raise RegistryLoadError(
            f"story_id {story_id!r} is missing from migration manifest; projection remains fail-closed"
        )
    if len(rows) != 1:
        raise RegistryLoadError(
            f"story_id {story_id!r} has ambiguous migration manifest rows; projection remains fail-closed"
        )
    disposition = str(rows[0].get("disposition") or "").strip().lower()
    if disposition not in REGISTRY_PROJECTABLE_DISPOSITIONS:
        raise RegistryLoadError(
            f"story_id {story_id!r} is blocked by migration manifest disposition "
            f"{disposition or '<missing>'!r}; projection remains fail-closed"
        )
    return rows[0]


def _normalize_registry_story_ids(raw_values: object) -> tuple[str, ...]:
    if raw_values is None:
        return ()
    if not isinstance(raw_values, list):
        raise RegistryLoadError("registry_story_id selectors must be passed as strings")
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        if not isinstance(raw, str):
            raise RegistryLoadError("registry_story_id selectors must be strings")
        for token in re.split(r"[\s,]+", raw):
            story_id = token.strip()
            if not story_id:
                continue
            if story_id in seen:
                raise RegistryLoadError(
                    f"duplicate registry story selector {story_id!r}; selection must be unambiguous"
                )
            seen.add(story_id)
            normalized.append(story_id)
    return tuple(normalized)


def load_registry_portfolio(
    registry_root: Path, *, selection: RegistrySelection | None = None
) -> RegistryPortfolioSlice:
    """Load a flat or split-tree registry slice for projection."""
    yaml_mod = _require_yaml()
    if not registry_root.is_dir():
        raise SystemExit(f"Registry root is not a directory: {registry_root}")

    by_path: list[tuple[Path, dict[str, Any]]] = []
    for path in _iter_registry_yaml_paths(registry_root):
        doc = yaml_mod.safe_load(read_text(path))
        if not isinstance(doc, dict):
            raise RegistryLoadError(f"{path.name}: document must be a mapping")
        by_path.append((path, doc))

    project_index = _registry_index_by_kind_id(by_path, kind="project", id_field="project_id")
    epic_index = _registry_index_by_kind_id(by_path, kind="epic", id_field="epic_id")
    story_index = _registry_index_by_kind_id(by_path, kind="story", id_field="story_id")
    manifest_story_rows = _load_manifest_story_rows(registry_root)
    active_selection = selection or RegistrySelection()
    selected_story_ids = _normalize_registry_story_ids(list(active_selection.story_ids))

    selected_project_id = active_selection.project_id.strip() if active_selection.project_id else None
    selected_epic_id = active_selection.epic_id.strip() if active_selection.epic_id else None

    if selected_story_ids:
        project_ids: set[str] = set()
        epic_ids: set[str] = set()
        for story_id in selected_story_ids:
            match = story_index.get(story_id)
            if match is None:
                raise RegistryLoadError(f"missing story record for story_id={story_id!r}")
            _, story = match
            _manifest_require_projectable_story(
                story_id, manifest_story_rows=manifest_story_rows
            )
            project_raw = story.get("project_id")
            epic_raw = story.get("epic_id")
            if not isinstance(project_raw, str) or not project_raw.strip():
                raise RegistryLoadError(f"story_id {story_id!r}: project_id must be a non-empty string")
            if not isinstance(epic_raw, str) or not epic_raw.strip():
                raise RegistryLoadError(f"story_id {story_id!r}: epic_id must be a non-empty string")
            project_ids.add(project_raw.strip())
            epic_ids.add(epic_raw.strip())
        if len(project_ids) != 1 or len(epic_ids) != 1:
            raise RegistryLoadError(
                "selected registry stories must resolve to exactly one project and one epic"
            )
        resolved_project_id = next(iter(project_ids))
        resolved_epic_id = next(iter(epic_ids))
        if selected_project_id and selected_project_id != resolved_project_id:
            raise RegistryLoadError(
                f"--registry-project-id={selected_project_id!r} does not match selected "
                f"story project {resolved_project_id!r}"
            )
        if selected_epic_id and selected_epic_id != resolved_epic_id:
            raise RegistryLoadError(
                f"--registry-epic-id={selected_epic_id!r} does not match selected "
                f"story epic {resolved_epic_id!r}"
            )
        selected_project_id = resolved_project_id
        selected_epic_id = resolved_epic_id
    elif selected_epic_id:
        epic_match = epic_index.get(selected_epic_id)
        if epic_match is None:
            raise RegistryLoadError(f"missing epic record for epic_id={selected_epic_id!r}")
        _, epic_doc = epic_match
        epic_project_id = epic_doc.get("project_id")
        if not isinstance(epic_project_id, str) or not epic_project_id.strip():
            raise RegistryLoadError("epic.project_id must be a non-empty string")
        selected_project_id = epic_project_id.strip()
    elif selected_project_id:
        project_match = project_index.get(selected_project_id)
        if project_match is None:
            raise RegistryLoadError(f"missing project record for project_id={selected_project_id!r}")
        project_path, project_doc = project_match
        epic_ids = _require_registry_string_list(
            project_doc.get("epic_ids"), field_name="project.epic_ids", path=project_path
        )
        if len(epic_ids) != 1:
            raise RegistryLoadError(
                "registry project selection must resolve to exactly one epic; pass "
                "--registry-epic-id or --registry-story-id for split-tree roots"
            )
        selected_epic_id = epic_ids[0]
    else:
        if len(project_index) != 1 or len(epic_index) != 1:
            raise RegistryLoadError(
                "registry root contains multiple projects or epics; pass --registry-epic-id "
                "or --registry-story-id to select a canonical slice"
            )
        selected_project_id = next(iter(project_index))
        selected_epic_id = next(iter(epic_index))

    project_match = project_index.get(selected_project_id or "")
    if project_match is None:
        raise RegistryLoadError(f"missing project record for project_id={selected_project_id!r}")
    _, project = project_match
    project_id = str(project.get("project_id") or "").strip()
    if not project_id:
        raise RegistryLoadError("project.project_id must be a non-empty string")

    epic_match = epic_index.get(selected_epic_id or "")
    if epic_match is None:
        raise RegistryLoadError(f"missing epic record for epic_id={selected_epic_id!r}")
    epic_path, epic = epic_match
    epic_id = str(epic.get("epic_id") or "").strip()
    if not epic_id:
        raise RegistryLoadError("epic.epic_id must be a non-empty string")
    if epic.get("project_id") != project_id:
        raise RegistryLoadError("epic.project_id must match project.project_id")
    story_ids = _require_registry_string_list(
        epic.get("story_ids"), field_name="epic.story_ids", path=epic_path
    )
    if selected_story_ids:
        story_id_set = set(selected_story_ids)
        unknown = [sid for sid in selected_story_ids if sid not in story_ids]
        if unknown:
            raise RegistryLoadError(
                f"selected story_ids are not members of epic {epic_id!r}: {', '.join(unknown)}"
            )
        story_ids = [sid for sid in story_ids if sid in story_id_set]
    else:
        for sid in story_ids:
            _manifest_require_projectable_story(sid, manifest_story_rows=manifest_story_rows)

    stories: list[dict[str, Any]] = []
    story_paths: dict[str, Path] = {}
    for sid in story_ids:
        match = story_index.get(sid)
        if match is None:
            raise RegistryLoadError(f"missing story record for story_id={sid!r}")
        path, story = match
        story = dict(story)
        if story.get("project_id") != project_id or story.get("epic_id") != epic_id:
            raise RegistryLoadError(f"{path.name}: story project_id/epic_id mismatch")
        manifest_row = _manifest_require_projectable_story(
            sid, manifest_story_rows=manifest_story_rows
        )
        if isinstance(manifest_row, dict):
            legacy_repo = manifest_row.get("legacy_issue_repo")
            legacy_number = manifest_row.get("legacy_issue_number")
            if isinstance(legacy_repo, str) and legacy_repo.strip():
                story["_legacy_issue_repo"] = legacy_repo.strip()
            if isinstance(legacy_number, int):
                story["_legacy_issue_number"] = legacy_number
        _registry_require_execution_repo(story, story_path=path)
        stories.append(story)
        story_paths[sid] = path

    merge_points = {
        str(d.get("merge_point_id")): d
        for _, d in by_path
        if d.get("kind") == "merge_point" and isinstance(d.get("merge_point_id"), str)
    }
    gates = {
        str(d.get("gate_id")): d
        for _, d in by_path
        if d.get("kind") == "gate" and isinstance(d.get("gate_id"), str)
    }
    policies = {
        str(d.get("policy_profile_id")): d
        for _, d in by_path
        if d.get("kind") == "policy_profile" and isinstance(d.get("policy_profile_id"), str)
    }

    return RegistryPortfolioSlice(
        registry_root=registry_root,
        project=project,
        epic=epic,
        stories=stories,
        merge_points=merge_points,
        gates=gates,
        policies=policies,
        story_paths=story_paths,
    )


def registry_slice_anchor_context(registry_root: Path) -> tuple[str | None, str, str | None]:
    """(source_repo_slug, relative_registry_path, optional_github_url_to_slice)"""
    repo_root = resolve_repo_root(registry_root)
    relative = registry_root.name
    source_slug: str | None = None
    canonical_url: str | None = None
    if repo_root:
        try:
            relative = registry_root.relative_to(repo_root).as_posix()
        except ValueError:
            relative = registry_root.as_posix()
        origin_remote = run_git(["config", "--get", "remote.origin.url"], cwd=repo_root)
        source_slug = remote_repo_slug(origin_remote)
        normalized_remote = normalize_github_remote(origin_remote)
        if normalized_remote:
            source_ref = infer_source_ref(repo_root)
            canonical_url = f"{normalized_remote}/blob/{source_ref}/{relative}"
    return source_slug, relative, canonical_url


def build_registry_reference_lines(registry_root: Path) -> list[str]:
    source_slug, relative, canonical_url = registry_slice_anchor_context(registry_root)
    lines: list[str] = []
    if source_slug:
        lines.append(f"- Source repo: `{source_slug}`")
    lines.append(f"- Registry root: `{relative}`")
    if canonical_url:
        lines.append(f"- Canonical registry slice URL: {canonical_url}")
    lines.append(
        "- Execution note: registry YAML is the machine contract; this issue body is projected."
    )
    return lines


def _story_source_registry_path(registry_root: Path, story_path: Path) -> str:
    repo_root = resolve_repo_root(registry_root)
    if repo_root:
        try:
            return story_path.relative_to(repo_root).as_posix()
        except ValueError:
            pass
    return story_path.as_posix()


def _story_projection_version(story: dict[str, Any]) -> str:
    v = story.get("registry_schema_version")
    if isinstance(v, str) and v.strip():
        return v.strip()
    jm = story.get("join_metadata_fixture")
    if isinstance(jm, dict):
        prim = jm.get("primary")
        if isinstance(prim, dict):
            pv = prim.get("projection_version")
            if isinstance(pv, str) and pv.strip():
                return pv.strip()
    return "2026-04-14.mp1"


def _story_execution_issue_key(story: dict[str, Any], story_path: Path) -> str:
    jm = story.get("join_metadata_fixture")
    if isinstance(jm, dict):
        prim = jm.get("primary")
        if isinstance(prim, dict):
            key = prim.get("execution_issue_key")
            if isinstance(key, str) and key.strip():
                return key.strip()
    links = story.get("pr_links")
    if isinstance(links, list) and links:
        link0 = links[0]
        if isinstance(link0, dict):
            repo = link0.get("repo")
            num = link0.get("number")
            if isinstance(repo, str) and isinstance(num, int):
                slug = normalize_repo_slug(repo) or repo.strip()
                return f"{slug}#{num}"
    legacy_repo = story.get("_legacy_issue_repo")
    legacy_number = story.get("_legacy_issue_number")
    if isinstance(legacy_repo, str) and legacy_repo.strip() and isinstance(legacy_number, int):
        slug = normalize_repo_slug(legacy_repo) or legacy_repo.strip()
        return f"{slug}#{legacy_number}"
    ex = _registry_require_execution_repo(story, story_path=story_path)
    return f"{ex}#pending"


def _story_join_primary_template(
    story: dict[str, Any],
    *,
    project_id: str,
    story_path: Path,
    registry_root: Path,
) -> tuple[dict[str, object], list[dict[str, object]] | None]:
    jm = story.get("join_metadata_fixture")
    if not isinstance(jm, dict):
        primary_obj: dict[str, object] = {
            "registry_id": project_id,
            "story_id": str(story.get("story_id") or ""),
            "registry_uuid": str(story.get("registry_uuid") or "") or None,
            "scope_key": (
                f"project/{story.get('project_id')}/epic/{story.get('epic_id')}/story/{story.get('story_id')}"
                if story.get("project_id") and story.get("epic_id") and story.get("story_id")
                else None
            ),
            "execution_issue_key": _story_execution_issue_key(story, story_path),
            "template_id": REGISTRY_PROJECTION_TEMPLATE_ID_DEFAULT,
            "projection_version": _story_projection_version(story),
            "source_registry_path": _story_source_registry_path(registry_root, story_path),
            "shard_count": 1,
        }
        return primary_obj, None
    mode = jm.get("mode")
    primary_raw = jm.get("primary")
    if not isinstance(primary_raw, dict):
        raise JoinMetadataEncodeError("join_metadata_fixture.primary must be a mapping")
    primary: dict[str, object] = {str(k): v for k, v in primary_raw.items()}
    ext = jm.get("extension_shards")
    if mode == "primary_only":
        return primary, None
    if mode == "sharded":
        if not isinstance(ext, list) or not ext:
            raise JoinMetadataEncodeError("sharded join_metadata_fixture requires extension_shards")
        shards = [dict(s) for s in ext if isinstance(s, dict)]
        return primary, shards
    raise JoinMetadataEncodeError(f"unknown join_metadata_fixture.mode: {mode!r}")


def build_registry_join_metadata_block(
    story: dict[str, Any],
    *,
    project_id: str,
    story_path: Path,
    registry_root: Path,
) -> tuple[str, dict[str, Any]]:
    """Return suffix body text (HTML comments) plus a diagnostic dict."""
    primary, ext = _story_join_primary_template(
        story, project_id=project_id, story_path=story_path, registry_root=registry_root
    )
    preimage = build_join_metadata_preimage(primary=primary, extension_shards=ext)
    checksum = join_metadata_checksum_hex(preimage)
    comments = encode_join_metadata_html_comments(preimage, checksum_hex=checksum)
    joined = "\n".join(["", *comments, ""])
    diag: dict[str, Any] = {
        "story_id": story.get("story_id"),
        "shard_blocks": len(comments),
        "checksum_sha256": checksum,
        "preimage_utf8_bytes": len(canonical_json_utf8(preimage)),
        "total_comment_utf8_bytes": sum(len(c.encode("utf-8")) for c in comments),
    }
    try:
        decode_join_metadata_html_comments(comments)
        diag["roundtrip_ok"] = True
    except JoinMetadataEncodeError as exc:
        diag["roundtrip_ok"] = False
        diag["roundtrip_error"] = str(exc)
    return joined, diag


def extract_join_metadata_comments(body: str) -> list[str]:
    return re.findall(
        r"<!--\s*ATLAS_REGISTRY_METADATA(?:_SHARD:\d+/\d+)?:.+?-->",
        body or "",
        flags=re.DOTALL,
    )


def issue_ref_from_url(issue_url: str) -> tuple[str, int] | None:
    match = ISSUE_URL_RE.search(issue_url or "")
    if not match:
        return None
    repo = normalize_repo_slug(match.group("repo")) or match.group("repo")
    return repo, int(match.group("number"))


def rebind_body_execution_issue_key(body: str, *, issue_repo: str, issue_number: int) -> str:
    comments = extract_join_metadata_comments(body)
    if not comments:
        return body
    preimage = decode_join_metadata_html_comments(comments)
    preimage["execution_issue_key"] = f"{normalize_repo_slug(issue_repo) or issue_repo}#{issue_number}"
    checksum = join_metadata_checksum_hex(preimage)
    encoded = encode_join_metadata_html_comments(preimage, checksum_hex=checksum)
    stripped = re.sub(
        r"\n?<!--\s*ATLAS_REGISTRY_METADATA(?:_SHARD:\d+/\d+)?:.+?-->\n?",
        "\n",
        body or "",
        flags=re.DOTALL,
    ).rstrip()
    return "\n".join([stripped, *encoded, ""])


def _sort_stories_for_strategy(
    stories: list[dict[str, Any]], *, strategy: str
) -> list[dict[str, Any]]:
    if strategy == "phases":
        return sorted(stories, key=lambda s: str(s.get("story_id") or ""))
    return sorted(
        stories,
        key=lambda s: (str(s.get("workstream") or ""), str(s.get("story_id") or "")),
    )


def build_registry_plan_execution_context(
    *,
    repo: str | None,
    stories: list[dict[str, Any]],
) -> dict[str, object]:
    dispatch_blockers: list[str] = []
    if not repo:
        dispatch_blockers.append("Missing target repo; pass `--repo` for registry-backed sync.")
    if not stories:
        dispatch_blockers.append("Registry slice contains no stories to project.")
    return {
        "status": "TypedRegistry",
        "current_stage": "WS2-projection",
        "tracking_mode": "registry",
        "blocking_decision": None,
        "unresolved_blockers": None,
        "next_required_user_action": None,
        "dispatch_blocked": bool(dispatch_blockers),
        "dispatch_blockers": dispatch_blockers,
        "recommended_dispatch_mode": "tracking-only" if dispatch_blockers else "review-before-dispatch",
    }


def build_registry_stability_summary(
    *,
    repo: str | None,
    children: list[IssueDraft],
    plan_execution: dict[str, object],
) -> dict[str, object]:
    dispatch_blocked = bool(plan_execution.get("dispatch_blocked"))
    distinct_slugs = distinct_normalized_repo_slugs_from_children(children)
    multi_repo_projection = len(distinct_slugs) > 1
    caveats: list[str] = []
    if multi_repo_projection:
        caveats.append(
            "Registry slice projects across multiple execution repos; verify tokens per repo before sync-apply."
        )
    plan_status = "ready-for-apply" if not dispatch_blocked and not caveats else "needs-attention"
    return {
        "plan_status": plan_status,
        "dispatch_blocked": dispatch_blocked,
        "multi_repo_projection": multi_repo_projection,
        "distinct_execution_repos": distinct_slugs,
        "caveats": caveats,
        "needs_user_input": [] if repo else ["repo"],
    }


def build_registry_epic(
    portfolio: RegistryPortfolioSlice,
    *,
    issue_repo: str | None,
    plan_execution: dict[str, object],
) -> IssueDraft:
    project_id = str(portfolio.project.get("project_id") or "")
    epic_title = str(portfolio.epic.get("title") or portfolio.epic.get("epic_id") or "Epic")
    summary = str(portfolio.project.get("summary") or "").strip()
    epic_id = str(portfolio.epic.get("epic_id") or "")
    repo_targets = normalize_repo_target_values(
        [str(x) for x in portfolio.epic.get("repo_targets") or [] if isinstance(x, str)]
    )
    labels = infer_labels(
        epic_title,
        summary or epic_title,
        "epic",
        project_id,
        repo_targets=repo_targets,
        highest_tier="T4",
    )
    execution_repo, base_branch = resolve_issue_execution_context(
        issue_repo=issue_repo,
        repo_targets=repo_targets,
        default_base_branch=None,
    )
    dispatch_recommendation = (
        "tracking-only"
        if plan_execution["dispatch_blocked"]
        else str(plan_execution.get("recommended_dispatch_mode") or "review-before-dispatch")
    )
    validation_scope = infer_validation_scope(
        title=epic_title,
        excerpt=summary or epic_title,
        gates=[],
        validation_requirements=[],
    )
    risk_tags = infer_risk_tags(
        title=epic_title,
        excerpt=summary or epic_title,
        repo_targets=repo_targets,
        highest_tier="T4",
        blockers=[],
        azure_closeout_only=False,
        issue_ready=True,
        validation_scope=validation_scope,
        gates=[],
    )
    body_lines = [
        "## Source Plan",
        *build_registry_reference_lines(portfolio.registry_root),
        f"- Plan key: `{project_id}`",
        f"- Epic id: `{epic_id}`",
        "",
        "## Summary",
        summary or "No project summary in registry project record.",
        "",
        *build_execution_context_lines(execution_repo, base_branch),
        "## Dispatch Metadata",
        f"- Dispatch recommendation: `{dispatch_recommendation}`",
        f"- Validation scope: `{validation_scope}`",
    ]
    if risk_tags:
        body_lines.append(f"- Risk tags: `{', '.join(risk_tags)}`")
    body_lines.append("")
    if repo_targets:
        body_lines.extend(["## Repo Boundaries", f"- {infer_repo_note(repo_targets)}", ""])
    body_lines.extend(
        [
            "## Notes",
            "- Projected from the typed planning registry slice (WS2).",
            "- Registry YAML remains the local planning authority for structure and routing.",
        ]
    )
    return IssueDraft(
        title=f"[Epic][{project_id}] {epic_title}",
        body="\n".join(body_lines),
        labels=labels,
        kind="epic",
        source_id=epic_id,
        execution_repo=execution_repo,
        base_branch=base_branch,
        repo_targets=repo_targets,
        repo_note=infer_repo_note(repo_targets),
        validation_requirements=[],
        dispatch_recommendation=str(dispatch_recommendation),
        validation_scope=validation_scope,
        risk_tags=risk_tags,
    )


def _capitalize_initial(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        return stripped
    return stripped[0].upper() + stripped[1:]


def workstream_title_prefix(workstream: str) -> str:
    return workstream_label_value(workstream).upper()


def registry_story_display_title(story_id: str, title: str, workstream: str) -> str:
    prefix = workstream_title_prefix(workstream)
    display = re.sub(r"^\s*WS\d+\s+", "", title.strip(), flags=re.IGNORECASE)
    if story_id.endswith("-epic-tracker"):
        display = re.sub(r"\s+epic\s+tracker\s*$", "", display, flags=re.IGNORECASE)
        return f"[{prefix}][Epic] {_capitalize_initial(display)}"
    return f"[{prefix}] {_capitalize_initial(display)}"


def build_registry_story_drafts(
    portfolio: RegistryPortfolioSlice,
    *,
    issue_repo: str | None,
    plan_execution: dict[str, object],
    strategy: str,
) -> tuple[list[IssueDraft], list[dict[str, Any]]]:
    project_id = str(portfolio.project.get("project_id") or "")
    ordered = _sort_stories_for_strategy(portfolio.stories, strategy=strategy)
    join_diagnostics: list[dict[str, Any]] = []
    drafts: list[IssueDraft] = []
    for story in ordered:
        sid = str(story.get("story_id") or "")
        path = portfolio.story_paths[sid]
        title = str(story.get("title") or sid)
        workstream = str(story.get("workstream") or "WS")
        repo_targets = normalize_repo_target_values(
            [str(x) for x in story.get("repo_targets") or [] if isinstance(x, str)]
        )
        gates = [
            str(g.get("gate_id"))
            for g in (story.get("typed_gate_evidence") or [])
            if isinstance(g, dict) and isinstance(g.get("gate_id"), str)
        ]
        execution_repo = _registry_require_execution_repo(story, story_path=path)
        base_branch = lookup_repo_default_branch(execution_repo)
        issue_ready = all(
            str(g.get("status", "")).lower() in {"complete", "completed", "done", "passed"}
            for g in (story.get("typed_gate_evidence") or [])
            if isinstance(g, dict)
        ) if story.get("typed_gate_evidence") else True
        validation_requirements: list[str] = []
        validation_scope = infer_validation_scope(
            title=title,
            excerpt=title,
            gates=gates,
            validation_requirements=validation_requirements,
        )
        risk_tags = infer_risk_tags(
            title=title,
            excerpt=title,
            repo_targets=repo_targets,
            highest_tier=infer_highest_tier(gates),
            blockers=[],
            azure_closeout_only=False,
            issue_ready=issue_ready,
            validation_scope=validation_scope,
            gates=gates,
        )
        points = suggest_points(title, repo_targets, gates)
        automation_blockers: list[str] = point_dispatch_guardrails(points)
        dispatch_recommendation = infer_dispatch_recommendation(
            issue_ready=issue_ready,
            azure_closeout_only=False,
            blockers=[],
            repo_targets=repo_targets,
            validation_scope=validation_scope,
            risk_tags=risk_tags,
            plan_dispatch_blocked=bool(plan_execution["dispatch_blocked"]),
            automation_blockers=automation_blockers,
        )
        status_label = runtime_status_label(
            issue_ready=issue_ready,
            azure_closeout_only=False,
            blockers=[],
            automation_blockers=automation_blockers,
            dispatch_recommendation=dispatch_recommendation,
        )
        priority = infer_priority_value(
            explicit_priority=None,
            title=title,
            excerpt=title,
            highest_tier=infer_highest_tier(gates),
            risk_tags=risk_tags,
            blockers=[],
            automation_blockers=automation_blockers,
            validation_scope=validation_scope,
            gates=gates,
        )
        labels = infer_labels(
            title,
            title,
            "story",
            workstream,
            repo_targets=repo_targets,
            highest_tier=infer_highest_tier(gates),
            status_label=status_label,
            points=points,
            priority=priority,
        )
        meta_suffix, diag = build_registry_join_metadata_block(
            story,
            project_id=project_id,
            story_path=path,
            registry_root=portfolio.registry_root,
        )
        join_diagnostics.append(diag)
        body_lines = [
            "## Source Plan",
            *build_registry_reference_lines(portfolio.registry_root),
            f"- Source section: `{sid}`",
            "",
            "## Suggested Draft Metadata",
            f"- Suggested points: `{points}`",
            f"- Issue ready: `{'true' if status_label == 'status:ready' else 'false'}`",
            f"- Dispatch recommendation: `{dispatch_recommendation}`",
            f"- Validation scope: `{validation_scope}`",
            f"- Priority: `{priority}`",
        ]
        if risk_tags:
            body_lines.append(f"- Risk tags: `{', '.join(risk_tags)}`")
        if repo_targets:
            body_lines.append(f"- Target repo(s): `{', '.join(repo_targets)}`")
        body_lines.append(f"- Execution repo: `{execution_repo}`")
        if base_branch:
            body_lines.append(f"- Base branch: `{base_branch}`")
        if gates:
            body_lines.extend(["## Named Gates", *[f"- `{g}`" for g in gates], ""])
        body_lines.extend(
            build_execution_state_lines(
                open_dependencies=[],
                manual_gates_remaining=[],
            )
        )
        if automation_blockers:
            body_lines.extend(["## Dispatch Guardrails", *[f"- {item}" for item in automation_blockers], ""])
        body_lines.extend(
            [
                "## Registry Story Record",
                f"- Story id: `{sid}`",
                f"- Workstream: `{workstream}`",
                "",
                "## Excerpt",
                "```yaml",
                f"(see {path.name} in registry slice)",
                "```",
                "",
                "## Implementation Notes",
                "- Confirm execution repo and base branch before sync-apply.",
                "- Join metadata HTML comments below are machine-controlled; do not edit by hand.",
            ]
        )
        body = "\n".join(body_lines) + meta_suffix
        drafts.append(
            IssueDraft(
                title=registry_story_display_title(sid, title, workstream),
                body=body,
                labels=labels,
                kind="story",
                source_id=sid,
                execution_repo=execution_repo,
                base_branch=base_branch,
                suggested_points=points,
                merge_points=[],
                gates=gates,
                highest_tier=infer_highest_tier(gates),
                repo_targets=repo_targets,
                repo_note=infer_repo_note(repo_targets),
                validation_requirements=validation_requirements,
                issue_ready=issue_ready,
                status_label=status_label,
                dispatch_recommendation=dispatch_recommendation,
                validation_scope=validation_scope,
                risk_tags=risk_tags,
                automation_blockers=automation_blockers,
                priority=priority,
                legacy_issue_repo=story.get("_legacy_issue_repo"),
                legacy_issue_number=story.get("_legacy_issue_number"),
            )
        )
    return drafts, join_diagnostics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview or create GitHub issues from a plan artifact."
    )
    parser.add_argument("--plan", help="Path to the plan markdown file (markdown mode).")
    parser.add_argument(
        "--registry-root",
        help="Directory of split YAML registry objects (registry mode / WS2 slice).",
    )
    parser.add_argument(
        "--registry-project-id",
        help="Optional project_id selector for split-tree registry roots.",
    )
    parser.add_argument(
        "--registry-epic-id",
        help="Optional epic_id selector for split-tree registry roots.",
    )
    parser.add_argument(
        "--registry-story-id",
        action="append",
        help=(
            "Optional story_id selector for split-tree registry roots. "
            "May be passed multiple times or as a comma/newline-separated list."
        ),
    )
    parser.add_argument(
        "--repo",
        help="Target GitHub repo, e.g. owner/repo. If omitted, use tracking.epicRepo from the plan.",
    )
    parser.add_argument(
        "--strategy",
        choices=("workstreams", "phases", "leaf-issues"),
        default="workstreams",
        help="How to project the plan into child issues.",
    )
    parser.add_argument(
        "--project-owner",
        help="Optional GitHub login or org for `gh project item-add`.",
    )
    parser.add_argument(
        "--project-number",
        type=int,
        help="Optional GitHub Project number for `gh project item-add`.",
    )
    parser.add_argument(
        "--project-url",
        help=(
            "Optional GitHub Project URL, e.g. "
            "https://github.com/orgs/foo/projects/1."
        ),
    )
    parser.add_argument(
        "--existing-issues-file",
        help="Optional JSON file of existing issues for sync-preview tests.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Print the projected issues only.")
    mode.add_argument("--apply", action="store_true", help="Create issues with gh.")
    mode.add_argument(
        "--sync-preview",
        action="store_true",
        help="Compare projected issues against existing GitHub issues and print a sync preview.",
    )
    mode.add_argument(
        "--sync-apply",
        action="store_true",
        help="Update matching GitHub issues in place and create missing projected issues.",
    )
    return parser.parse_args()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def find_repo_root(path: Path) -> Path | None:
    search_root = path if path.is_dir() else path.parent
    for candidate in [search_root, *search_root.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


def run_git(args: list[str], cwd: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return result.stdout.strip() or None


def resolve_repo_root(path: Path) -> Path | None:
    root = run_git(["rev-parse", "--show-toplevel"], cwd=path.parent)
    if root:
        return Path(root).resolve()
    return find_repo_root(path)


def normalize_github_remote(remote_url: str | None) -> str | None:
    if not remote_url:
        return None
    remote_url = remote_url.strip()
    if remote_url.startswith("git@github.com:"):
        remote_url = "https://github.com/" + remote_url[len("git@github.com:") :]
    if remote_url.endswith(".git"):
        remote_url = remote_url[:-4]
    if remote_url.startswith("https://github.com/"):
        return remote_url
    return None


def remote_repo_slug(remote_url: str | None) -> str | None:
    normalized = normalize_github_remote(remote_url)
    if not normalized:
        return None
    return normalized.removeprefix("https://github.com/")


def normalize_repo_slug(repo: str | None) -> str | None:
    if not repo:
        return None
    cleaned = repo.strip().strip("/")
    if cleaned.startswith("https://github.com/"):
        cleaned = cleaned.removeprefix("https://github.com/").strip("/")
    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]
    aliased = REPO_SLUG_ALIASES.get(cleaned.lower())
    if aliased:
        return aliased
    if cleaned.count("/") == 1:
        return cleaned
    return REPO_SLUG_ALIASES.get(cleaned.lower())


def infer_default_branch(repo_root: Path) -> str:
    head_ref = run_git(["symbolic-ref", "refs/remotes/origin/HEAD"], cwd=repo_root)
    if head_ref and head_ref.startswith("refs/remotes/origin/"):
        return head_ref.removeprefix("refs/remotes/origin/")
    return "main"


def infer_source_ref(repo_root: Path) -> str:
    """Prefer the checked-out authoring ref for source links, falling back to commit/default."""
    branch = run_git(["branch", "--show-current"], cwd=repo_root)
    if branch:
        return branch
    commit = run_git(["rev-parse", "HEAD"], cwd=repo_root)
    if commit:
        return commit
    return infer_default_branch(repo_root)


def build_plan_reference_lines(plan_path: Path, *, include_execution_note: bool = False) -> list[str]:
    _, relative_plan_path, canonical_plan_url = plan_reference_context(plan_path)
    repo_root = resolve_repo_root(plan_path)
    source_repo_slug = None
    if repo_root:
        origin_remote = run_git(["config", "--get", "remote.origin.url"], cwd=repo_root)
        source_repo_slug = remote_repo_slug(origin_remote)
    lines = []
    if source_repo_slug:
        lines.append(f"- Source repo: `{source_repo_slug}`")
    lines.append(f"- Plan path: `{relative_plan_path}`")
    if canonical_plan_url:
        lines.append(f"- Canonical plan URL: {canonical_plan_url}")
    if include_execution_note:
        lines.append(
            "- Execution note: if this issue lives outside the source repo, use the exact source "
            "repo/path above and do not substitute another local harness plan file."
        )
    return lines


def plan_reference_context(plan_path: Path) -> tuple[str | None, str, str | None]:
    repo_root = resolve_repo_root(plan_path)
    relative_plan_path = plan_path.name
    source_repo_slug = None
    canonical_plan_url = None

    if repo_root:
        try:
            relative_plan_path = plan_path.relative_to(repo_root).as_posix()
        except ValueError:
            relative_plan_path = plan_path.name
        origin_remote = run_git(["config", "--get", "remote.origin.url"], cwd=repo_root)
        source_repo_slug = remote_repo_slug(origin_remote)
        normalized_remote = normalize_github_remote(origin_remote)
        if normalized_remote:
            source_ref = infer_source_ref(repo_root)
            canonical_plan_url = f"{normalized_remote}/blob/{source_ref}/{relative_plan_path}"
    return source_repo_slug, relative_plan_path, canonical_plan_url


def normalize_branch_field(values: list[str]) -> str | None:
    if not values:
        return None
    value = values[-1].replace("`", "").strip()
    return value or None


def infer_issue_execution_repo(issue_repo: str | None, repo_targets: list[str]) -> str | None:
    normalized_issue_repo = normalize_repo_slug(issue_repo)
    normalized_targets = normalize_repo_target_values(repo_targets)
    if len(normalized_targets) == 1:
        normalized_target_repo = normalized_targets[0]
        if normalized_issue_repo and normalized_target_repo == normalized_issue_repo:
            return normalized_issue_repo
        if (
            normalized_issue_repo
            and repo_component_for_issue_repo(issue_repo)
            == repo_component_for_issue_repo(normalized_target_repo)
        ):
            return normalized_issue_repo
        return normalized_target_repo
    if normalized_issue_repo:
        for normalized_target in normalized_targets:
            if normalized_target == normalized_issue_repo:
                return normalized_issue_repo
            if repo_component_for_issue_repo(normalized_target) == repo_component_for_issue_repo(
                normalized_issue_repo
            ):
                return normalized_issue_repo
    if not normalized_issue_repo and len(normalized_targets) > 1:
        return None
    if normalized_targets:
        return normalized_targets[0]
    return normalized_issue_repo


def lookup_repo_default_branch(repo: str | None) -> str | None:
    repo_slug = normalize_repo_slug(repo)
    if not repo_slug:
        return None
    hinted = DEFAULT_BRANCH_HINTS.get(repo_slug)
    if hinted:
        return hinted
    try:
        result = subprocess.run(
            [
                "gh",
                "repo",
                "view",
                repo_slug,
                "--json",
                "defaultBranchRef",
                "--jq",
                ".defaultBranchRef.name",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    branch = result.stdout.strip()
    return branch or None


def resolve_issue_execution_context(
    *,
    issue_repo: str | None,
    repo_targets: list[str],
    explicit_execution_repo: str | None = None,
    explicit_base_branch: str | None = None,
    default_base_branch: str | None = None,
) -> tuple[str | None, str | None]:
    execution_repo = normalize_repo_slug(explicit_execution_repo) or infer_issue_execution_repo(issue_repo, repo_targets)
    base_branch = explicit_base_branch or default_base_branch
    if not base_branch:
        base_branch = lookup_repo_default_branch(execution_repo)
    return execution_repo, base_branch


def build_execution_context_lines(execution_repo: str | None, base_branch: str | None) -> list[str]:
    if not execution_repo and not base_branch:
        return []
    lines = ["## Agent Execution Context"]
    if execution_repo:
        lines.append(f"- Execution repo: `{execution_repo}`")
    if base_branch:
        lines.append(f"- Base branch: `{base_branch}`")
        lines.append(
            "- PR rule: create follow-up PRs against the explicit base branch above; do not infer from local checkout state, `origin/HEAD`, or fallback-to-`main` behavior."
        )
    return [*lines, ""]


def display_plan_path(path: Path) -> str:
    _, relative_plan_path, _ = plan_reference_context(path)
    return relative_plan_path


def _clean_frontmatter_scalar(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1]
    return text


def _parse_scalar_frontmatter_block(block: str) -> dict[str, object]:
    """Small YAML subset fallback for scalar frontmatter used by plan metadata."""
    data: dict[str, object] = {}
    current_parent: str | None = None
    current_multiline_key: str | None = None
    current_multiline_indent = 0
    current_multiline_lines: list[str] = []

    def flush_multiline() -> None:
        nonlocal current_multiline_key, current_multiline_lines
        if current_multiline_key is not None:
            data[current_multiline_key] = "\n".join(current_multiline_lines).rstrip()
        current_multiline_key = None
        current_multiline_lines = []

    for raw_line in block.splitlines():
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        if current_multiline_key is not None:
            if not line:
                current_multiline_lines.append("")
                continue
            if indent >= current_multiline_indent:
                current_multiline_lines.append(raw_line[current_multiline_indent:])
                continue
            flush_multiline()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if indent == 0:
            current_parent = key if not value else None
            if value in {"|", ">"}:
                current_multiline_key = key
                current_multiline_indent = indent + 2
                current_multiline_lines = []
            elif value:
                data[key] = _clean_frontmatter_scalar(value)
            continue
        if current_parent:
            data.setdefault(current_parent, {})
            parent = data[current_parent]
            if isinstance(parent, dict):
                parent[key] = _clean_frontmatter_scalar(value)
    flush_multiline()
    return data


def _flatten_frontmatter(data: Mapping[str, object]) -> dict[str, str]:
    frontmatter: dict[str, str] = {}
    for key in ("name", "overview", "summary", "ProjectionWorkstreamLabel", "projectionWorkstreamLabel"):
        value = data.get(key)
        scalar = _clean_frontmatter_scalar(value)
        if scalar:
            frontmatter[key] = scalar
    tracking = data.get("tracking")
    if isinstance(tracking, Mapping):
        for key, value in tracking.items():
            scalar = _clean_frontmatter_scalar(value)
            if scalar:
                frontmatter[f"tracking.{key}"] = scalar
    if "overview" not in frontmatter and frontmatter.get("summary"):
        frontmatter["overview"] = frontmatter["summary"]
    return frontmatter


def parse_frontmatter(text: str) -> dict[str, str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}
    block = match.group(1)
    try:
        yaml = _require_yaml()
        parsed = yaml.safe_load(block)  # type: ignore[attr-defined]
    except SystemExit:
        parsed = _parse_scalar_frontmatter_block(block)
    if not isinstance(parsed, Mapping):
        return {}
    return _flatten_frontmatter(parsed)


def strip_frontmatter(text: str) -> str:
    return FRONTMATTER_RE.sub("", text, count=1)


def first_heading(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return "Plan"


def extract_plan_state_value(text: str, field_name: str) -> str | None:
    pattern = re.compile(rf"^{re.escape(field_name)}:\s*(.+)$", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return None
    value = match.group(1).strip().strip("`")
    return value or None


def infer_plan_key(*values: str) -> str:
    for value in values:
        match = PLAN_ID_RE.search(value or "")
        if match:
            return match.group(1).upper()
    for value in values:
        raw = (value or "").strip()
        if not raw:
            continue
        candidate = Path(raw).stem
        candidate = re.sub(r"^\s*feature:\s*", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\.plan$", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"[-_ ]20\d{2}(?:[-_]\d{2}){2}$", "", candidate)
        candidate = re.sub(r"[-_ ][0-9a-f]{8}$", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"[^A-Za-z0-9]+", "-", candidate).strip("-").upper()
        if candidate:
            return candidate
    return "PLAN"


def collect_sections(lines: list[str], heading_re: re.Pattern[str]) -> list[tuple[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = []
    current_title: str | None = None
    current_body: list[str] = []

    def flush() -> None:
        nonlocal current_title, current_body
        if current_title is not None:
            sections.append((current_title, current_body[:]))
        current_title = None
        current_body = []

    for line in lines:
        if line.startswith("## "):
            flush()
            continue
        heading_match = heading_re.match(line)
        if heading_match:
            flush()
            current_title = heading_match.group(1).strip()
            continue
        if current_title is not None:
            current_body.append(line)
    flush()
    return sections


def collect_bullet_sections(
    lines: list[str],
    *,
    section_heading: str,
    bullet_re: re.Pattern[str],
) -> list[tuple[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = []
    current_title: str | None = None
    current_body: list[str] = []
    in_target_section = False

    def flush() -> None:
        nonlocal current_title, current_body
        if current_title is not None:
            sections.append((current_title, current_body[:]))
        current_title = None
        current_body = []

    for line in lines:
        if line.startswith("### "):
            if in_target_section:
                flush()
            in_target_section = line == section_heading
            continue
        if not in_target_section:
            continue
        bullet_match = bullet_re.match(line)
        if bullet_match:
            flush()
            source_id = bullet_match.group(1).upper()
            summary = bullet_match.group(2).strip()
            current_title = f"{source_id} {summary}"
            continue
        if current_title is not None:
            current_body.append(line)
    flush()
    return sections


def _is_crosswalk_workstream_heading(title: str) -> bool:
    """True for subsection titles like `WS2 -> WS3 -> WS4 Status Mapping` that match WORKSTREAM_HEADING_RE but are not workstreams."""
    return "->" in title


def collect_workstream_sections(lines: list[str]) -> list[tuple[str, list[str]]]:
    """
    Resolve workstream child sections for issue projection.

    Prefer bullet workstreams under WORKSTREAMS_SECTION_HEADING when that block defines at least
    one workstream; otherwise fall back to ### WS*-style headings. Cross-walk headings that
    mention multiple workstreams with `->` are excluded from the heading fallback.
    """
    bullet_sections = collect_bullet_sections(
        lines,
        section_heading=WORKSTREAMS_SECTION_HEADING,
        bullet_re=WORKSTREAM_BULLET_RE,
    )
    if bullet_sections:
        return bullet_sections
    heading_sections = collect_sections(lines, WORKSTREAM_HEADING_RE)
    return [
        (title, body)
        for title, body in heading_sections
        if not _is_crosswalk_workstream_heading(title)
    ]


def collect_automation_manifest_sections(lines: list[str]) -> list[tuple[str, list[str]]]:
    canonical_sections = collect_bullet_sections(
        lines,
        section_heading=AUTOMATION_MANIFEST_SECTION_HEADING,
        bullet_re=MANIFEST_LEAF_BULLET_RE,
    )
    if canonical_sections:
        return canonical_sections
    return collect_bullet_sections(
        lines,
        section_heading=MANIFEST_LEAF_SECTION_HEADING,
        bullet_re=MANIFEST_LEAF_BULLET_RE,
    )


def normalize_excerpt(lines: Iterable[str], limit: int = 28) -> str:
    cleaned = [line.rstrip() for line in lines]
    while cleaned and not cleaned[0].strip():
        cleaned.pop(0)
    while cleaned and not cleaned[-1].strip():
        cleaned.pop()
    if len(cleaned) > limit:
        cleaned = cleaned[:limit] + ["...", "(truncated)"]
    return "\n".join(cleaned).strip()


def extract_source_id(title: str, fallback: str) -> str:
    match = re.search(rf"\b({WORKSTREAM_ID_PATTERN})\b", title, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    return fallback


def ordered_unique(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


def shorten_label_name(label: str, *, max_length: int = GITHUB_LABEL_NAME_MAX_LENGTH) -> str:
    """Return a deterministic GitHub label name within GitHub's 50-character limit."""
    if len(label) <= max_length:
        return label
    digest = hashlib.sha1(label.encode("utf-8")).hexdigest()[:LABEL_DIGEST_LENGTH]
    suffix = f"-{digest}"
    prefix = ""
    token = label
    if ":" in label:
        prefix, token = label.split(":", 1)
        prefix = f"{prefix}:"
    token_budget = max_length - len(prefix) - len(suffix)
    if token_budget <= 0:
        return f"{label[: max_length - len(suffix)]}{suffix}"
    shortened_token = token[:token_budget].rstrip("-_:.")
    if not shortened_token:
        shortened_token = token[:token_budget]
    return f"{prefix}{shortened_token}{suffix}"


def normalize_label_names(labels: Iterable[str]) -> list[str]:
    return sorted(set(shorten_label_name(label) for label in labels if label))


def projection_workstream_label_scope(frontmatter: Mapping[str, str], fallback: str) -> str:
    for key in (
        "ProjectionWorkstreamLabel",
        "projectionWorkstreamLabel",
        "tracking.ProjectionWorkstreamLabel",
        "tracking.projectionWorkstreamLabel",
        "tracking.workstreamLabel",
    ):
        value = frontmatter.get(key)
        if value and value.strip():
            return value.strip()
    return fallback


def split_csv_values(values: list[str]) -> list[str]:
    items: list[str] = []
    for value in values:
        for part in value.split(","):
            cleaned = part.replace("`", "").strip()
            if cleaned:
                items.append(cleaned)
    return ordered_unique(items)


def parse_bool_field(values: list[str], default: bool = True) -> bool:
    if not values:
        return default
    value = values[-1].replace("`", "").strip().lower()
    if value in {"true", "yes", "y", "ready"}:
        return True
    if value in {"false", "no", "n", "draft", "blocked", "hold"}:
        return False
    return default


def get_field_values(fields: dict[str, list[str]], *prefixes: str) -> list[str]:
    values: list[str] = []
    normalized_prefixes = tuple(prefix.strip().lower() for prefix in prefixes if prefix.strip())
    for key, key_values in fields.items():
        normalized_key = key.strip().lower()
        if any(
            normalized_key == prefix or normalized_key.startswith(f"{prefix} ")
            or normalized_key.startswith(f"{prefix}(") or normalized_key.startswith(f"{prefix} /")
            for prefix in normalized_prefixes
        ):
            values.extend(key_values)
    return values


def normalize_repo_target_values(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in split_csv_values(values):
        repo = normalize_repo_slug(value) or value
        normalized.append(repo)
    return ordered_unique(normalized)


def normalize_highest_tier(values: list[str]) -> str | None:
    if not values:
        return None
    value = values[-1].replace("`", "").strip().upper()
    return value if re.fullmatch(r"T[0-6]", value) else None


def normalize_blocker_values(values: list[str]) -> list[str]:
    return analyze_blocker_values(values).blockers


def child_display_title(title: str, source_id: str) -> str:
    prefix = f"{source_id} "
    if title.startswith(prefix):
        return title[len(prefix) :].strip()
    return title


def status_label_for_issue(
    *,
    issue_ready: bool,
    azure_closeout_only: bool,
    explicit_blockers: list[str],
) -> str:
    if azure_closeout_only or not issue_ready:
        return "status:draft"
    if explicit_blockers:
        return "status:blocked"
    return "status:ready"


def normalize_dispatch_mode(values: list[str], *, default: str = "manual-review") -> str:
    if not values:
        return default
    value = values[-1].replace("`", "").strip().lower()
    aliases = {
        "agent-ready": "agent-ready",
        "auto": "agent-ready",
        "auto-dispatch": "agent-ready",
        "dispatch": "agent-ready",
        "review": "manual-review",
        "review-before-dispatch": "manual-review",
        "manual": "manual-review",
        "manual-review": "manual-review",
        "tracking": "tracking-only",
        "tracking-only": "tracking-only",
        "blocked": "blocked",
        "dry-run-only": "tracking-only",
    }
    return aliases.get(value, default)


def dispatch_recommendation_for_manifest_mode(
    mode: str,
    inferred: str,
) -> str:
    if inferred == "tracking-only":
        return "tracking-only"
    if mode == "agent-ready":
        return inferred
    if mode == "manual-review":
        return "review-before-dispatch"
    return "tracking-only"


def point_dispatch_guardrails(points: int | None) -> list[str]:
    if points is not None and points > 1:
        return [f"Decompose `points:{points}` issue into one-point child issues before local automation dispatch."]
    return []


def requires_decomposition(points: int | None, automation_blockers: Iterable[str] = ()) -> bool:
    return bool(points is not None and points > 1) or any(
        blocker.startswith("Decompose `points:") for blocker in automation_blockers
    )


def effective_issue_ready(
    issue_ready: bool,
    points: int | None,
    automation_blockers: Iterable[str] = (),
) -> bool:
    """Return the machine-readable readiness after dispatch guardrails apply."""
    if requires_decomposition(points, automation_blockers):
        return False
    return issue_ready


def non_decomposition_automation_blockers(
    automation_blockers: Iterable[str],
) -> list[str]:
    return [
        blocker
        for blocker in automation_blockers
        if not blocker.startswith("Decompose `points:")
    ]


def runtime_status_label(
    *,
    issue_ready: bool,
    azure_closeout_only: bool,
    blockers: list[str],
    automation_blockers: list[str],
    dispatch_recommendation: str,
) -> str:
    if azure_closeout_only or not issue_ready:
        return "status:draft"
    if blockers or non_decomposition_automation_blockers(automation_blockers):
        return "status:blocked"
    if dispatch_recommendation in {"auto-dispatch", "auto-dispatch-pilot"}:
        return "status:ready"
    return "status:draft"


def effective_dispatch_mode(
    requested_mode: str | None,
    *,
    issue_ready: bool,
    blockers: list[str],
    automation_blockers: list[str],
) -> str | None:
    if requested_mode is None:
        return None
    if requested_mode == "blocked":
        return "tracking-only"
    if not issue_ready or blockers or automation_blockers:
        return "tracking-only"
    return requested_mode


def runtime_field_value(values: list[str]) -> str:
    cleaned = ordered_unique([value.replace("`", "").strip() for value in values if value.strip()])
    return "none" if not cleaned else "; ".join(cleaned)


def clean_manifest_field_value(value: str) -> str:
    return value.replace("`", "").strip()


def clean_optional_manifest_scalar(values: list[str]) -> str | None:
    cleaned = [
        clean_manifest_field_value(value)
        for value in values
        if clean_manifest_field_value(value)
    ]
    if not cleaned:
        return None
    value = cleaned[-1]
    return None if value.lower() in {"none", "n/a", "na"} else value


def normalize_agent_type(values: list[str]) -> str | None:
    value = clean_optional_manifest_scalar(values)
    if value in ALLOWED_AGENT_TYPES:
        return value
    return None


def clean_manifest_list_values(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    for value in split_csv_values(values):
        item = clean_manifest_field_value(value)
        if item and item.lower() not in {"none", "n/a", "na"}:
            cleaned.append(item)
    return ordered_unique(cleaned)


def build_execution_state_lines(
    *,
    open_dependencies: list[str],
    manual_gates_remaining: list[str],
) -> list[str]:
    return [
        "## Execution State",
        f"- Open dependencies: `{runtime_field_value(open_dependencies)}`",
        f"- Manual gates remaining: `{runtime_field_value(manual_gates_remaining)}`",
        "",
    ]


def parse_int_value(value: str | None) -> int | None:
    if value is None:
        return None
    match = re.search(r"-?\d+", value)
    if not match:
        return None
    return int(match.group(0))


def normalize_points_value(value: str | None) -> int | None:
    points = parse_int_value(value)
    if points in ALLOWED_POINT_VALUES:
        return points
    return None


def explicit_points_from_lines(lines: list[str]) -> int | None:
    values = collect_field_values(lines, "points", "story points", "suggested points")
    for value in reversed(values):
        points = normalize_points_value(value)
        if points is not None:
            return points
    return None


def points_for_issue(title: str, repo_targets: list[str], gates: list[str], lines: list[str]) -> int:
    return explicit_points_from_lines(lines) or suggest_points(title, repo_targets, gates)


def should_block_dispatch(next_required_user_action: str | None) -> bool:
    if not next_required_user_action:
        return False
    lowered = next_required_user_action.lower()
    blocking_phrases = (
        "do not",
        "before apply mode",
        "apply mode remains blocked",
        "issue materialization until",
        "issue apply deferred until",
        "keep issue apply deferred",
        "do not start p5",
        "defer issue apply",
        "dry-run only",
    )
    return any(phrase in lowered for phrase in blocking_phrases)


def build_plan_execution_context(
    *,
    frontmatter: dict[str, str],
    markdown: str,
    repo: str | None,
    sections: list[tuple[str, list[str]]],
) -> dict[str, object]:
    status = extract_plan_state_value(markdown, "Status")
    current_stage = extract_plan_state_value(markdown, "CurrentStage")
    next_required_user_action = extract_plan_state_value(markdown, "NextRequiredUserAction")
    blocking_decision = extract_plan_state_value(markdown, "BlockingDecision")
    unresolved_blockers = parse_int_value(extract_plan_state_value(markdown, "UnresolvedBlockers"))
    explicit_dispatch_policy = (
        extract_plan_state_value(markdown, "DispatchAllowed")
        or frontmatter.get("tracking.dispatchPolicy")
        or ""
    ).strip().lower()

    dispatch_blockers: list[str] = []
    if not repo:
        dispatch_blockers.append("Missing target repo; add `tracking.epicRepo` or pass `--repo`.")
    if not sections:
        dispatch_blockers.append("No projectable workstreams, phases, or manifest leaves were found.")
    if unresolved_blockers and unresolved_blockers > 0:
        dispatch_blockers.append(
            f"Plan state reports `{unresolved_blockers}` unresolved blocker(s)."
        )
    if blocking_decision and blocking_decision.lower() not in {"none", "n/a", "na"}:
        dispatch_blockers.append(
            f"BlockingDecision is still set to `{blocking_decision}`."
        )
    if should_block_dispatch(next_required_user_action):
        dispatch_blockers.append(
            "NextRequiredUserAction keeps issue apply/dispatch blocked until upstream steps finish."
        )
    if explicit_dispatch_policy in {"tracking-only", "blocked", "dry-run-only"}:
        dispatch_blockers.append(
            f"Dispatch policy explicitly set to `{explicit_dispatch_policy}`."
        )

    review_required = explicit_dispatch_policy in {
        "review-before-dispatch",
        "review-required",
    }
    recommended_dispatch_mode = (
        "tracking-only"
        if dispatch_blockers
        else "review-before-dispatch" if review_required else "dispatch-eligible"
    )

    return {
        "status": status,
        "current_stage": current_stage,
        "tracking_mode": frontmatter.get("tracking.mode"),
        "blocking_decision": blocking_decision,
        "unresolved_blockers": unresolved_blockers,
        "next_required_user_action": next_required_user_action,
        "dispatch_blocked": bool(dispatch_blockers),
        "dispatch_blockers": dispatch_blockers,
        "recommended_dispatch_mode": recommended_dispatch_mode,
    }


def build_stability_summary(
    *,
    repo: str | None,
    sections: list[tuple[str, list[str]]],
    children: list[IssueDraft],
    explicit_blockers: dict[str, str],
    plan_execution: dict[str, object],
) -> dict[str, object]:
    needs_user_input: list[str] = []
    if not repo:
        needs_user_input.append("tracking.epicRepo")
    if not sections:
        needs_user_input.append("projectable_sections")

    unstable_items: list[str] = []
    for child in children:
        if child.azure_closeout_only:
            unstable_items.append(
                f"{child.source_id} is Azure-closeout-only and should stay draft-tracked until upstream proof is green."
            )
        elif not child.issue_ready:
            blocker_suffix = (
                f" Blocked by: {', '.join(child.blockers)}." if child.blockers else ""
            )
            unstable_items.append(
                f"{child.source_id} is draft-only for issue projection.{blocker_suffix}"
            )

    dispatch_blocked = bool(plan_execution.get("dispatch_blocked"))
    distinct_slugs = distinct_normalized_repo_slugs_from_children(children)
    multi_repo_projection = len(distinct_slugs) > 1

    caveats: list[str] = []
    if dispatch_blocked and not needs_user_input:
        caveats.append(
            "Plan metadata or policy still blocks issue dispatch/apply; see plan_execution.dispatch_blockers "
            "and per-issue dispatch recommendations before using apply mode."
        )
    if multi_repo_projection and not needs_user_input:
        caveats.append(
            "Projected children normalize to multiple distinct GitHub repos; apply/sync use each child's "
            "`execution_repo` when present (otherwise the epic repo). Confirm repo targets, tokens, and "
            "project membership before apply; dry-run alone does not prove cross-repo permissions."
        )

    if needs_user_input:
        plan_status = "needs-user-input"
    elif dispatch_blocked:
        plan_status = "dispatch-blocked"
    elif multi_repo_projection:
        plan_status = "multi-repo-preview"
    else:
        plan_status = "ready-for-apply"

    return {
        "plan_status": plan_status,
        "needs_user_input": needs_user_input,
        "explicit_blockers": explicit_blockers,
        "unstable_items": unstable_items,
        "dispatch_blocked": dispatch_blocked,
        "multi_repo_projection": multi_repo_projection,
        "distinct_child_repo_slugs": distinct_slugs,
        "caveats": caveats,
    }


def infer_validation_scope(
    *,
    title: str,
    excerpt: str,
    gates: list[str],
    validation_requirements: list[str],
) -> str:
    joined = "\n".join([title, excerpt, *gates, *validation_requirements]).lower()
    if any(
        token in joined
        for token in (
            "hosted_base_url",
            "e2e_api_key",
            "deployed",
            "hosted",
            "workflow_dispatch",
            "apim",
            "release-candidate",
            "environment:",
        )
    ):
        return "deployed"
    if any(token in joined for token in ("ci", "pytest", "build", "lint", "unit test")):
        return "ci"
    return "local"


def highest_tier_level(highest_tier: str | None) -> int | None:
    if not highest_tier:
        return None
    match = re.search(r"(\d+)", highest_tier)
    if not match:
        return None
    return int(match.group(1))


def infer_risk_tags(
    *,
    title: str,
    excerpt: str,
    repo_targets: list[str],
    highest_tier: str | None,
    blockers: list[str],
    azure_closeout_only: bool,
    issue_ready: bool,
    validation_scope: str,
    gates: list[str],
) -> list[str]:
    joined = "\n".join([title, excerpt, *gates]).lower()
    tags: list[str] = []
    if len(repo_targets) > 1:
        tags.append("cross-repo")
    tier_level = highest_tier_level(highest_tier)
    if tier_level is not None and tier_level >= 4:
        tags.append("tier:t4+")
    if validation_scope == "deployed":
        tags.append("needs-deployed-validation")
    elif validation_scope == "ci":
        tags.append("needs-ci-validation")
    if blockers:
        tags.append("blocked-by-upstream")
    if any(MERGE_POINT_RE.fullmatch(token) for token in blockers):
        tags.append("merge-point-dependency")
    if azure_closeout_only:
        tags.append("azure-closeout-only")
    if not issue_ready:
        tags.append("draft-only")
    if any(token in joined for token in ("infra", "bicep", "apim", "gateway", "routing")):
        tags.append("infra")
    if any(token in joined for token in ("github actions", "ci/cd", "cicd", "deploy")):
        tags.append("ci-cd")
    if any(token in joined for token in ("migration", "postgres", "alembic", "schema")):
        tags.append("migration")
    if any(token in joined for token in ("auth", "jwt", "identity", "entra", "tenant")):
        tags.append("auth")
    if any(token in joined for token in ("admin ui", "chainlit", "ui")):
        tags.append("ui-surface")
    return ordered_unique(tags)


def infer_dispatch_recommendation(
    *,
    issue_ready: bool,
    azure_closeout_only: bool,
    blockers: list[str],
    repo_targets: list[str],
    validation_scope: str,
    risk_tags: list[str],
    plan_dispatch_blocked: bool,
    automation_blockers: list[str],
) -> str:
    if plan_dispatch_blocked or not issue_ready or azure_closeout_only or blockers or automation_blockers:
        return "tracking-only"
    if len(repo_targets) != 1:
        return "review-before-dispatch"
    if validation_scope == "deployed":
        return "review-before-dispatch"
    if any(tag in risk_tags for tag in ("infra", "ci-cd", "migration", "auth", "tier:t4+")):
        return "review-before-dispatch"
    return "auto-dispatch"


def normalize_priority_value(value: str | None) -> str | None:
    if value is None:
        return None
    token = value.replace("`", "").strip().lower()
    if not token or token in {"none", "n/a", "na"}:
        return None
    aliases = {
        "critical": "P0",
        "blocker": "P0",
        "highest": "P0",
        "high": "P1",
        "urgent": "P1",
        "medium": "P2",
        "normal": "P2",
        "default": "P2",
        "low": "P3",
    }
    if token in aliases:
        return aliases[token]
    match = re.search(r"\bp([0-3])\b", token, flags=re.IGNORECASE)
    if match:
        return f"P{match.group(1)}"
    numeric = parse_int_value(token)
    if numeric is not None and 0 <= numeric <= 3:
        return f"P{numeric}"
    return None


def explicit_priority_from_lines(lines: list[str]) -> str | None:
    for value in reversed(collect_field_values(lines, "priority", "issue priority")):
        priority = normalize_priority_value(value)
        if priority:
            return priority
    return None


def infer_priority_value(
    *,
    explicit_priority: str | None,
    title: str,
    excerpt: str,
    highest_tier: str | None,
    risk_tags: list[str],
    blockers: list[str],
    automation_blockers: list[str],
    validation_scope: str,
    gates: list[str],
) -> str:
    if explicit_priority:
        return explicit_priority
    joined = "\n".join([title, excerpt, *gates]).lower()
    if any(token in joined for token in ("critical", "blocker", "sev0", "severity 0")):
        return "P1"
    tier_level = highest_tier_level(highest_tier)
    high_risk_tags = {"auth", "secrets", "migration", "cross-repo", "needs-deployed-validation"}
    if tier_level is not None and tier_level <= 1:
        return "P1"
    if tier_level is not None and tier_level <= 3:
        return "P2"
    if tier_level is not None:
        return "P3"
    if set(risk_tags) & high_risk_tags or validation_scope == "deployed":
        return "P1"
    if blockers or automation_blockers:
        return "P2"
    return "P2"


def parse_named_items(pattern: re.Pattern[str], text: str) -> dict[str, str]:
    return {match.group(1): match.group(2).strip() for match in pattern.finditer(text)}


def parse_section_fields(lines: list[str]) -> dict[str, list[str]]:
    fields: dict[str, list[str]] = {}
    for line in lines:
        match = FIELD_LINE_RE.match(line)
        if not match:
            continue
        key = match.group("key").strip().lower()
        value = match.group("value").strip()
        fields.setdefault(key, []).append(value)
    return fields


def collect_field_values(lines: list[str], *prefixes: str) -> list[str]:
    values: list[str] = []
    normalized_prefixes = tuple(prefix.strip().lower() for prefix in prefixes if prefix.strip())
    current_indent: int | None = None
    collecting = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if collecting and current_indent is not None:
            child_indent = len(line) - len(line.lstrip())
            if child_indent > current_indent and stripped.startswith("-"):
                child_match = re.match(r"^\s*-\s+(.+)$", line)
                if child_match:
                    values.append(child_match.group(1).strip())
                    continue
            if child_indent <= current_indent and stripped.startswith("-"):
                collecting = False
                current_indent = None

        field_match = re.match(r"^(?P<indent>\s*)-\s+(?P<key>[^:]+):\s*(?P<value>.*)$", line)
        if field_match:
            key = field_match.group("key").strip().lower()
            value = field_match.group("value").strip()
            indent = len(field_match.group("indent"))
            matched_prefix = next(
                (
                    prefix
                    for prefix in normalized_prefixes
                    if key == prefix
                    or key.startswith(f"{prefix} ")
                    or key.startswith(f"{prefix}(")
                    or key.startswith(f"{prefix} /")
                ),
                None,
            )
            if matched_prefix is not None:
                if value:
                    values.append(value)
                    collecting = False
                    current_indent = None
                else:
                    collecting = True
                    current_indent = indent
                continue
            collecting = False
            current_indent = None

    return values


def field_declared(lines: list[str], *prefixes: str) -> bool:
    normalized_prefixes = tuple(prefix.strip().lower() for prefix in prefixes if prefix.strip())
    for line in lines:
        field_match = re.match(r"^(?P<indent>\s*)-\s+(?P<key>[^:]+):\s*(?P<value>.*)$", line)
        if not field_match:
            continue
        key = field_match.group("key").strip().lower()
        if any(
            key == prefix
            or key.startswith(f"{prefix} ")
            or key.startswith(f"{prefix}(")
            or key.startswith(f"{prefix} /")
            for prefix in normalized_prefixes
        ):
            return True
    return False


def extract_review_gates_from_workstream_lines(lines: list[str]) -> list[str]:
    """Collect `G-*` gate ids from nested bullets under `Review gates (...):`."""
    gates: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        match = REVIEW_GATES_HEADER_RE.match(line)
        if not match:
            i += 1
            continue
        rest = match.group("rest").strip()
        header_indent = len(match.group("indent"))
        if rest:
            gates.extend(extract_tokens(rest, GATE_RE))
            i += 1
            continue
        i += 1
        while i < len(lines):
            child = lines[i]
            if not child.strip():
                i += 1
                continue
            child_indent = len(child) - len(child.lstrip())
            if child_indent <= header_indent and child.strip().startswith("-"):
                break
            gates.extend(extract_tokens(child, GATE_RE))
            i += 1
    return ordered_unique(gates)


def extract_owned_file_repo_targets(lines: list[str]) -> list[str]:
    """Collect repo targets from nested bullets under `Owns files:`."""
    repos: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if not re.match(r"^(?P<indent>\s*)-\s+Owns files:\s*$", line, re.IGNORECASE):
            i += 1
            continue
        header_indent = len(line) - len(line.lstrip())
        i += 1
        while i < len(lines):
            child = lines[i]
            if not child.strip():
                i += 1
                continue
            child_indent = len(child) - len(child.lstrip())
            if child_indent <= header_indent and child.strip().startswith("-"):
                break
            match = re.search(r"`([^`]+)`", child)
            if match:
                repos.append(repo_for_path(match.group(1).strip()))
            i += 1
    return ordered_unique(repos)


def extract_tokens(value: str, pattern: re.Pattern[str]) -> list[str]:
    return ordered_unique(match.upper() for match in pattern.findall(value or ""))


def normalize_issue_ref(repo: str | None, number: str) -> str:
    normalized_repo = normalize_repo_slug(repo) if repo else None
    if normalized_repo:
        return f"{normalized_repo}#{int(number)}"
    return f"#{int(number)}"


def extract_issue_refs(value: str, *, default_repo: str | None = None) -> list[str]:
    refs: list[str] = []
    for match in ISSUE_URL_RE.finditer(value or ""):
        refs.append(normalize_issue_ref(match.group("repo"), match.group("number")))
    for match in ISSUE_REF_RE.finditer(value or ""):
        refs.append(normalize_issue_ref(match.group("repo") or default_repo, match.group("number")))
    return ordered_unique(refs)


def extract_non_issue_dependency_tokens(value: str) -> list[str]:
    return ordered_unique(
        [
            *extract_tokens(value, WORKSTREAM_TOKEN_RE),
            *extract_tokens(value, MERGE_POINT_RE),
            *extract_tokens(value, GATE_RE),
            *extract_tokens(value, DECISION_TOKEN_RE),
            *extract_tokens(value, ASSUMPTION_TOKEN_RE),
            *extract_tokens(value, RISK_TOKEN_RE),
        ]
    )


def analyze_dependency_values(values: list[str], *, default_repo: str | None = None) -> DependencyAnalysis:
    analysis = DependencyAnalysis()
    for value in values:
        cleaned_value = value.replace("`", "").strip()
        if cleaned_value.lower() in {"none", "n/a", "na"}:
            continue
        issue_refs = extract_issue_refs(value, default_repo=default_repo)
        tokens = extract_non_issue_dependency_tokens(value)
        analysis.issue_refs.extend(issue_refs)
        analysis.dependencies.extend([*issue_refs, *tokens])
        analysis.unsupported_tokens.extend(
            token
            for token in tokens
            if MERGE_POINT_RE.fullmatch(token)
            or GATE_RE.fullmatch(token)
            or DECISION_TOKEN_RE.fullmatch(token)
            or ASSUMPTION_TOKEN_RE.fullmatch(token)
            or RISK_TOKEN_RE.fullmatch(token)
        )
        if not issue_refs and not tokens:
            analysis.dependencies.append(cleaned_value)
            analysis.opaque_values.append(cleaned_value)
    analysis.dependencies = ordered_unique(analysis.dependencies)
    analysis.issue_refs = ordered_unique(analysis.issue_refs)
    analysis.unsupported_tokens = ordered_unique(analysis.unsupported_tokens)
    analysis.opaque_values = ordered_unique(analysis.opaque_values)
    return analysis


def analyze_manifest_dependency_values(
    values: list[str],
    *,
    manifest_source_ids: set[str],
    default_repo: str | None = None,
) -> DependencyAnalysis:
    analysis = DependencyAnalysis()
    for value in values:
        for segment in value.split(","):
            cleaned_value = segment.replace("`", "").strip()
            if cleaned_value.lower() in {"", "none", "n/a", "na"}:
                continue
            issue_refs = extract_issue_refs(segment, default_repo=default_repo)
            manifest_tokens = [
                token
                for token in extract_tokens(segment, MANIFEST_LEAF_TOKEN_RE)
                if token in manifest_source_ids
            ]
            manifest_token_set = set(manifest_tokens)
            unsupported_tokens = [
                token
                for token in [
                    *extract_tokens(segment, WORKSTREAM_TOKEN_RE),
                    *extract_tokens(segment, MERGE_POINT_RE),
                    *extract_tokens(segment, GATE_RE),
                    *extract_tokens(segment, DECISION_TOKEN_RE),
                    *extract_tokens(segment, ASSUMPTION_TOKEN_RE),
                    *extract_tokens(segment, RISK_TOKEN_RE),
                ]
                if token not in manifest_token_set
            ]
            analysis.issue_refs.extend(issue_refs)
            analysis.dependencies.extend([*manifest_tokens, *issue_refs, *unsupported_tokens])
            analysis.unsupported_tokens.extend(unsupported_tokens)
            if not issue_refs and not manifest_tokens and not unsupported_tokens:
                analysis.dependencies.append(cleaned_value)
                analysis.opaque_values.append(cleaned_value)
    analysis.dependencies = ordered_unique(analysis.dependencies)
    analysis.issue_refs = ordered_unique(analysis.issue_refs)
    analysis.unsupported_tokens = ordered_unique(analysis.unsupported_tokens)
    analysis.opaque_values = ordered_unique(analysis.opaque_values)
    return analysis


def normalize_dependency_values(values: list[str]) -> list[str]:
    return analyze_dependency_values(values).dependencies


def analyze_blocker_values(values: list[str], *, default_repo: str | None = None) -> BlockerAnalysis:
    analysis = BlockerAnalysis()
    for value in values:
        cleaned_value = value.replace("`", "").strip()
        if cleaned_value.lower() in {"none", "n/a", "na"}:
            continue
        issue_refs = extract_issue_refs(value, default_repo=default_repo)
        tokens = extract_non_issue_dependency_tokens(value)
        if issue_refs or tokens:
            analysis.issue_refs.extend(issue_refs)
            analysis.blockers.extend([*issue_refs, *tokens])
            continue
        analysis.blockers.append(cleaned_value)
        analysis.opaque_values.append(cleaned_value)
    analysis.blockers = ordered_unique(analysis.blockers)
    analysis.issue_refs = ordered_unique(analysis.issue_refs)
    analysis.opaque_values = ordered_unique(analysis.opaque_values)
    return analysis


def repo_for_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    if normalized.startswith("core/"):
        return "core"
    if normalized.startswith("infra/"):
        return "infra"
    if normalized.startswith("admin-ui/"):
        return "admin-ui"
    if normalized.startswith("app/"):
        return "app"
    return "service"


def repo_component_for_issue_repo(repo: str | None) -> str | None:
    repo_slug = normalize_repo_slug(repo)
    if not repo_slug:
        return None
    name = repo_slug.split("/", 1)[-1].strip().lower()
    aliases = {
        "service": "service",
        "api-service": "service",
        "core": "core",
        "core-lib": "core",
        "admin-ui": "admin-ui",
        "app": "app",
        "frontend": "app",
        "infra": "infra",
    }
    return aliases.get(name)


def filter_repo_targets_for_issue_repo(
    repo_targets: list[str], issue_repo: str | None
) -> list[str]:
    if not repo_targets or not issue_repo:
        return repo_targets
    repo_component = repo_component_for_issue_repo(issue_repo)
    if not repo_component:
        return repo_targets
    normalized_issue_repo = normalize_repo_slug(issue_repo)
    matches: list[str] = []
    for repo_target in repo_targets:
        normalized_target = normalize_repo_slug(repo_target)
        if normalized_issue_repo and normalized_target == normalized_issue_repo:
            matches.append(normalized_target)
            continue
        if repo_component_for_issue_repo(repo_target) == repo_component:
            matches.append(normalized_target or repo_target)
    return ordered_unique(matches)


def repo_targets_include_issue_repo(repo_targets: list[str], issue_repo: str | None) -> bool:
    if not repo_targets or not issue_repo:
        return True
    return bool(filter_repo_targets_for_issue_repo(repo_targets, issue_repo))


def collect_owner_repo_targets(text: str) -> dict[str, list[str]]:
    owner_repos: dict[str, list[str]] = {}
    for match in FILE_DELTA_RE.finditer(text):
        path = match.group("link_text") or match.group("code_path") or ""
        owner = match.group("owner").strip()
        owner_repos.setdefault(owner, [])
        owner_repos[owner].append(repo_for_path(path))
    return {owner: normalize_repo_target_values(repos) for owner, repos in owner_repos.items()}


def collect_explicit_blockers(text: str) -> dict[str, str]:
    """Return only IDs the plan explicitly asks to materialize as blocking work.

    Assumptions (A1) and risks (R1) are not schedule blockers unless a conversion
    rule lists them — merging every A/R into the epic was misleading for plans
    that omit a materialize line (e.g. WS4).
    """
    blockers: dict[str, str] = {}
    assumptions = parse_named_items(ASSUMPTION_RE, text)
    risks = parse_named_items(RISK_RE, text)
    explicit_ids: list[str] = []
    for line in text.splitlines():
        if "GitHub issue conversion rule: materialize" not in line:
            continue
        explicit_ids.extend(re.findall(r"`([^`]+)`", line))
    for blocker_id in explicit_ids:
        if blocker_id in assumptions:
            blockers[blocker_id] = assumptions[blocker_id]
        elif blocker_id in risks:
            blockers[blocker_id] = risks[blocker_id]
    return blockers


def collect_plan_decisions(text: str) -> dict[str, str]:
    return parse_named_items(DECISION_RE, text)


def collect_stability_notes(text: str) -> list[str]:
    notes: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        low = stripped.lower()
        if low.startswith("- stability note:"):
            notes.append(stripped.removeprefix("- ").strip())
    return ordered_unique(notes)


def collect_azure_runner_inputs(text: str) -> list[str]:
    inputs: list[str] = []
    in_section = False
    for line in text.splitlines():
        if line.startswith("- Deployed runner inputs:"):
            in_section = True
            continue
        if in_section and line.startswith("#"):
            break
        if in_section and line.lstrip().startswith("- "):
            inputs.append(line.strip()[2:].strip())
    return inputs


def collect_all_gates(text: str) -> list[str]:
    return ordered_unique(match.upper() for match in GATE_RE.findall(text))


def infer_owner_labels(owner_names: list[str]) -> list[str]:
    labels: list[str] = []
    for owner_name in owner_names:
        token = owner_name.lower().replace("/", "-").replace(" ", "-")
        labels.append(shorten_label_name(f"owner:{token}"))
    return labels


def infer_highest_tier(gates: list[str]) -> str | None:
    if not gates:
        return None
    if any(gate.startswith("G-MVP-") for gate in gates):
        return "T5"
    if any(gate.startswith("G-DEPLOYED-") for gate in gates):
        return "T5"
    if any(gate.startswith("G-SEC-") for gate in gates):
        return "T5"
    if any(
        gate in {"G-PRODUCT-WORKFLOW-SMOKE", "G-LOCAL-WORKFLOW-RELIABILITY", "G-WORKFLOW-AUTH-LOCAL"}
        for gate in gates
    ):
        return "T4"
    if "G-PYTHON-CLIENT-TESTS" in gates:
        return "T3"
    return "T0"


def repo_label_value(repo_target: str) -> str:
    """GitHub label token derived from the normalized owner/repo (preserves root repo spelling)."""
    normalized = normalize_repo_slug(repo_target) or repo_target.strip()
    if "/" in normalized:
        return normalized.split("/", 1)[-1].strip().lower()
    return normalized.lower()


def distinct_normalized_repo_slugs_from_children(children: list[IssueDraft]) -> list[str]:
    seen: dict[str, None] = {}
    for child in children:
        for rt in child.repo_targets:
            slug = normalize_repo_slug(rt) or rt.strip()
            if slug:
                seen.setdefault(slug, None)
    return list(seen.keys())


def infer_repo_note(repo_targets: list[str]) -> str:
    if not repo_targets:
        return ""
    normalized_targets = [normalize_repo_slug(repo) or repo for repo in repo_targets]
    if len(normalized_targets) == 1 and normalized_targets[0] == ROOT_REPO_SLUG:
        return "Implementation work stays in the target repo."
    if len(normalized_targets) == 1:
        return (
            f"This work clearly lands in the nested `{normalized_targets[0]}` repo; keep the root plan as the authoring artifact "
            "and flag the repo boundary instead of silently re-homing the story."
        )
    repo_list = ", ".join(f"`{repo}`" for repo in normalized_targets)
    return (
        "This story spans multiple repos/components "
        f"({repo_list}); keep the root plan as the authoring artifact and treat the issue as cross-repo tracking."
    )


def suggest_points(title: str, repo_targets: list[str], gates: list[str]) -> int:
    lowered = title.lower()
    if "verification" in lowered or "governance" in lowered:
        return 5
    if "azure" in lowered or "hosted" in lowered or len(repo_targets) > 1:
        return 13
    if "runtime" in lowered or "persistence" in lowered:
        return 13
    if "contracts" in lowered or "codegen" in lowered:
        return 8
    if "migration" in lowered or "client" in lowered or "cutover" in lowered:
        return 8
    if "G-PYTHON-CLIENT-TESTS" in gates:
        return 8
    return 5


def plan_stem(plan_key: str) -> str | None:
    match = re.match(r"(WS\d+)", plan_key.strip(), flags=re.IGNORECASE)
    return match.group(1).upper() if match else None


def infer_ws1_story_blockers(
    source_id: str,
    title: str,
    global_blockers: dict[str, str],
    decisions: dict[str, str],
) -> list[str]:
    lowered = title.lower()
    blockers: list[str] = []
    if source_id.endswith("A"):
        for blocker_id in ("A2", "A3"):
            if blocker_id in global_blockers:
                blockers.append(f"{blocker_id}: {global_blockers[blocker_id]}")
    elif source_id.endswith("B"):
        for blocker_id in ("A1",):
            if blocker_id in global_blockers:
                blockers.append(f"{blocker_id}: {global_blockers[blocker_id]}")
    elif source_id.endswith("C"):
        for blocker_id in ("A1",):
            if blocker_id in global_blockers:
                blockers.append(f"{blocker_id}: {global_blockers[blocker_id]}")
        for decision_id in ("DR-WS1-006", "DR-WS1-013"):
            if decision_id in decisions:
                blockers.append(f"{decision_id}: {decisions[decision_id]}")
    elif source_id.endswith("D"):
        for blocker_id in ("A2", "R3"):
            if blocker_id in global_blockers:
                blockers.append(f"{blocker_id}: {global_blockers[blocker_id]}")
        if "DR-WS1-015" in decisions:
            blockers.append(f"DR-WS1-015: {decisions['DR-WS1-015']}")
    elif source_id.endswith("E") or "verification" in lowered:
        for blocker_id, description in global_blockers.items():
            blockers.append(f"{blocker_id}: {description}")
        for decision_id in ("DR-WS1-006", "DR-WS1-013"):
            if decision_id in decisions:
                blockers.append(f"{decision_id}: {decisions[decision_id]}")
    return ordered_unique(blockers)


def infer_story_blockers(
    plan_key: str,
    source_id: str,
    title: str,
    global_blockers: dict[str, str],
    decisions: dict[str, str],
) -> list[str]:
    stem = plan_stem(plan_key)
    if stem != "WS1":
        return []
    sid = source_id.upper()
    if sid != "WS1" and not sid.startswith("WS1"):
        return []
    return infer_ws1_story_blockers(sid, title, global_blockers, decisions)


def _is_ws2_f_workstream(scope_id: str) -> bool:
    """True only for the route/workflow parity workstream (not title heuristics)."""
    sid = scope_id.strip().upper().replace("–", "-")
    return bool(re.fullmatch(r"WS2-?F", sid))


def infer_ws2_validation_requirements(
    scope_id: str,
    stability_notes: list[str],
) -> list[str]:
    requirements: list[str] = []
    sid = scope_id.upper().replace("–", "-")
    base_local = (
        "Activate the project virtualenv at repo root; run the plan's `G-WS2-*` pytest lanes "
        "from the package directory named in the plan."
    )
    base_sec = (
        "Run `G-SEC-*` gates from repo-root `tests/` when this story touches those surfaces; "
        "use the same venv from repo root without `cd` into the local package."
    )
    if sid == "WS2":
        requirements.extend(
            [
                "Local/CI proves implementation readiness; do not claim Azure drafting trust or WS2 MVP "
                "completion from local/CI alone (plan DR-003).",
                "Azure / T5 closeout (human-run): `G-SEC-APIM-BACKEND-PARITY`, deployed search parity via "
                "`.github/workflows/_test-suites.yml` `phase35-search-io` (or documented successor), "
                "`G-SEC-BACKEND-JWT`, and `G-SEC-INTERNAL-SURFACE` in the target environment; attach "
                "evidence artifacts to the trust claim.",
                "Before Azure parity: `G-WS2-FinanceBench-PDF-Extended` (manual) sign-off with run logs "
                "attached (plan DR-006).",
                base_local,
                base_sec,
            ]
        )
    elif _is_ws2_f_workstream(scope_id):
        requirements.extend(
            [
                "Own repo-local `G-WS2-RouteParity`, `G-WS2-WorkflowParity`, and CI `G-SEC-BACKEND-JWT` / "
                "`G-SEC-INTERNAL-SURFACE` when this branch changes those surfaces.",
                "Keep `G-SEC-APIM-BACKEND-PARITY` and deployed search parity on the parent epic or dedicated "
                "T5 issues unless this story explicitly owns hosted validation.",
                base_local,
                base_sec,
            ]
        )
    else:
        requirements.extend(
            [
                "This story is bounded to local/CI trust lanes (`ws2_ci` / documented manual shards); "
                "the epic tracks T5 Azure trust closeout.",
                base_local,
            ]
        )
    for note in stability_notes:
        if "deployed drafting closeout" in note.lower() or "azure mvp board" in note.lower():
            requirements.append(note)
    return ordered_unique(requirements)


def infer_ws4_validation_requirements(
    scope_id: str,
    title: str,
    azure_runner_inputs: list[str],
    stability_notes: list[str],
    gates: list[str] | None,
) -> list[str]:
    """WS4 plans are local/CI-first; Azure MVP drafting closeout is explicit (DR-WS4-009)."""
    sid = scope_id.strip().upper().replace("–", "-")
    gate_set = {g.upper() for g in (gates or [])}
    lowered = title.lower()
    requirements: list[str] = []

    hosted_touch = bool(
        gate_set.intersection(
            {
                "G-DEPLOYED-WORKFLOW-AUTH-PARITY",
                "G-DEPLOYED-WORKFLOW-PARITY",
                "G-MVP-DEPLOYED-DRAFTING-PARITY",
            }
        )
    ) or any(g.startswith("G-SEC-") for g in gate_set)
    if "functions/" in lowered or "infra/" in lowered or "hosted" in lowered or "deployed" in lowered:
        hosted_touch = True

    if sid == "WS4":
        requirements.append(
            "Azure MVP closeout: satisfy `G-MVP-DEPLOYED-DRAFTING-PARITY` (plan DR-WS4-009) with PARITY-1 route/detail, "
            "PARITY-2 drafting artifact/evidence, and PARITY-3 deployed operator walkthrough evidence before calling MVP complete on Azure."
        )
        requirements.extend(stability_notes)
        if azure_runner_inputs:
            requirements.append(
                "When verifying hosted paths, use the plan's deployed runner inputs and preserve the APIM → Functions trust boundary (DR-WS4-007)."
            )
            requirements.extend(azure_runner_inputs)
        return ordered_unique(requirements)

    requirements.append(
        "WS4 work is local/CI-first: satisfy the workstream named gates; do not treat Azure MVP as complete from local evidence alone."
    )
    if hosted_touch:
        requirements.append(
            "This scope touches hosted workflow or security surfaces: run `G-SEC-INTERNAL-AUTH` and `G-SEC-HEADER-PROJECTION` "
            "when `functions/**`, backend authentication modules, or relevant `infra/**` changes land in the same branch."
        )
        if azure_runner_inputs:
            requirements.extend(azure_runner_inputs)
        requirements.append(
            "Track `G-MVP-DEPLOYED-DRAFTING-PARITY` / PARITY issues on the parent epic unless this story explicitly owns deployed drafting validation."
        )
    requirements.extend(
        note
        for note in stability_notes
        if any(
            token in note.lower()
            for token in ("mvp", "parity", "drafting", "g-mvp-deployed-drafting-parity", "azure")
        )
    )
    return ordered_unique(requirements)


def infer_validation_requirements(
    plan_key: str,
    scope_id: str,
    title: str,
    azure_runner_inputs: list[str],
    stability_notes: list[str],
    *,
    gates: list[str] | None = None,
) -> list[str]:
    stem_match = plan_stem(plan_key)
    stem = stem_match or plan_key.strip().upper()
    sid = scope_id.strip().upper().replace("–", "-")
    lowered = title.lower()
    requirements: list[str] = []

    if stem == "WS2":
        return infer_ws2_validation_requirements(sid, stability_notes)

    if stem == "WS3":
        if sid == stem:
            requirements.extend(
                [
                    "WS3 epic tracks local contract + local runtime readiness through `WS3-MP3`; "
                    "do not claim deployed drafting parity or Azure MVP drafting closeout from this epic alone.",
                    "Trusted drafting on the roadmap remains gated on `WS2-F` / `WS2-MP5` (route/workflow propagation) "
                    "per the WS3 plan; track as explicit upstream dependency or follow-up issue.",
                    "Deployed drafting parity is `G-MVP-DEPLOYED-DRAFTING-PARITY` (outside WS3 local gate closure).",
                ]
            )
            for note in stability_notes:
                if "deployed drafting closeout" in note.lower() or "azure mvp board" in note.lower():
                    requirements.append(note)
            return ordered_unique(requirements)
        requirements.append(
            "Prove acceptance with the plan's `G-WS3-*` gates and `ws3_*` pytest markers; "
            "do not fold unrelated deployed workflow parity gates into WS3 story closure unless the story explicitly owns them."
        )
        for note in stability_notes:
            if "deployed drafting closeout" in note.lower() or "azure mvp board" in note.lower():
                requirements.append(note)
        return ordered_unique(requirements)

    if stem == "WS4":
        return infer_ws4_validation_requirements(
            sid, title, azure_runner_inputs, stability_notes, gates
        )

    if stem_match is None:
        if gates:
            requirements.append(
                "Use the lane plan's named gates and cited source-plan acceptance gates; "
                "do not import WS-specific hosted workflow parity requirements unless the lane explicitly declares them."
            )
        return ordered_unique(requirements)

    is_azure_scoped = False
    if stem == "WS1":
        is_azure_scoped = (
            sid == stem
            or (sid.startswith("WS1") and sid.endswith(("D", "E")))
            or "azure" in lowered
            or "hosted" in lowered
        )
    else:
        is_azure_scoped = sid == stem or "azure" in lowered or "hosted" in lowered

    if is_azure_scoped:
        requirements.append(
            "Run `G-DEPLOYED-WORKFLOW-AUTH-PARITY` and `G-DEPLOYED-WORKFLOW-PARITY` against the configured hosted API deployment."
        )
        requirements.extend(azure_runner_inputs)
        requirements.append(
            "Keep deterministic hosted parity scoped to `summary.v1`; do not treat `case_summary_draft.v1` as closed here."
        )
    else:
        requirements.append(
            "Preserve one shared local/Azure workflow contract so WS1D can validate hosted parity without DTO forks."
        )
    if is_azure_scoped:
        for note in stability_notes:
            if "deployed drafting closeout" in note.lower() or "azure mvp board" in note.lower():
                requirements.append(note)
    return ordered_unique(requirements)


def parse_project_url(project_url: str) -> tuple[str, int]:
    match = PROJECT_URL_RE.match(project_url.strip())
    if not match:
        raise SystemExit(
            "Invalid --project-url. Expected a GitHub URL like "
            "https://github.com/orgs/<owner>/projects/<number>."
        )
    return match.group("owner"), int(match.group("number"))


def infer_labels(
    section_title: str,
    section_body: str,
    kind: str,
    plan_key: str,
    *,
    workstream_label_scope: str | None = None,
    owner_names: list[str] | None = None,
    repo_targets: list[str] | None = None,
    highest_tier: str | None = None,
    status_label: str = "status:draft",
    points: int | None = None,
    priority: str | None = None,
) -> list[str]:
    workstream_token = (workstream_label_scope or plan_key).strip()
    labels = [f"type:{kind}", f"workstream:{workstream_label_value(workstream_token)}"]
    lowered = f"{section_title}\n{section_body}".lower()
    stem = plan_stem(plan_key) or plan_key.strip().upper()
    if "admin-ui" in lowered or "admin ui" in lowered:
        labels.append("area:admin-ui")
    if "frontend" in lowered or "app" in lowered:
        labels.append("area:app")
    if "infra" in lowered:
        labels.append("area:infra")
    if "azure" in lowered or "hosted" in lowered or "deployed" in lowered:
        labels.append("area:azure")
    if "core" in lowered or "contracts" in lowered or "workflow" in lowered:
        labels.append("area:core")
    if stem in {"WS1", "WS3", "WS4"} or "workflow control plane" in lowered:
        labels.append("area:workflow-control-plane")
    if not any(label.startswith("area:") for label in labels):
        labels.append("area:portfolio")
    labels.append(status_label)
    if owner_names:
        labels.extend(infer_owner_labels(owner_names))
    if repo_targets:
        labels.append("repo:cross-repo" if len(repo_targets) > 1 else f"repo:{repo_label_value(repo_targets[0])}")
    if highest_tier:
        labels.append(f"tier:{highest_tier.lower()}")
    if points in ALLOWED_POINT_VALUES:
        labels.append(f"points:{points}")
    if requires_decomposition(points):
        labels.extend(["agent:decomposed", "decomposition:required"])
    if priority:
        labels.append(f"priority:{priority.lower()}")
    return normalize_label_names(labels)


def workstream_label_value(workstream_token: str) -> str:
    normalized = workstream_token.strip().lower()
    compact_match = re.fullmatch(r"ws(?P<num>\d+)(?P<suffix>[a-z])(?P<rest>(?:-[a-z0-9]+)*)", normalized)
    if compact_match:
        return f"ws{compact_match.group('num')}-{compact_match.group('suffix')}{compact_match.group('rest')}"
    return normalized


def build_epic(
    plan_path: Path,
    plan_display_path: str,
    frontmatter: dict[str, str],
    heading: str,
    body: str,
    *,
    issue_repo: str | None,
    global_blockers: dict[str, str],
    repo_targets: list[str],
    azure_runner_inputs: list[str],
    stability_notes: list[str],
    plan_base_branch: str | None,
    plan_execution: dict[str, object],
) -> IssueDraft:
    plan_key = infer_plan_key(frontmatter.get("name", ""), plan_path.stem, heading)
    epic_title = heading
    summary = frontmatter.get("overview", "").strip()
    blockers = [f"{blocker_id}: {description}" for blocker_id, description in global_blockers.items()]
    validation_requirements = infer_validation_requirements(
        plan_key,
        plan_key,
        epic_title,
        azure_runner_inputs,
        stability_notes,
        gates=None,
    )
    if plan_key == "WS3":
        epic_highest_tier: str | None = None
    else:
        epic_highest_tier = (
            "T5"
            if any(
                "G-DEPLOYED" in requirement
                or "G-MVP-" in requirement
                or "PARITY-" in requirement
                for requirement in validation_requirements
            )
            else "T4"
        )
    labels = infer_labels(
        epic_title,
        summary or epic_title,
        "epic",
        plan_key,
        workstream_label_scope=projection_workstream_label_scope(frontmatter, plan_key),
        repo_targets=repo_targets,
        highest_tier=epic_highest_tier,
    )
    execution_repo, base_branch = resolve_issue_execution_context(
        issue_repo=issue_repo,
        repo_targets=repo_targets,
        default_base_branch=plan_base_branch or frontmatter.get("tracking.baseBranch"),
    )
    validation_scope = infer_validation_scope(
        title=epic_title,
        excerpt=summary or epic_title,
        gates=[],
        validation_requirements=validation_requirements,
    )
    risk_tags = infer_risk_tags(
        title=epic_title,
        excerpt=summary or epic_title,
        repo_targets=repo_targets,
        highest_tier=epic_highest_tier,
        blockers=blockers,
        azure_closeout_only=False,
        issue_ready=True,
        validation_scope=validation_scope,
        gates=[],
    )
    dispatch_recommendation = (
        "tracking-only"
        if plan_execution["dispatch_blocked"]
        else "review-before-dispatch"
    )
    issue_title = f"[Epic][{plan_key}] {epic_title}"
    body_lines = ["## Source Plan", *build_plan_reference_lines(plan_path), f"- Plan key: `{plan_key}`", "", "## Summary", summary or "No overview found in frontmatter.", ""]
    body_lines.extend(build_execution_context_lines(execution_repo, base_branch))
    body_lines.extend(
        [
            "## Dispatch Metadata",
            f"- Dispatch recommendation: `{dispatch_recommendation}`",
            f"- Validation scope: `{validation_scope}`",
        ]
    )
    if risk_tags:
        body_lines.append(f"- Risk tags: `{', '.join(risk_tags)}`")
    body_lines.append("")
    if blockers:
        body_lines.extend(["## Explicit Blockers", *[f"- {item}" for item in blockers], ""])
    if plan_execution["dispatch_blockers"]:
        body_lines.extend(
            [
                "## Dispatch Guardrails",
                *[f"- {item}" for item in plan_execution["dispatch_blockers"]],
                "",
            ]
        )
    if repo_targets:
        body_lines.extend(["## Repo Boundaries", f"- {infer_repo_note(repo_targets)}", ""])
    if validation_requirements:
        body_lines.extend(
            [
                "## Deployed / Manual Validation Requirements",
                *[f"- {item}" for item in validation_requirements],
                "",
            ]
        )
    if stability_notes:
        body_lines.extend(["## Stability Notes", *[f"- {item}" for item in stability_notes], ""])
    body_lines.extend(
        [
            "## Notes",
            "- This issue was generated from the plan artifact.",
            "- Keep the plan as the authoring artifact; do not treat the issue as planning authority.",
        ]
    )
    issue_body = "\n".join(body_lines)
    return IssueDraft(
        title=issue_title,
        body=issue_body,
        labels=labels,
        kind="epic",
        source_id=plan_key,
        execution_repo=execution_repo,
        base_branch=base_branch,
        blockers=blockers,
        repo_targets=repo_targets,
        repo_note=infer_repo_note(repo_targets),
        validation_requirements=validation_requirements,
        unstable_reasons=stability_notes,
        issue_ready=True,
        azure_closeout_only=False,
        status_label="status:draft",
        dispatch_recommendation=dispatch_recommendation,
        validation_scope=validation_scope,
        risk_tags=risk_tags,
    )


def build_children(
    plan_path: Path,
    plan_display_path: str,
    plan_key: str,
    frontmatter: dict[str, str],
    sections: list[tuple[str, list[str]]],
    kind: str,
    *,
    issue_repo: str | None,
    owner_repo_targets: dict[str, list[str]],
    global_blockers: dict[str, str],
    decisions: dict[str, str],
    azure_runner_inputs: list[str],
    stability_notes: list[str],
    all_gates: list[str],
    plan_base_branch: str | None,
    plan_execution: dict[str, object],
) -> list[IssueDraft]:
    drafts: list[IssueDraft] = []
    for title, lines in sections:
        source_id = extract_source_id(title, plan_key)
        display_title = child_display_title(title, source_id)
        excerpt = normalize_excerpt(lines)
        owner_names = ordered_unique(
            [value.replace("`", "").strip() for value in collect_field_values(lines, "owner")]
        )
        explicit_repo_targets = normalize_repo_target_values(collect_field_values(lines, "target repo"))
        repo_targets = explicit_repo_targets[:]
        if not repo_targets:
            for owner_name in owner_names:
                repo_targets.extend(owner_repo_targets.get(owner_name, []))
            if "persistence" in title.lower():
                repo_targets.extend(owner_repo_targets.get("Persistence/Migration", []))
            repo_targets.extend(extract_owned_file_repo_targets(lines))
        repo_targets = normalize_repo_target_values(repo_targets)
        dependency_analysis = analyze_dependency_values(
            collect_field_values(lines, "depends on"),
            default_repo=issue_repo,
        )
        dependencies = dependency_analysis.dependencies
        merge_points = ordered_unique(
            token
            for value in collect_field_values(lines, "merge point")
            for token in extract_tokens(value, MERGE_POINT_RE)
        )
        blocker_analysis = analyze_blocker_values(
            collect_field_values(lines, "blocked by"),
            default_repo=issue_repo,
        )
        explicit_blockers = blocker_analysis.blockers
        raw_review_gate_values = collect_field_values(lines, "review gates")
        gates = ordered_unique(
            token
            for value in raw_review_gate_values
            for token in extract_tokens(value, GATE_RE)
        )
        gates = ordered_unique([*gates, *extract_review_gates_from_workstream_lines(lines)])
        if not gates and any("all named gates" in value.lower() for value in raw_review_gate_values):
            gates = all_gates
        blockers = ordered_unique(
            [
                *explicit_blockers,
                *infer_story_blockers(plan_key, source_id, title, global_blockers, decisions),
            ]
        )
        issue_ready = parse_bool_field(collect_field_values(lines, "issue ready"), default=True)
        azure_closeout_only = parse_bool_field(
            collect_field_values(lines, "azure closeout only", "deployed closeout only", "provider closeout only"),
            default=False,
        )
        highest_tier = normalize_highest_tier(collect_field_values(lines, "highest tier")) or infer_highest_tier(gates)
        if highest_tier is None and source_id.endswith("E"):
            highest_tier = "T5"
        validation_requirements = infer_validation_requirements(
            plan_key,
            source_id,
            title,
            azure_runner_inputs,
            stability_notes,
            gates=gates,
        )
        validation_scope = infer_validation_scope(
            title=title,
            excerpt=excerpt,
            gates=gates,
            validation_requirements=validation_requirements,
        )
        repo_note = infer_repo_note(repo_targets)
        execution_repo, base_branch = resolve_issue_execution_context(
            issue_repo=issue_repo,
            repo_targets=repo_targets,
            explicit_execution_repo=normalize_branch_field(
                collect_field_values(lines, "execution repo", "execution repository")
            ),
            explicit_base_branch=normalize_branch_field(
                collect_field_values(lines, "base branch", "target base branch")
            ),
            default_base_branch=plan_base_branch or frontmatter.get("tracking.baseBranch"),
        )
        automation_blockers = ordered_unique(
            [
                *(
                    f"Convert dependency token `{token}` into an explicit issue ref or runnable workstream before auto-dispatch."
                    for token in dependency_analysis.unsupported_tokens
                ),
                *(
                    f"Resolve opaque dependency `{value}` into an explicit issue ref or canonical workstream token before auto-dispatch."
                    for value in dependency_analysis.opaque_values
                ),
            ]
        )
        points = points_for_issue(title, repo_targets, gates, lines)
        automation_blockers = ordered_unique([*automation_blockers, *point_dispatch_guardrails(points)])
        risk_tags = infer_risk_tags(
            title=title,
            excerpt=excerpt,
            repo_targets=repo_targets,
            highest_tier=highest_tier,
            blockers=[*blockers, *automation_blockers],
            azure_closeout_only=azure_closeout_only,
            issue_ready=issue_ready,
            validation_scope=validation_scope,
            gates=gates,
        )
        dispatch_recommendation = infer_dispatch_recommendation(
            issue_ready=issue_ready,
            azure_closeout_only=azure_closeout_only,
            blockers=blockers,
            repo_targets=repo_targets,
            validation_scope=validation_scope,
            risk_tags=risk_tags,
            plan_dispatch_blocked=bool(plan_execution["dispatch_blocked"]),
            automation_blockers=automation_blockers,
        )
        status_label = runtime_status_label(
            issue_ready=issue_ready,
            azure_closeout_only=azure_closeout_only,
            blockers=blockers,
            automation_blockers=automation_blockers,
            dispatch_recommendation=dispatch_recommendation,
        )
        priority = infer_priority_value(
            explicit_priority=explicit_priority_from_lines(lines),
            title=title,
            excerpt=excerpt,
            highest_tier=highest_tier,
            risk_tags=risk_tags,
            blockers=blockers,
            automation_blockers=automation_blockers,
            validation_scope=validation_scope,
            gates=gates,
        )
        labels = infer_labels(
            title,
            excerpt,
            kind,
            plan_key,
            workstream_label_scope=source_id,
            owner_names=owner_names,
            repo_targets=repo_targets,
            highest_tier=highest_tier,
            status_label=status_label,
            points=points,
            priority=priority,
        )
        body_lines = [
            "## Source Plan",
            *build_plan_reference_lines(plan_path, include_execution_note=bool(repo_targets)),
            f"- Source section: `{title}`",
            "",
            "## Suggested Draft Metadata",
            f"- Suggested points: `{points}`",
            f"- Issue ready: `{'true' if status_label == 'status:ready' else 'false'}`",
            f"- Dispatch recommendation: `{dispatch_recommendation}`",
            f"- Validation scope: `{validation_scope}`",
            f"- Priority: `{priority}`",
        ]
        if risk_tags:
            body_lines.append(f"- Risk tags: `{', '.join(risk_tags)}`")
        if repo_targets:
            body_lines.append(f"- Target repo(s): `{', '.join(repo_targets)}`")
        if execution_repo:
            body_lines.append(f"- Execution repo: `{execution_repo}`")
        if base_branch:
            body_lines.append(f"- Base branch: `{base_branch}`")
            body_lines.append(
                "- PR rule: create follow-up PRs against the explicit base branch above; do not infer from local checkout state, `origin/HEAD`, or fallback-to-`main` behavior."
            )
        if highest_tier:
            body_lines.append(f"- Highest tier: `{highest_tier}`")
        if azure_closeout_only:
            body_lines.append("- Deployed closeout only: `true`")
        if repo_note:
            body_lines.append(f"- Repo note: {repo_note}")
        body_lines.append("")
        body_lines.extend(
            build_execution_state_lines(
                open_dependencies=dependencies,
                manual_gates_remaining=blockers,
            )
        )
        if dependencies:
            body_lines.extend(["## Dependencies", *[f"- {item}" for item in dependencies], ""])
        if blockers:
            body_lines.extend(["## Blockers", *[f"- {item}" for item in blockers], ""])
        if dependency_analysis.issue_refs or blocker_analysis.issue_refs:
            body_lines.append("## Linked Issue Refs")
            if dependency_analysis.issue_refs:
                body_lines.extend(
                    ["- Depends on issue refs:", *[f"  - {item}" for item in dependency_analysis.issue_refs]]
                )
            if blocker_analysis.issue_refs:
                body_lines.extend(
                    ["- Blocked by issue refs:", *[f"  - {item}" for item in blocker_analysis.issue_refs]]
                )
            body_lines.append("")
        combined_dispatch_blockers = ordered_unique(
            [*automation_blockers, *plan_execution["dispatch_blockers"]]
        )
        if combined_dispatch_blockers:
            body_lines.extend(
                [
                    "## Dispatch Guardrails",
                    *[f"- {item}" for item in combined_dispatch_blockers],
                    "",
                ]
            )
        if merge_points:
            body_lines.extend(["## Merge Points", *[f"- {item}" for item in merge_points], ""])
        if gates:
            body_lines.extend(["## Named Gates", *[f"- {item}" for item in gates], ""])
        if validation_requirements:
            body_lines.extend(
                [
                    "## Deployed / Manual Validation Requirements",
                    *[f"- {item}" for item in validation_requirements],
                    "",
                ]
            )
        if (source_id.endswith(("D", "E")) or azure_closeout_only or not issue_ready) and stability_notes:
            body_lines.extend(["## Stability Notes", *[f"- {item}" for item in stability_notes], ""])
        body_lines.extend(
            [
                "## Excerpt",
                "```md",
                excerpt or "(no body found)",
                "```",
                "",
                "## Implementation Notes",
                "- Confirm points, repo, and owner role before apply.",
                "- Keep named gates in the issue acceptance criteria.",
                "- Open PRs with an explicit base branch; do not rely on local checkout inference.",
            ]
        )
        body = "\n".join(body_lines)
        drafts.append(
            IssueDraft(
                title=f"[{source_id}] {display_title}",
                body=body,
                labels=labels,
                kind=kind,
                source_id=source_id,
                execution_repo=execution_repo,
                base_branch=base_branch,
                suggested_points=points,
                dependencies=dependencies,
                blockers=blockers,
                merge_points=merge_points,
                gates=gates,
                highest_tier=highest_tier,
                repo_targets=repo_targets,
                repo_note=repo_note,
                validation_requirements=validation_requirements,
                unstable_reasons=stability_notes if (source_id.endswith(("D", "E")) or azure_closeout_only or not issue_ready) else [],
                issue_ready=issue_ready,
                azure_closeout_only=azure_closeout_only,
                status_label=status_label,
                dispatch_recommendation=dispatch_recommendation,
                validation_scope=validation_scope,
                risk_tags=risk_tags,
                dependency_issue_refs=dependency_analysis.issue_refs,
                blocker_issue_refs=blocker_analysis.issue_refs,
                automation_blockers=automation_blockers,
                priority=priority,
            )
        )
    return drafts


def build_manifest_leaf_children(
    plan_path: Path,
    plan_display_path: str,
    plan_key: str,
    frontmatter: dict[str, str],
    sections: list[tuple[str, list[str]]],
    *,
    issue_repo: str | None,
    plan_base_branch: str | None,
    plan_execution: dict[str, object],
) -> list[IssueDraft]:
    drafts: list[IssueDraft] = []
    manifest_source_ids = {
        title.split(" ", 1)[0].strip().replace("`", "").upper()
        for title, _ in sections
        if title.strip()
    }
    for title, lines in sections:
        source_id = title.split(" ", 1)[0].strip().replace("`", "").upper()
        display_title = title.split(" ", 1)[1].strip() if " " in title else source_id
        excerpt = normalize_excerpt(lines)
        owner_names = ordered_unique(
            [value.replace("`", "").strip() for value in collect_field_values(lines, "owner")]
        )
        write_scope = ordered_unique(
            [
                value.replace("`", "").strip()
                for value in collect_field_values(
                    lines, "write scope", "files in scope", "owns files"
                )
            ]
        )
        explicit_repo_targets = normalize_repo_target_values(collect_field_values(lines, "target repo"))
        repo_targets = explicit_repo_targets[:]
        if not repo_targets:
            repo_targets = normalize_repo_target_values(
                [repo_for_path(item) for item in write_scope if item]
            )
        dependency_field_present = field_declared(lines, "depends on", "dependencies")
        dependency_analysis = analyze_manifest_dependency_values(
            collect_field_values(lines, "depends on", "dependencies"),
            manifest_source_ids=manifest_source_ids,
            default_repo=issue_repo,
        )
        dependencies = dependency_analysis.dependencies
        blocker_analysis = analyze_blocker_values(
            collect_field_values(
                lines, "blocked by", "blockers", "external blockers", "manual blockers"
            ),
            default_repo=issue_repo,
        )
        explicit_blockers = blocker_analysis.blockers
        raw_gate_values = [
            *collect_field_values(
                lines, "gates", "named gates", "review gates", "required gates"
            ),
        ]
        gates = ordered_unique(
            token
            for value in raw_gate_values
            for token in extract_tokens(value, GATE_RE)
        )
        gates = ordered_unique([*gates, *extract_review_gates_from_workstream_lines(lines)])
        validation_commands = ordered_unique(
            [
                value.replace("`", "").strip()
                for value in collect_field_values(
                    lines, "validation", "validation commands", "validation command"
                )
            ]
        )
        blocks = clean_manifest_list_values(collect_field_values(lines, "blocks"))
        parallel_group = clean_optional_manifest_scalar(
            collect_field_values(lines, "parallel group")
        )
        critical_path_rank = parse_int_value(
            clean_optional_manifest_scalar(collect_field_values(lines, "critical path rank"))
        )
        merge_group = clean_optional_manifest_scalar(collect_field_values(lines, "merge group"))
        combine_policy = clean_optional_manifest_scalar(
            collect_field_values(lines, "combine policy")
        )
        conflict_class = clean_optional_manifest_scalar(
            collect_field_values(lines, "conflict class")
        )
        validation_tier = clean_optional_manifest_scalar(
            collect_field_values(lines, "validation tier")
        )
        requested_dispatch_mode = normalize_dispatch_mode(
            collect_field_values(lines, "dispatch mode", "dispatch")
        )
        agent_type = normalize_agent_type(collect_field_values(lines, "agent type"))
        issue_ready = parse_bool_field(
            collect_field_values(lines, "issue ready"),
            default=requested_dispatch_mode in {"agent-ready", "manual-review"},
        )
        highest_tier = normalize_highest_tier(collect_field_values(lines, "highest tier")) or infer_highest_tier(gates)
        validation_requirements = validation_commands[:]
        validation_scope = infer_validation_scope(
            title=title,
            excerpt=excerpt,
            gates=gates,
            validation_requirements=validation_requirements,
        )
        repo_note = infer_repo_note(repo_targets)
        execution_repo, base_branch = resolve_issue_execution_context(
            issue_repo=issue_repo,
            repo_targets=repo_targets,
            explicit_execution_repo=normalize_branch_field(
                collect_field_values(lines, "execution repo", "execution repository")
            ),
            explicit_base_branch=normalize_branch_field(
                collect_field_values(lines, "base branch", "target base branch")
            ),
            default_base_branch=plan_base_branch or frontmatter.get("tracking.baseBranch"),
        )
        blockers = explicit_blockers
        points = points_for_issue(title, repo_targets, gates, lines)
        automation_blockers = ordered_unique(
            [
                *(
                    [
                        "Add explicit manifest dependency metadata (`Depends on: none` or concrete leaf ids/issue refs) before auto-dispatch."
                    ]
                    if not dependency_field_present
                    else []
                ),
                *(
                    f"Convert dependency token `{token}` into an explicit issue ref or Automation Issue Manifest leaf id before auto-dispatch."
                    for token in dependency_analysis.unsupported_tokens
                ),
                *(
                    f"Resolve opaque dependency `{value}` into an explicit issue ref or Automation Issue Manifest leaf id before auto-dispatch."
                    for value in dependency_analysis.opaque_values
                ),
            ]
        )
        automation_blockers = ordered_unique([*automation_blockers, *point_dispatch_guardrails(points)])
        risk_tags = infer_risk_tags(
            title=title,
            excerpt=excerpt,
            repo_targets=repo_targets,
            highest_tier=highest_tier,
            blockers=[*blockers, *automation_blockers],
            azure_closeout_only=False,
            issue_ready=issue_ready,
            validation_scope=validation_scope,
            gates=gates,
        )
        dispatch_recommendation = infer_dispatch_recommendation(
            issue_ready=issue_ready,
            azure_closeout_only=False,
            blockers=blockers,
            repo_targets=repo_targets,
            validation_scope=validation_scope,
            risk_tags=risk_tags,
            plan_dispatch_blocked=bool(plan_execution["dispatch_blocked"]),
            automation_blockers=automation_blockers,
        )
        dispatch_recommendation = dispatch_recommendation_for_manifest_mode(
            requested_dispatch_mode,
            dispatch_recommendation,
        )
        runtime_dispatch_mode = effective_dispatch_mode(
            requested_dispatch_mode,
            issue_ready=issue_ready,
            blockers=blockers,
            automation_blockers=automation_blockers,
        )
        status_label = runtime_status_label(
            issue_ready=issue_ready,
            azure_closeout_only=False,
            blockers=blockers,
            automation_blockers=automation_blockers,
            dispatch_recommendation=dispatch_recommendation,
        )
        priority = infer_priority_value(
            explicit_priority=explicit_priority_from_lines(lines),
            title=title,
            excerpt=excerpt,
            highest_tier=highest_tier,
            risk_tags=risk_tags,
            blockers=blockers,
            automation_blockers=automation_blockers,
            validation_scope=validation_scope,
            gates=gates,
        )
        labels = infer_labels(
            title,
            excerpt,
            "story",
            plan_key,
            workstream_label_scope=source_id,
            owner_names=owner_names,
            repo_targets=repo_targets,
            highest_tier=highest_tier,
            status_label=status_label,
            points=points,
            priority=priority,
        )
        body_lines = [
            "## Source Plan",
            *build_plan_reference_lines(plan_path, include_execution_note=bool(repo_targets)),
            f"- Source section: `{AUTOMATION_MANIFEST_SECTION_TITLE}` / `{source_id}`",
            "",
            "## Automation Manifest Metadata",
            f"- Suggested points: `{points}`",
            f"- Issue ready: `{'true' if status_label == 'status:ready' else 'false'}`",
            f"- Requested dispatch mode: `{requested_dispatch_mode}`",
            f"- Dispatch mode: `{runtime_dispatch_mode}`",
            f"- Dispatch recommendation: `{dispatch_recommendation}`",
            f"- Validation scope: `{validation_scope}`",
            f"- Priority: `{priority}`",
        ]
        if agent_type:
            body_lines.append(f"- Agent type: `{agent_type}`")
        if parallel_group:
            body_lines.append(f"- Parallel group: `{parallel_group}`")
        if blocks:
            body_lines.append(f"- Blocks: `{'; '.join(blocks)}`")
        if critical_path_rank is not None:
            body_lines.append(f"- Critical path rank: `{critical_path_rank}`")
        if merge_group:
            body_lines.append(f"- Merge group: `{merge_group}`")
        if combine_policy:
            body_lines.append(f"- Combine policy: `{combine_policy}`")
        if conflict_class:
            body_lines.append(f"- Conflict class: `{conflict_class}`")
        if validation_tier:
            body_lines.append(f"- Validation tier: `{validation_tier}`")
        if risk_tags:
            body_lines.append(f"- Risk tags: `{', '.join(risk_tags)}`")
        if repo_targets:
            body_lines.append(f"- Target repo(s): `{', '.join(repo_targets)}`")
        if execution_repo:
            body_lines.append(f"- Execution repo: `{execution_repo}`")
        if base_branch:
            body_lines.append(f"- Base branch: `{base_branch}`")
            body_lines.append(
                "- PR rule: create follow-up PRs against the explicit base branch above; do not infer from local checkout state, `origin/HEAD`, or fallback-to-`main` behavior."
            )
        if highest_tier:
            body_lines.append(f"- Highest tier: `{highest_tier}`")
        if repo_note:
            body_lines.append(f"- Repo note: {repo_note}")
        body_lines.append("")
        body_lines.extend(
            build_execution_state_lines(
                open_dependencies=dependencies,
                manual_gates_remaining=blockers,
            )
        )
        if write_scope:
            body_lines.extend(["## Write Scope", *[f"- `{item}`" for item in write_scope], ""])
        if dependencies:
            body_lines.extend(["## Dependencies", *[f"- {item}" for item in dependencies], ""])
        if blockers:
            body_lines.extend(["## Blockers", *[f"- {item}" for item in blockers], ""])
        if dependency_analysis.issue_refs or blocker_analysis.issue_refs:
            body_lines.append("## Linked Issue Refs")
            if dependency_analysis.issue_refs:
                body_lines.extend(
                    ["- Depends on issue refs:", *[f"  - {item}" for item in dependency_analysis.issue_refs]]
                )
            if blocker_analysis.issue_refs:
                body_lines.extend(
                    ["- Blocked by issue refs:", *[f"  - {item}" for item in blocker_analysis.issue_refs]]
                )
            body_lines.append("")
        combined_dispatch_blockers = ordered_unique(
            [*automation_blockers, *plan_execution["dispatch_blockers"]]
        )
        if combined_dispatch_blockers:
            body_lines.extend(
                [
                    "## Dispatch Guardrails",
                    *[f"- {item}" for item in combined_dispatch_blockers],
                    "",
                ]
            )
        if gates:
            body_lines.extend(["## Named Gates", *[f"- {item}" for item in gates], ""])
        if validation_commands:
            body_lines.extend(
                ["## Validation Commands", *[f"- `{item}`" for item in validation_commands], ""]
            )
        body_lines.extend(
            [
                "## Excerpt",
                "```md",
                excerpt or "(no body found)",
                "```",
                "",
                "## Implementation Notes",
                "- Treat the Automation Issue Manifest leaf as the executable scope.",
                "- Keep dependencies explicit before local automation dispatch.",
            ]
        )
        drafts.append(
            IssueDraft(
                title=f"[{source_id}] {display_title}",
                body="\n".join(body_lines),
                labels=labels,
                kind="story",
                source_id=source_id,
                execution_repo=execution_repo,
                base_branch=base_branch,
                suggested_points=points,
                dependencies=dependencies,
                blocks=blocks,
                blockers=blockers,
                gates=gates,
                highest_tier=highest_tier,
                repo_targets=repo_targets,
                repo_note=repo_note,
                validation_requirements=validation_requirements,
                issue_ready=effective_issue_ready(issue_ready, points, automation_blockers),
                status_label=status_label,
                dispatch_recommendation=dispatch_recommendation,
                dispatch_mode=runtime_dispatch_mode,
                agent_type=agent_type,
                write_scope=write_scope,
                validation_commands=validation_commands,
                validation_scope=validation_scope,
                parallel_group=parallel_group,
                critical_path_rank=critical_path_rank,
                merge_group=merge_group,
                combine_policy=combine_policy,
                conflict_class=conflict_class,
                validation_tier=validation_tier,
                risk_tags=risk_tags,
                dependency_issue_refs=dependency_analysis.issue_refs,
                blocker_issue_refs=blocker_analysis.issue_refs,
                automation_blockers=automation_blockers,
                priority=priority,
            )
        )
    return drafts


def gh_issue_create(repo: str, draft: IssueDraft) -> str:
    ensure_labels_exist(repo, draft.labels)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False) as tmp:
        tmp.write(draft.body)
        tmp_path = Path(tmp.name)
    try:
        cmd = [
            "gh",
            "issue",
            "create",
            "--repo",
            repo,
            "--title",
            draft.title,
            "--body-file",
            str(tmp_path),
        ]
        for label in draft.labels:
            cmd.extend(["--label", label])
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True
        )
        return result.stdout.strip()
    finally:
        tmp_path.unlink(missing_ok=True)


FIELD_DATA_TYPES = {
    "Status": "SINGLE_SELECT",
    "ExecutionState": "SINGLE_SELECT",
    "ItemType": "SINGLE_SELECT",
    "Workstream": "TEXT",
    "TargetRepo": "TEXT",
    "ExecutionRepo": "TEXT",
    "BaseBranch": "TEXT",
    "PlanKey": "TEXT",
    "SourceId": "TEXT",
    "ParentEpic": "TEXT",
    "DependsOn": "TEXT",
    "Blocks": "TEXT",
    "ParallelGroup": "TEXT",
    "CriticalPathRank": "NUMBER",
    "MergeGroup": "TEXT",
    "CombinePolicy": "TEXT",
    "ConflictClass": "TEXT",
    "ValidationTier": "TEXT",
    "AutomationBlockers": "TEXT",
    "ReviewGates": "TEXT",
    "GateTier": "SINGLE_SELECT",
    "MergePoint": "TEXT",
    "DispatchMode": "SINGLE_SELECT",
    "DispatchRecommendation": "SINGLE_SELECT",
    "IssueReady": "SINGLE_SELECT",
    "AgentType": "SINGLE_SELECT",
    "AutomationState": "SINGLE_SELECT",
    "Priority": "SINGLE_SELECT",
    "Size": "NUMBER",
    "Risk": "SINGLE_SELECT",
    "RiskTags": "TEXT",
    "ValidationScope": "SINGLE_SELECT",
    "WriteScope": "TEXT",
    "OnePRContract": "SINGLE_SELECT",
    "ReviewVerdict": "SINGLE_SELECT",
    "ReviewRoute": "SINGLE_SELECT",
    "BlockerType": "TEXT",
    "BlockerReason": "TEXT",
    "Checks": "TEXT",
    "HeadSha": "TEXT",
    "TargetDate": "DATE",
    "ActivePR": "TEXT",
    "Validation": "TEXT",
}
PROJECT_FIELD_TYPES = FIELD_DATA_TYPES
PROJECT_CONFIG_CACHE: dict[tuple[str, int], dict[str, object]] = {}
PROJECT_ITEM_URL_CACHE: dict[tuple[str, int], dict[str, str]] = {}
PROJECT_ITEM_RECORD_CACHE: dict[tuple[str, int], dict[str, dict[str, object]]] = {}
PROJECT_ITEM_ID_RECORD_CACHE: dict[tuple[str, int], dict[str, dict[str, object]]] = {}


def parse_project_items(payload: object) -> list[object]:
    if isinstance(payload, dict):
        candidate_items = payload.get("items")
        return candidate_items if isinstance(candidate_items, list) else [payload]
    if isinstance(payload, list):
        return payload
    return []


def gh_project_item_url_map(
    project_owner: str,
    project_number: int,
    *,
    force_refresh: bool = False,
) -> dict[str, str]:
    cache_key = (project_owner, project_number)
    if not force_refresh and cache_key in PROJECT_ITEM_URL_CACHE:
        return PROJECT_ITEM_URL_CACHE[cache_key]

    list_cmd = [
        "gh",
        "project",
        "item-list",
        str(project_number),
        "--owner",
        project_owner,
        "--limit",
        str(GITHUB_PROJECT_ITEM_LIST_LIMIT),
        "--format",
        "json",
    ]
    listed = subprocess.run(
        list_cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    try:
        payload = json.loads(listed.stdout or "[]")
    except json.JSONDecodeError:
        payload = []

    item_by_url: dict[str, str] = {}
    item_by_url_record: dict[str, dict[str, object]] = {}
    item_by_id_record: dict[str, dict[str, object]] = {}
    for current in parse_project_items(payload):
        if not isinstance(current, dict):
            continue
        content = current.get("content")
        item_id = current.get("id")
        if isinstance(content, dict) and isinstance(item_id, str):
            url = content.get("url")
            if isinstance(url, str) and url:
                item_by_url[url] = item_id
                item_by_url_record[url] = current
                item_by_id_record[item_id] = current
    PROJECT_ITEM_URL_CACHE[cache_key] = item_by_url
    PROJECT_ITEM_RECORD_CACHE[cache_key] = item_by_url_record
    PROJECT_ITEM_ID_RECORD_CACHE[cache_key] = item_by_id_record
    return item_by_url


def gh_project_item_id_record_map(
    project_owner: str,
    project_number: int,
    *,
    force_refresh: bool = False,
) -> dict[str, dict[str, object]]:
    cache_key = (project_owner, project_number)
    if not force_refresh and cache_key in PROJECT_ITEM_ID_RECORD_CACHE:
        return PROJECT_ITEM_ID_RECORD_CACHE[cache_key]
    gh_project_item_url_map(project_owner, project_number, force_refresh=force_refresh)
    return PROJECT_ITEM_ID_RECORD_CACHE.get(cache_key, {})


def gh_project_add(project_owner: str, project_number: int, issue_url: str) -> str | None:
    existing_items = gh_project_item_url_map(project_owner, project_number)
    existing_item_id = existing_items.get(issue_url)
    if existing_item_id:
        return existing_item_id

    cmd = [
        "gh",
        "project",
        "item-add",
        str(project_number),
        "--owner",
        project_owner,
        "--url",
        issue_url,
        "--format",
        "json",
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True
        )
        payload = json.loads(result.stdout or "{}")
        item_id = payload.get("id")
        if item_id:
            item_id = str(item_id)
            existing_items[issue_url] = item_id
            PROJECT_ITEM_RECORD_CACHE.setdefault((project_owner, project_number), {})[issue_url] = payload
            PROJECT_ITEM_ID_RECORD_CACHE.setdefault((project_owner, project_number), {})[item_id] = payload
            return item_id
        return None
    except subprocess.CalledProcessError as exc:
        try:
            refreshed_items = gh_project_item_url_map(
                project_owner,
                project_number,
                force_refresh=True,
            )
        except subprocess.CalledProcessError:
            refreshed_items = {}
        refreshed_item_id = refreshed_items.get(issue_url)
        if refreshed_item_id:
            return refreshed_item_id

        stderr = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(
            f"failed to add {issue_url} to GitHub Project {project_owner}/{project_number}: "
            f"{stderr or exc}"
        ) from exc


def gh_project_config(project_owner: str, project_number: int) -> dict[str, object]:
    cache_key = (project_owner, project_number)
    cached = PROJECT_CONFIG_CACHE.get(cache_key)
    if cached is not None:
        return cached
    project = subprocess.run(
        ["gh", "project", "view", str(project_number), "--owner", project_owner, "--format", "json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    fields = subprocess.run(
        ["gh", "project", "field-list", str(project_number), "--owner", project_owner, "--format", "json", "--limit", "100"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    project_payload = json.loads(project.stdout or "{}")
    fields_payload = json.loads(fields.stdout or "{}")
    by_name: dict[str, dict[str, object]] = {}
    for field in fields_payload.get("fields") or []:
        if not isinstance(field, dict):
            continue
        name = field.get("name")
        if isinstance(name, str) and name:
            by_name[name] = field
    config: dict[str, object] = {
        "project_id": str(project_payload["id"]),
        "fields": by_name,
    }
    PROJECT_CONFIG_CACHE[cache_key] = config
    return config


def first_label_value(labels: list[str], prefix: str) -> str | None:
    for label in labels:
        if label.startswith(prefix):
            return label.split(":", 1)[1]
    return None


def issue_ready_project_value(draft: IssueDraft) -> str:
    if requires_decomposition(draft.suggested_points, draft.automation_blockers):
        return "Draft"
    if draft.status_label == "status:blocked" or draft.blockers or non_decomposition_automation_blockers(draft.automation_blockers):
        return "Blocked"
    if draft.issue_ready and draft.status_label == "status:ready":
        return "Ready"
    return "Draft"


def item_type_project_value(draft: IssueDraft) -> str:
    if draft.kind == "epic":
        return "Epic"
    if draft.kind == "spike":
        return "Spike"
    if draft.kind == "tracker":
        return "Tracker"
    return "Story"


def automation_state_project_value(draft: IssueDraft) -> str:
    if draft.kind == "epic":
        return "Planned"
    if requires_decomposition(draft.suggested_points, draft.automation_blockers):
        return "Manual"
    if draft.status_label == "status:blocked" or draft.blockers or draft.automation_blockers:
        return "Blocked"
    if draft.status_label == "status:draft":
        return "Draft"
    if draft.dispatch_recommendation == "tracking-only":
        return "Manual"
    if draft.dispatch_recommendation == "review-before-dispatch":
        return "Manual"
    if draft.suggested_points and draft.suggested_points > 1:
        return "Manual"
    if draft.dispatch_recommendation in {"auto-dispatch", "auto-dispatch-pilot"}:
        return "Ready"
    return "Planned"


def risk_project_value(draft: IssueDraft) -> str | None:
    tags = {tag.lower() for tag in draft.risk_tags}
    if tags & {"auth", "secrets", "migration", "cross-repo", "needs-deployed-validation", "ui-surface"}:
        return "High"
    if tags:
        return "Medium"
    return None


def one_pr_project_value(draft: IssueDraft) -> str:
    if draft.suggested_points == 1:
        return "Yes"
    if draft.suggested_points and draft.suggested_points > 1:
        return "No"
    return "N/A"


def blocker_type_project_value(draft: IssueDraft) -> str | None:
    if draft.automation_blockers:
        return "automation"
    if draft.blockers:
        return "manual"
    if draft.dependencies:
        return "dependency"
    return None


def agent_type_project_value(draft: IssueDraft) -> str | None:
    if draft.agent_type in ALLOWED_AGENT_TYPES:
        return draft.agent_type
    return None


def project_field_values(
    draft: IssueDraft,
    *,
    issue_repo: str,
    plan_key: str,
    parent_epic_url: str | None = None,
) -> dict[str, object]:
    labels = draft.labels
    target_repo = ", ".join(draft.repo_targets) if draft.repo_targets else issue_repo
    values: dict[str, object] = {
        "Status": "Todo",
        "ExecutionState": item_type_project_value(draft),
        "ItemType": item_type_project_value(draft),
        "Workstream": draft.source_id,
        "TargetRepo": target_repo,
        "ExecutionRepo": draft.execution_repo or issue_repo,
        "BaseBranch": draft.base_branch,
        "PlanKey": plan_key,
        "SourceId": draft.source_id,
        "ParentEpic": parent_epic_url,
        "DependsOn": "\n".join(draft.dependencies),
        "Blocks": "\n".join(draft.blocks or draft.blockers),
        "ParallelGroup": draft.parallel_group,
        "CriticalPathRank": draft.critical_path_rank,
        "MergeGroup": draft.merge_group,
        "CombinePolicy": draft.combine_policy,
        "ConflictClass": draft.conflict_class,
        "ValidationTier": draft.validation_tier,
        "AutomationBlockers": "\n".join(draft.automation_blockers),
        "ReviewGates": "\n".join(draft.gates),
        "GateTier": draft.highest_tier,
        "MergePoint": "\n".join(draft.merge_points),
        "DispatchMode": draft.dispatch_mode,
        "DispatchRecommendation": draft.dispatch_recommendation,
        "AgentType": agent_type_project_value(draft),
        "IssueReady": issue_ready_project_value(draft),
        "AutomationState": automation_state_project_value(draft),
        "Priority": draft.priority or (first_label_value(labels, "priority:") or "").upper() or None,
        "Size": draft.suggested_points,
        "Risk": risk_project_value(draft),
        "RiskTags": ", ".join(draft.risk_tags),
        "ValidationScope": draft.validation_scope,
        "WriteScope": "\n".join(draft.write_scope),
        "OnePRContract": one_pr_project_value(draft),
        "BlockerType": blocker_type_project_value(draft),
        "BlockerReason": "\n".join([*draft.blockers, *draft.automation_blockers]),
        "Validation": "\n".join([*draft.validation_commands, *draft.validation_requirements]),
    }
    return {name: value for name, value in values.items() if value not in (None, "", [])}


def gh_project_item_edit_value(
    *,
    project_id: str,
    item_id: str,
    field: dict[str, object],
    value: object,
) -> None:
    field_name = str(field.get("name") or "")
    data_type = FIELD_DATA_TYPES.get(field_name)
    if not data_type:
        return
    cmd = [
        "gh",
        "project",
        "item-edit",
        "--id",
        item_id,
        "--project-id",
        project_id,
        "--field-id",
        str(field["id"]),
    ]
    if data_type == "SINGLE_SELECT":
        options = {
            str(option.get("name")): str(option.get("id"))
            for option in field.get("options") or []
            if isinstance(option, dict) and option.get("name") and option.get("id")
        }
        option_id = options.get(str(value))
        if not option_id:
            return
        cmd.extend(["--single-select-option-id", option_id])
    elif data_type == "NUMBER":
        try:
            number_value = float(value)
        except (TypeError, ValueError):
            return
        cmd.extend(["--number", str(number_value)])
    elif data_type == "DATE":
        cmd.extend(["--date", str(value)])
    else:
        cmd.extend(["--text", str(value)])
    subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)


def project_field_payload_key(field_name: str) -> str:
    return field_name[:1].lower() + field_name[1:] if field_name else ""


def project_field_value_matches(
    *,
    field: dict[str, object],
    desired_value: object,
    current_item: dict[str, object] | None,
) -> bool:
    if not current_item:
        return False
    field_name = str(field.get("name") or "")
    payload_key = project_field_payload_key(field_name)
    if not payload_key or payload_key not in current_item:
        return False
    current_value = current_item.get(payload_key)
    data_type = FIELD_DATA_TYPES.get(field_name)
    if data_type == "NUMBER":
        try:
            return float(current_value) == float(desired_value)
        except (TypeError, ValueError):
            return False
    return str(current_value) == str(desired_value)


def gh_project_sync_issue_fields(
    project_owner: str,
    project_number: int,
    item_id: str | None,
    draft: IssueDraft,
    *,
    issue_repo: str,
    plan_key: str,
    parent_epic_url: str | None = None,
) -> None:
    if not item_id:
        return
    config = gh_project_config(project_owner, project_number)
    project_id = str(config["project_id"])
    fields = config["fields"]
    if not isinstance(fields, dict):
        return
    current_item = gh_project_item_id_record_map(project_owner, project_number).get(item_id)
    for name, value in project_field_values(
        draft,
        issue_repo=issue_repo,
        plan_key=plan_key,
        parent_epic_url=parent_epic_url,
    ).items():
        field = fields.get(name)
        if isinstance(field, dict):
            if project_field_value_matches(field=field, desired_value=value, current_item=current_item):
                continue
            gh_project_item_edit_value(project_id=project_id, item_id=item_id, field=field, value=value)
            if current_item is not None:
                current_item[project_field_payload_key(name)] = (
                    float(value) if FIELD_DATA_TYPES.get(name) == "NUMBER" else str(value)
                )


def label_metadata(name: str) -> tuple[str, str]:
    if name.startswith("type:"):
        return "b60205", "Projected issue type label"
    if name.startswith("workstream:"):
        return "bfdadc", "Planning projection workstream label"
    if name.startswith("repo:"):
        return "fbca04", "Target repository label"
    if name.startswith("status:"):
        return "d4c5f9", "Issue readiness label"
    if name.startswith("tier:"):
        return "5319e7", "Highest testing tier label"
    if name.startswith("area:"):
        return "1d76db", "Planning projection area label"
    if name.startswith("owner:"):
        return "0e8a16", "Planning projection owner label"
    if name == "ai-generated":
        return "5319e7", "AI-authored change"
    if name == "needs-review":
        return "fbca04", "Needs review"
    if name == "ai-ready":
        return "0e8a16", "Ready for AI dispatch"
    return "ededed", "Managed automation label"


def gh_repo_labels(repo: str) -> set[str]:
    cmd = [
        "gh",
        "label",
        "list",
        "--repo",
        repo,
        "--limit",
        "500",
        "--json",
        "name",
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True
    )
    payload = json.loads(result.stdout)
    return {item["name"] for item in payload if isinstance(item, dict) and item.get("name")}


def ensure_labels_exist(repo: str, labels: list[str]) -> None:
    desired = [label for label in ordered_unique(labels) if label]
    if not desired:
        return
    existing = gh_repo_labels(repo)
    for label in desired:
        if label in existing:
            continue
        color, description = label_metadata(label)
        cmd = [
            "gh",
            "label",
            "create",
            label,
            "--repo",
            repo,
            "--color",
            color,
            "--description",
            description,
        ]
        subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True
        )
        existing.add(label)


def gh_issue_edit(
    repo: str,
    number: int,
    *,
    title: str,
    body: str,
    add_labels: list[str],
    remove_labels: list[str],
) -> str:
    ensure_labels_exist(repo, add_labels)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False) as tmp:
        tmp.write(body)
        tmp_path = Path(tmp.name)
    try:
        cmd = [
            "gh",
            "issue",
            "edit",
            str(number),
            "--repo",
            repo,
            "--title",
            title,
            "--body-file",
            str(tmp_path),
        ]
        for label in add_labels:
            cmd.extend(["--add-label", label])
        for label in remove_labels:
            cmd.extend(["--remove-label", label])
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True
        )
        return result.stdout.strip()
    finally:
        tmp_path.unlink(missing_ok=True)


def load_existing_issues(repo: str, existing_issues_file: str | None = None) -> list[dict[str, object]]:
    if existing_issues_file:
        return json.loads(read_text(Path(existing_issues_file).expanduser().resolve()))
    cmd = [
        "gh",
        "issue",
        "list",
        "--repo",
        repo,
        "--state",
        "all",
        "--limit",
        str(GITHUB_ISSUE_LIST_LIMIT),
        "--json",
        "number,title,body,labels,url,state",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(result.stdout)


def _repo_cache_key(repo: str) -> str:
    return normalize_repo_slug(repo) or repo.strip()


def repos_needed_for_projection(epic_repo: str, children: list[IssueDraft]) -> list[str]:
    keys: list[str] = []
    epic_key = _repo_cache_key(epic_repo)
    keys.append(epic_key)
    for child in children:
        keys.append(_repo_cache_key(child.execution_repo or epic_repo))
    return ordered_unique(keys)


def load_existing_issues_map(
    *,
    epic_repo: str,
    children: list[IssueDraft],
    existing_issues_file: str | None,
) -> dict[str, list[dict[str, object]]]:
    needed = repos_needed_for_projection(epic_repo, children)
    if not existing_issues_file:
        return {key: load_existing_issues(key, None) for key in needed}

    path = Path(existing_issues_file).expanduser().resolve()
    raw = json.loads(read_text(path))
    if isinstance(raw, list):
        if len(needed) > 1:
            raise SystemExit(
                "Multi-repo sync requires --existing-issues-file to be a JSON object keyed by repo slug; "
                "the legacy JSON array format only supports a single epic repo."
            )
        result = {key: [] for key in needed}
        epic_key = _repo_cache_key(epic_repo)
        result[epic_key] = raw
        return result
    if isinstance(raw, dict):
        normalized_file: dict[str, list[dict[str, object]]] = {}
        for key, value in raw.items():
            if not isinstance(value, list):
                continue
            nk = _repo_cache_key(str(key))
            normalized_file[nk] = value
        return {key: normalized_file.get(key, []) for key in needed}
    raise SystemExit(
        "Invalid --existing-issues-file: expected a JSON array or an object mapping repo slug to issue arrays."
    )


def issue_landing_repo(epic_repo: str, draft: IssueDraft) -> str:
    """GitHub repo where this draft's issue is created or synced."""
    if draft.kind == "epic":
        return _repo_cache_key(epic_repo)
    if draft.execution_repo:
        return _repo_cache_key(draft.execution_repo)
    return _repo_cache_key(epic_repo)


def issue_label_names(issue: dict[str, object]) -> list[str]:
    labels = issue.get("labels", [])
    if not isinstance(labels, list):
        return []
    names: list[str] = []
    for label in labels:
        if isinstance(label, dict):
            name = label.get("name")
            if isinstance(name, str) and name:
                names.append(name)
        elif isinstance(label, str) and label:
            names.append(label)
    return sorted(set(ordered_unique(names)))


def normalized_issue_body(body: str) -> str:
    return body.replace("\r\n", "\n").replace("\r", "\n").rstrip()


def extract_issue_body_value(pattern: re.Pattern[str], body: str) -> str | None:
    match = pattern.search(body or "")
    if not match:
        return None
    value = match.group(1).strip()
    return value or None


def source_section_from_draft(draft: IssueDraft) -> str | None:
    return extract_issue_body_value(ISSUE_SOURCE_SECTION_RE, draft.body)


def epic_id_from_draft(draft: IssueDraft) -> str | None:
    return extract_issue_body_value(ISSUE_EPIC_ID_RE, draft.body)


def parent_epic_url_from_body(body: str) -> str | None:
    return extract_issue_body_value(ISSUE_PARENT_EPIC_RE, body)


def plan_path_matches(issue_plan_path: str | None, relative_plan_path: str) -> bool:
    if issue_plan_path == relative_plan_path:
        return True
    if issue_plan_path and issue_plan_path == Path(relative_plan_path).name:
        return True
    return False


def issue_state(issue: dict[str, object]) -> str:
    return str(issue.get("state") or "").upper()


def unique_issue_matches(matches: list[dict[str, object]]) -> list[dict[str, object]]:
    seen: set[tuple[object, object]] = set()
    unique: list[dict[str, object]] = []
    for match in matches:
        key = (match.get("number"), match.get("url"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(match)
    return unique


def choose_issue_match(
    matches: list[dict[str, object]],
    *,
    source_id: str,
    match_kind: str,
) -> dict[str, object] | None:
    unique = unique_issue_matches(matches)
    if not unique:
        return None
    if len(unique) == 1:
        return unique[0]

    open_matches = [match for match in unique if issue_state(match) == "OPEN"]
    if len(open_matches) == 1:
        return open_matches[0]

    raise SystemExit(
        f"{match_kind} match for {source_id!r} is ambiguous; projection remains fail-closed"
    )


def managed_label(name: str) -> bool:
    return name.startswith(
        (
            "type:",
            "workstream:",
            "repo:",
            "tier:",
            "status:",
            "area:",
            "owner:",
            "points:",
            "priority:",
            "agent:",
            "decomposition:",
        )
    )


def merged_labels_for_sync(existing_labels: list[str], desired_labels: list[str]) -> list[str]:
    preserved = [label for label in existing_labels if not managed_label(label)]
    return sorted(set([*preserved, *desired_labels]))


def desired_body_for_sync(draft: IssueDraft, *, parent_epic_url: str | None = None) -> str:
    if draft.kind != "story" or not parent_epic_url:
        return draft.body
    stripped = draft.body.rstrip()
    return "\n".join([stripped, "", "## Parent Epic", parent_epic_url])


def projection_preflight_report(drafts: list[IssueDraft]) -> dict[str, object]:
    errors: list[str] = []
    warnings: list[str] = []
    source_ids: dict[str, list[IssueDraft]] = {}
    invalid_labels: list[dict[str, object]] = []
    for draft in drafts:
        source_ids.setdefault(draft.source_id, []).append(draft)
        for label in draft.labels:
            if not label or len(label) > GITHUB_LABEL_NAME_MAX_LENGTH:
                invalid_labels.append(
                    {
                        "source_id": draft.source_id,
                        "label": label,
                        "length": len(label),
                        "max_length": GITHUB_LABEL_NAME_MAX_LENGTH,
                    }
                )
        if draft.status_label == "status:ready" and draft.dispatch_recommendation not in {
            "auto-dispatch",
            "auto-dispatch-pilot",
        }:
            errors.append(
                f"{draft.source_id}: status:ready requires an auto-dispatch recommendation."
            )
        if draft.dispatch_mode == "agent-ready" and (
            draft.kind == "epic"
            or requires_decomposition(draft.suggested_points, draft.automation_blockers)
        ):
            errors.append(
                f"{draft.source_id}: agent-ready is unsafe for parent or multi-point rows."
            )
        if draft.priority is None and draft.kind != "epic":
            warnings.append(
                f"{draft.source_id}: priority is missing; dry-run should infer or require it before apply."
            )
    duplicate_source_ids = [
        {
            "source_id": source_id,
            "titles": [draft.title for draft in matches],
        }
        for source_id, matches in sorted(source_ids.items())
        if len(matches) > 1
    ]
    for duplicate in duplicate_source_ids:
        errors.append(
            f"Duplicate SourceId {duplicate['source_id']!r} appears in the projected rows."
        )
    for label in invalid_labels:
        errors.append(
            f"{label['source_id']}: label {label['label']!r} is {label['length']} characters; "
            f"GitHub label names must be <= {label['max_length']} characters."
        )
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "duplicate_source_ids": duplicate_source_ids,
        "invalid_labels": invalid_labels,
    }


def enforce_projection_preflight(preflight: dict[str, object]) -> None:
    errors = preflight.get("errors")
    if isinstance(errors, list) and errors:
        raise SystemExit("Projection preflight failed:\n- " + "\n- ".join(str(e) for e in errors))


def find_matching_issue(
    draft: IssueDraft,
    *,
    existing_issues: list[dict[str, object]],
    relative_plan_path: str,
    registry_root_relative: str | None = None,
) -> dict[str, object] | None:
    desired_source_section = source_section_from_draft(draft)
    desired_epic_id = epic_id_from_draft(draft) if draft.kind == "epic" else None
    desired_plan_key = draft.source_id if draft.kind == "epic" and not desired_epic_id else None
    exact_title_matches: list[dict[str, object]] = []
    metadata_matches: list[dict[str, object]] = []
    legacy_number_matches: list[dict[str, object]] = []

    for issue in existing_issues:
        body = str(issue.get("body") or "")
        if (
            draft.kind != "epic"
            and isinstance(draft.legacy_issue_number, int)
            and issue.get("number") == draft.legacy_issue_number
        ):
            legacy_number_matches.append(issue)
            continue
        if registry_root_relative is not None:
            issue_registry = extract_issue_body_value(ISSUE_REGISTRY_ROOT_RE, body)
            if issue_registry != registry_root_relative:
                continue
        else:
            issue_plan_path = extract_issue_body_value(ISSUE_PLAN_PATH_RE, body)
            if not plan_path_matches(issue_plan_path, relative_plan_path):
                continue
        if draft.kind == "epic" and desired_epic_id:
            issue_epic_id = extract_issue_body_value(ISSUE_EPIC_ID_RE, body)
            if issue_epic_id == desired_epic_id:
                metadata_matches.append(issue)
            continue
        title = str(issue.get("title") or "")
        if title == draft.title:
            exact_title_matches.append(issue)
        issue_plan_key = extract_issue_body_value(ISSUE_PLAN_KEY_RE, body)
        issue_source_section = extract_issue_body_value(ISSUE_SOURCE_SECTION_RE, body)
        if draft.kind == "epic" and issue_plan_key == desired_plan_key:
            metadata_matches.append(issue)
        elif draft.kind != "epic" and desired_source_section and issue_source_section == desired_source_section:
            metadata_matches.append(issue)

    return (
        choose_issue_match(
            legacy_number_matches,
            source_id=draft.source_id,
            match_kind="legacy registry",
        )
        or choose_issue_match(
            metadata_matches,
            source_id=draft.source_id,
            match_kind="SourceId/source metadata",
        )
        or choose_issue_match(
            exact_title_matches,
            source_id=draft.source_id,
            match_kind="title",
        )
    )


def find_matching_issue_in_repos(
    draft: IssueDraft,
    *,
    preferred_repo: str,
    issues_by_repo: dict[str, list[dict[str, object]]],
    relative_plan_path: str,
    registry_root_relative: str | None = None,
) -> tuple[str, dict[str, object] | None]:
    match = find_matching_issue(
        draft,
        existing_issues=issues_by_repo.get(preferred_repo, []),
        relative_plan_path=relative_plan_path,
        registry_root_relative=registry_root_relative,
    )
    if match is not None:
        return preferred_repo, match

    fallback_matches: list[tuple[str, dict[str, object]]] = []
    for repo_key, issues in issues_by_repo.items():
        if repo_key == preferred_repo:
            continue
        repo_match = find_matching_issue(
            draft,
            existing_issues=issues,
            relative_plan_path=relative_plan_path,
            registry_root_relative=registry_root_relative,
        )
        if repo_match is not None:
            fallback_matches.append((repo_key, repo_match))

    if not fallback_matches:
        return preferred_repo, None
    if len(fallback_matches) == 1:
        return fallback_matches[0]

    open_fallbacks = [
        (repo_key, match)
        for repo_key, match in fallback_matches
        if issue_state(match) == "OPEN"
    ]
    if len(open_fallbacks) == 1:
        return open_fallbacks[0]

    raise SystemExit(
        f"cross-repo match for {draft.source_id!r} is ambiguous; projection remains fail-closed"
    )


def find_matching_epic_tracker_issue(
    epic: IssueDraft,
    children: list[IssueDraft],
    *,
    existing_issues: list[dict[str, object]],
    relative_plan_path: str,
    registry_root_relative: str | None = None,
) -> tuple[IssueDraft, dict[str, object]] | None:
    tracker_source_id = f"{epic.source_id}-epic-tracker"
    tracker = next((child for child in children if child.source_id == tracker_source_id), None)
    if tracker is None:
        return None
    match = find_matching_issue(
        tracker,
        existing_issues=existing_issues,
        relative_plan_path=relative_plan_path,
        registry_root_relative=registry_root_relative,
    )
    if match is None:
        return None
    return tracker, match


def build_sync_preview(
    *,
    epic_repo: str,
    plan_path: Path,
    epic: IssueDraft,
    children: list[IssueDraft],
    issues_by_repo: dict[str, list[dict[str, object]]],
    registry_root_relative: str | None = None,
) -> dict[str, object]:
    _, relative_plan_path, _ = plan_reference_context(plan_path)
    epic_key = issue_landing_repo(epic_repo, epic)
    epic_existing = issues_by_repo.get(epic_key, [])
    epic_match = find_matching_issue(
        epic,
        existing_issues=epic_existing,
        relative_plan_path=relative_plan_path,
        registry_root_relative=registry_root_relative,
    )
    tracker_adoption = (
        None
        if epic_match
        else find_matching_epic_tracker_issue(
            epic,
            children,
            existing_issues=epic_existing,
            relative_plan_path=relative_plan_path,
            registry_root_relative=registry_root_relative,
        )
    )
    tracker_adoption_source_id = tracker_adoption[0].source_id if tracker_adoption else None
    tracker_adoption_match = tracker_adoption[1] if tracker_adoption else None
    epic_url = (
        str(epic_match.get("url"))
        if epic_match
        else str(tracker_adoption_match.get("url"))
        if tracker_adoption_match
        else None
    )
    operations: list[dict[str, object]] = []
    matched_numbers_by_repo: dict[str, set[int]] = {
        key: set() for key in issues_by_repo
    }

    for draft in [epic, *children]:
        landing = issue_landing_repo(epic_repo, draft)
        if draft.kind == "epic" and not epic_match and tracker_adoption_match:
            existing_labels = issue_label_names(tracker_adoption_match)
            operations.append(
                {
                    "source_id": draft.source_id,
                    "kind": draft.kind,
                    "title": draft.title,
                    "issue_repo": landing,
                    "action": "use-existing-epic-tracker",
                    "changed_fields": [],
                    "match": {
                        "number": tracker_adoption_match.get("number"),
                        "title": tracker_adoption_match.get("title"),
                        "url": tracker_adoption_match.get("url"),
                    },
                    "labels": {
                        "existing": existing_labels,
                        "desired": existing_labels,
                        "add": [],
                        "remove": [],
                    },
                    "dispatch_recommendation": draft.dispatch_recommendation,
                    "validation_scope": draft.validation_scope,
                    "risk_tags": draft.risk_tags,
                    "body_changed": False,
                    "note": "Typed registry epic will use the existing epic-tracker issue as the parent surface; no duplicate epic issue will be created.",
                }
            )
            if isinstance(tracker_adoption_match.get("number"), int):
                matched_numbers_by_repo[landing].add(int(tracker_adoption_match["number"]))
            continue
        issue_repo, match = find_matching_issue_in_repos(
            draft,
            preferred_repo=landing,
            issues_by_repo=issues_by_repo,
            relative_plan_path=relative_plan_path,
            registry_root_relative=registry_root_relative,
        )
        if match and isinstance(match.get("number"), int):
            matched_numbers_by_repo.setdefault(issue_repo, set()).add(int(match["number"]))
        existing_labels = issue_label_names(match or {})
        desired_labels = merged_labels_for_sync(existing_labels, draft.labels)
        parent_epic_url = (
            None
            if draft.kind == "epic" or draft.source_id == tracker_adoption_source_id
            else epic_url or parent_epic_url_from_body(str((match or {}).get("body") or ""))
        )
        desired_body = desired_body_for_sync(draft, parent_epic_url=parent_epic_url)
        if match and draft.kind == "story" and isinstance(match.get("number"), int):
            desired_body = rebind_body_execution_issue_key(
                desired_body,
                issue_repo=issue_repo,
                issue_number=int(match["number"]),
            )
        changed_fields: list[str] = []
        label_additions = [label for label in desired_labels if label not in existing_labels]
        label_removals = [label for label in existing_labels if label not in desired_labels]
        if not match:
            changed_fields = ["title", "body", "labels"]
            action = "create-missing"
        else:
            if str(match.get("title") or "") != draft.title:
                changed_fields.append("title")
            if normalized_issue_body(str(match.get("body") or "")) != normalized_issue_body(desired_body):
                changed_fields.append("body")
            if existing_labels != desired_labels:
                changed_fields.append("labels")
            action = "update" if changed_fields else "noop"
        operations.append(
            {
                "source_id": draft.source_id,
                "kind": draft.kind,
                "title": draft.title,
                "issue_repo": issue_repo,
                "desired_issue_repo": landing,
                "matched_outside_landing_repo": bool(match and issue_repo != landing),
                "action": action,
                "changed_fields": changed_fields,
                "match": None
                if not match
                else {
                    "number": match.get("number"),
                    "title": match.get("title"),
                    "url": match.get("url"),
                },
                "labels": {
                    "existing": existing_labels,
                    "desired": desired_labels,
                    "add": label_additions,
                    "remove": label_removals,
                },
                "dispatch_recommendation": draft.dispatch_recommendation,
                "validation_scope": draft.validation_scope,
                "risk_tags": draft.risk_tags,
                "body_changed": "body" in changed_fields,
            }
        )

    unmatched_existing: list[dict[str, object]] = []
    for cache_repo, issue_list in issues_by_repo.items():
        matched_numbers = matched_numbers_by_repo.get(cache_repo, set())
        for issue in issue_list:
            number = issue.get("number")
            if not isinstance(number, int) or number in matched_numbers:
                continue
            body = str(issue.get("body") or "")
            if registry_root_relative is not None:
                if extract_issue_body_value(ISSUE_REGISTRY_ROOT_RE, body) != registry_root_relative:
                    continue
            elif not plan_path_matches(extract_issue_body_value(ISSUE_PLAN_PATH_RE, body), relative_plan_path):
                continue
            unmatched_existing.append(
                {
                    "repo": cache_repo,
                    "number": number,
                    "title": issue.get("title"),
                    "url": issue.get("url"),
                }
            )

    result: dict[str, object] = {
        "repo": epic_repo,
        "epic_repo": epic_repo,
        "repos_considered": list(issues_by_repo.keys()),
        "plan_path": relative_plan_path,
        "operations": operations,
        "unmatched_existing": unmatched_existing,
    }
    if registry_root_relative is not None:
        result["registry_root"] = registry_root_relative
    return result


def apply_sync_operations(
    *,
    epic_repo: str,
    project_owner: str | None,
    project_number: int | None,
    plan_path: Path,
    epic: IssueDraft,
    children: list[IssueDraft],
    issues_by_repo: dict[str, list[dict[str, object]]],
    registry_root_relative: str | None = None,
) -> dict[str, object]:
    _, relative_plan_path, _ = plan_reference_context(plan_path)
    epic_key = issue_landing_repo(epic_repo, epic)
    epic_existing = issues_by_repo.get(epic_key, [])
    created: list[dict[str, object]] = []
    updated: list[dict[str, object]] = []
    unchanged: list[dict[str, object]] = []

    epic_match = find_matching_issue(
        epic,
        existing_issues=epic_existing,
        relative_plan_path=relative_plan_path,
        registry_root_relative=registry_root_relative,
    )
    tracker_adoption = (
        None
        if epic_match
        else find_matching_epic_tracker_issue(
            epic,
            children,
            existing_issues=epic_existing,
            relative_plan_path=relative_plan_path,
            registry_root_relative=registry_root_relative,
        )
    )
    tracker_adoption_source_id = tracker_adoption[0].source_id if tracker_adoption else None
    tracker_adoption_match = tracker_adoption[1] if tracker_adoption else None
    epic_existing_labels = issue_label_names(epic_match or {})
    epic_desired_labels = merged_labels_for_sync(epic_existing_labels, epic.labels)
    epic_remove = [label for label in epic_existing_labels if label not in epic_desired_labels]
    epic_add = [label for label in epic_desired_labels if label not in epic_existing_labels]

    if epic_match:
        epic_body = desired_body_for_sync(epic)
        epic_changed_fields: list[str] = []
        if str(epic_match.get("title") or "") != epic.title:
            epic_changed_fields.append("title")
        if normalized_issue_body(str(epic_match.get("body") or "")) != normalized_issue_body(epic_body):
            epic_changed_fields.append("body")
        if epic_existing_labels != epic_desired_labels:
            epic_changed_fields.append("labels")
        if epic_changed_fields:
            gh_issue_edit(
                epic_key,
                int(epic_match["number"]),
                title=epic.title,
                body=epic_body,
                add_labels=epic_add,
                remove_labels=epic_remove,
            )
            epic_url = str(epic_match["url"])
            updated.append(
                {
                    "source_id": epic.source_id,
                    "kind": epic.kind,
                    "issue_repo": epic_key,
                    "number": epic_match["number"],
                    "url": epic_url,
                    "changed_fields": epic_changed_fields,
                }
            )
        else:
            epic_url = str(epic_match["url"])
            unchanged.append(
                {
                    "source_id": epic.source_id,
                    "kind": epic.kind,
                    "issue_repo": epic_key,
                    "number": epic_match["number"],
                    "url": epic_url,
                }
            )
    else:
        if tracker_adoption_match:
            epic_url = str(tracker_adoption_match["url"])
            unchanged.append(
                {
                    "source_id": epic.source_id,
                    "kind": epic.kind,
                    "issue_repo": epic_key,
                    "number": tracker_adoption_match["number"],
                    "url": epic_url,
                    "adopted_epic_tracker": tracker_adoption_source_id,
                }
            )
        else:
            epic_url = gh_issue_create(epic_key, epic)
            created.append(
                {
                    "source_id": epic.source_id,
                    "kind": epic.kind,
                    "issue_repo": epic_key,
                    "url": epic_url,
                }
            )
    if project_owner and project_number:
        item_id = gh_project_add(project_owner, project_number, epic_url)
        gh_project_sync_issue_fields(
            project_owner,
            project_number,
            item_id,
            epic,
            issue_repo=epic_key,
            plan_key=epic.source_id,
        )

    for child in children:
        landing = issue_landing_repo(epic_repo, child)
        issue_repo, match = find_matching_issue_in_repos(
            child,
            preferred_repo=landing,
            issues_by_repo=issues_by_repo,
            relative_plan_path=relative_plan_path,
            registry_root_relative=registry_root_relative,
        )
        existing_labels = issue_label_names(match or {})
        desired_labels = merged_labels_for_sync(existing_labels, child.labels)
        add_labels = [label for label in desired_labels if label not in existing_labels]
        remove_labels = [label for label in existing_labels if label not in desired_labels]
        child_parent_epic_url = None if child.source_id == tracker_adoption_source_id else epic_url
        body = desired_body_for_sync(child, parent_epic_url=child_parent_epic_url)

        if match:
            issue_url = str(match["url"])
            body = rebind_body_execution_issue_key(
                body,
                issue_repo=issue_repo,
                issue_number=int(match["number"]),
            )
            changed_fields: list[str] = []
            if str(match.get("title") or "") != child.title:
                changed_fields.append("title")
            if normalized_issue_body(str(match.get("body") or "")) != normalized_issue_body(body):
                changed_fields.append("body")
            if existing_labels != desired_labels:
                changed_fields.append("labels")
            if changed_fields:
                gh_issue_edit(
                    issue_repo,
                    int(match["number"]),
                    title=child.title,
                    body=body,
                    add_labels=add_labels,
                    remove_labels=remove_labels,
                )
                updated.append(
                    {
                        "source_id": child.source_id,
                        "kind": child.kind,
                        "issue_repo": issue_repo,
                        "desired_issue_repo": landing,
                        "number": match["number"],
                        "url": issue_url,
                        "changed_fields": changed_fields,
                    }
                )
            else:
                unchanged.append(
                    {
                        "source_id": child.source_id,
                        "kind": child.kind,
                        "issue_repo": issue_repo,
                        "desired_issue_repo": landing,
                        "number": match["number"],
                        "url": issue_url,
                    }
                )
            if project_owner and project_number:
                item_id = gh_project_add(project_owner, project_number, issue_url)
                gh_project_sync_issue_fields(
                    project_owner,
                    project_number,
                    item_id,
                    child,
                    issue_repo=issue_repo,
                    plan_key=epic.source_id,
                    parent_epic_url=child_parent_epic_url,
                )
            continue

        issue_url = gh_issue_create(
            landing,
            IssueDraft(
                title=child.title,
                body=body,
                labels=child.labels,
                kind=child.kind,
                source_id=child.source_id,
                execution_repo=child.execution_repo,
                base_branch=child.base_branch,
                suggested_points=child.suggested_points,
                dependencies=child.dependencies,
                blockers=child.blockers,
                merge_points=child.merge_points,
                gates=child.gates,
                highest_tier=child.highest_tier,
                repo_targets=child.repo_targets,
                repo_note=child.repo_note,
                validation_requirements=child.validation_requirements,
                unstable_reasons=child.unstable_reasons,
                issue_ready=child.issue_ready,
                azure_closeout_only=child.azure_closeout_only,
                status_label=child.status_label,
                dispatch_recommendation=child.dispatch_recommendation,
                validation_scope=child.validation_scope,
                risk_tags=child.risk_tags,
            ),
        )
        created.append(
            {
                "source_id": child.source_id,
                "kind": child.kind,
                "issue_repo": landing,
                "url": issue_url,
            }
        )
        created_issue_ref = issue_ref_from_url(issue_url)
        if created_issue_ref is not None:
            rebound_body = rebind_body_execution_issue_key(
                body,
                issue_repo=created_issue_ref[0],
                issue_number=created_issue_ref[1],
            )
            if rebound_body != body:
                gh_issue_edit(
                    created_issue_ref[0],
                    created_issue_ref[1],
                    title=child.title,
                    body=rebound_body,
                    add_labels=[],
                    remove_labels=[],
                )
        if project_owner and project_number:
            item_id = gh_project_add(project_owner, project_number, issue_url)
            gh_project_sync_issue_fields(
                project_owner,
                project_number,
                item_id,
                child,
                issue_repo=landing,
                plan_key=epic.source_id,
                parent_epic_url=child_parent_epic_url,
            )

    return {
        "epic_repo": epic_repo,
        "repos_considered": list(issues_by_repo.keys()),
        "created": created,
        "updated": updated,
        "unchanged": unchanged,
    }


def run_registry_projection(
    args: argparse.Namespace,
    project_owner: str | None,
    project_number: int | None,
) -> int:
    """WS2 registry-backed dry-run / sync-preview / sync-apply / --apply entrypoint."""
    registry_root = Path(args.registry_root).expanduser().resolve()
    selection = RegistrySelection(
        project_id=args.registry_project_id,
        epic_id=args.registry_epic_id,
        story_ids=tuple(args.registry_story_id or ()),
    )
    try:
        portfolio = load_registry_portfolio(registry_root, selection=selection)
    except RegistryLoadError as exc:
        raise SystemExit(str(exc)) from exc

    repo = args.repo
    if (args.apply or args.sync_preview or args.sync_apply) and not repo:
        raise SystemExit(
            "Missing target repo. Pass `--repo` for registry-backed sync modes or legacy `--apply`."
        )

    plan_execution = build_registry_plan_execution_context(repo=repo, stories=portfolio.stories)
    try:
        children, join_diag = build_registry_story_drafts(
            portfolio,
            issue_repo=repo,
            plan_execution=plan_execution,
            strategy=args.strategy,
        )
    except JoinMetadataEncodeError as exc:
        raise SystemExit(f"Join metadata encoding failed: {exc}") from exc

    epic = build_registry_epic(portfolio, issue_repo=repo, plan_execution=plan_execution)
    stability = build_registry_stability_summary(repo=repo, children=children, plan_execution=plan_execution)
    epic_status_label = "status:draft"
    epic.labels = sorted(
        set([label for label in epic.labels if not label.startswith("status:")] + [epic_status_label])
    )
    epic.status_label = epic_status_label
    relative_registry_anchor = display_plan_path(registry_root)
    preflight = projection_preflight_report([epic, *children])

    payload: dict[str, object] = {
        "plan": relative_registry_anchor,
        "repo": repo,
        "strategy": args.strategy,
        "source_kind": "registry",
        "registry": {
            "registry_root": relative_registry_anchor,
            "project_id": portfolio.project.get("project_id"),
            "epic_id": portfolio.epic.get("epic_id"),
            "story_count": len(children),
            "merge_point_records": len(portfolio.merge_points),
            "gate_records": len(portfolio.gates),
            "policy_records": len(portfolio.policies),
            "join_metadata_projection": join_diag,
        },
        "join_metadata_contract": {
            "schema": JOIN_METADATA_SCHEMA,
            "checksum": "sha256",
            "canonical_json": "minified-sorted-keys-utf8",
            "wire_encoding": "base64-of-canonical-json-in-sharded-envelopes",
            "primary_budget_bytes": JOIN_METADATA_PRIMARY_BUDGET_BYTES,
            "extension_shard_max": JOIN_METADATA_EXTENSION_SHARD_MAX,
            "extension_budget_bytes_each": JOIN_METADATA_EXTENSION_BUDGET_BYTES,
            "total_budget_bytes": JOIN_METADATA_TOTAL_BUDGET_BYTES,
        },
        "epic": asdict(epic),
        "children": [asdict(child) for child in children],
        "project": {
            "name": portfolio.project.get("title") or portfolio.project.get("project_id"),
            "owner": project_owner,
            "number": project_number,
        },
        "plan_execution": plan_execution,
        "stability": stability,
        "preflight": preflight,
    }

    plan_path_anchor = registry_root

    if args.dry_run:
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if args.sync_preview:
        issues_by_repo = load_existing_issues_map(
            epic_repo=repo,
            children=children,
            existing_issues_file=args.existing_issues_file,
        )
        sync_preview = build_sync_preview(
            epic_repo=repo,
            plan_path=plan_path_anchor,
            epic=epic,
            children=children,
            issues_by_repo=issues_by_repo,
            registry_root_relative=relative_registry_anchor,
        )
        payload["sync_preview"] = sync_preview
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    enforce_projection_preflight(preflight)

    if args.sync_apply:
        issues_by_repo = load_existing_issues_map(
            epic_repo=repo,
            children=children,
            existing_issues_file=args.existing_issues_file,
        )
        sync_result = apply_sync_operations(
            epic_repo=repo,
            project_owner=project_owner,
            project_number=project_number,
            plan_path=plan_path_anchor,
            epic=epic,
            children=children,
            issues_by_repo=issues_by_repo,
            registry_root_relative=relative_registry_anchor,
        )
        payload["sync_apply"] = sync_result
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    created: list[dict[str, str]] = []
    epic_landing = issue_landing_repo(repo, epic)
    epic_url = gh_issue_create(epic_landing, epic)
    created.append(
        {"kind": "epic", "title": epic.title, "url": epic_url, "repo": epic_landing}
    )
    if project_owner and project_number:
        item_id = gh_project_add(project_owner, project_number, epic_url)
        gh_project_sync_issue_fields(
            project_owner,
            project_number,
            item_id,
            epic,
            issue_repo=epic_landing,
            plan_key=epic.source_id,
        )

    for child in children:
        child.body = "\n".join(
            [
                child.body,
                "",
                "## Parent Epic",
                epic_url,
            ]
        )
        child_landing = issue_landing_repo(repo, child)
        issue_url = gh_issue_create(child_landing, child)
        created.append(
            {
                "kind": child.kind,
                "title": child.title,
                "url": issue_url,
                "repo": child_landing,
            }
        )
        if project_owner and project_number:
            item_id = gh_project_add(project_owner, project_number, issue_url)
            gh_project_sync_issue_fields(
                project_owner,
                project_number,
                item_id,
                child,
                issue_repo=child_landing,
                plan_key=epic.source_id,
                parent_epic_url=epic_url,
            )

    json.dump({"created": created}, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def main() -> int:
    args = parse_args()
    if bool(args.plan) == bool(args.registry_root):
        raise SystemExit("Specify exactly one of --plan or --registry-root.")

    project_owner = args.project_owner
    project_number = args.project_number
    if args.project_url:
        parsed_owner, parsed_number = parse_project_url(args.project_url)
        if project_owner and project_owner != parsed_owner:
            raise SystemExit(
                f"Project owner mismatch: --project-owner={project_owner!r} "
                f"but --project-url implies {parsed_owner!r}."
            )
        if project_number and project_number != parsed_number:
            raise SystemExit(
                f"Project number mismatch: --project-number={project_number!r} "
                f"but --project-url implies {parsed_number!r}."
            )
        project_owner = parsed_owner
        project_number = parsed_number

    if args.registry_root:
        return run_registry_projection(args, project_owner, project_number)

    plan_path = Path(args.plan).expanduser().resolve()
    plan_display_path = display_plan_path(plan_path)
    text = read_text(plan_path)
    frontmatter = parse_frontmatter(text)
    repo = args.repo or frontmatter.get("tracking.epicRepo")
    if (args.apply or args.sync_preview or args.sync_apply) and not repo:
        raise SystemExit(
            "Missing target repo. Pass --repo or add tracking.epicRepo to the plan frontmatter."
        )
    markdown = strip_frontmatter(text)
    heading = first_heading(markdown)
    plan_base_branch = extract_plan_state_value(markdown, "BaseBranch")
    plan_key = infer_plan_key(frontmatter.get("name", ""), plan_path.stem, heading)
    lines = markdown.splitlines()
    owner_repo_targets = collect_owner_repo_targets(markdown)
    global_blockers = collect_explicit_blockers(markdown)
    decisions = collect_plan_decisions(markdown)
    stability_notes = collect_stability_notes(markdown)
    azure_runner_inputs = collect_azure_runner_inputs(markdown)
    all_gates = collect_all_gates(markdown)
    if args.strategy == "leaf-issues":
        sections = collect_automation_manifest_sections(lines)
        child_kind = "story"
    elif args.strategy == "workstreams":
        sections = collect_workstream_sections(lines)
        child_kind = "story"
    else:
        sections = collect_sections(lines, PHASE_HEADING_RE)
        child_kind = "story"
    plan_execution = build_plan_execution_context(
        frontmatter=frontmatter,
        markdown=markdown,
        repo=repo,
        sections=sections,
    )

    if args.strategy == "leaf-issues":
        children = build_manifest_leaf_children(
            plan_path,
            plan_display_path,
            plan_key,
            frontmatter,
            sections,
            issue_repo=repo,
            plan_base_branch=plan_base_branch,
            plan_execution=plan_execution,
        )
    else:
        children = build_children(
            plan_path,
            plan_display_path,
            plan_key,
            frontmatter,
            sections,
            child_kind,
            issue_repo=repo,
            owner_repo_targets=owner_repo_targets,
            global_blockers=global_blockers,
            decisions=decisions,
            azure_runner_inputs=azure_runner_inputs,
            stability_notes=stability_notes,
            all_gates=all_gates,
            plan_base_branch=plan_base_branch,
            plan_execution=plan_execution,
        )
    epic_repo_targets = ordered_unique(
        repo_target
        for child in children
        for repo_target in child.repo_targets
    ) or ordered_unique(
        repo_target
        for repo_targets in owner_repo_targets.values()
        for repo_target in repo_targets
    )
    epic = build_epic(
        plan_path,
        plan_display_path,
        frontmatter,
        heading,
        markdown,
        issue_repo=repo,
        global_blockers=global_blockers,
        repo_targets=epic_repo_targets,
        azure_runner_inputs=azure_runner_inputs,
        stability_notes=stability_notes,
        plan_base_branch=plan_base_branch,
        plan_execution=plan_execution,
    )
    stability = build_stability_summary(
        repo=repo,
        sections=sections,
        children=children,
        explicit_blockers=global_blockers,
        plan_execution=plan_execution,
    )
    epic_status_label = "status:draft"
    epic.labels = sorted(
        set([label for label in epic.labels if not label.startswith("status:")] + [epic_status_label])
    )
    epic.status_label = epic_status_label
    preflight = projection_preflight_report([epic, *children])

    payload = {
        "plan": plan_display_path,
        "repo": repo,
        "strategy": args.strategy,
        "source_kind": "plan",
        "epic": asdict(epic),
        "children": [asdict(child) for child in children],
        "project": {
            "name": frontmatter.get("tracking.project"),
            "owner": project_owner,
            "number": project_number,
        },
        "plan_execution": plan_execution,
        "stability": stability,
        "preflight": preflight,
    }

    if args.dry_run:
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if args.sync_preview:
        issues_by_repo = load_existing_issues_map(
            epic_repo=repo,
            children=children,
            existing_issues_file=args.existing_issues_file,
        )
        sync_preview = build_sync_preview(
            epic_repo=repo,
            plan_path=plan_path,
            epic=epic,
            children=children,
            issues_by_repo=issues_by_repo,
            registry_root_relative=None,
        )
        payload["sync_preview"] = sync_preview
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    enforce_projection_preflight(preflight)

    if args.sync_apply:
        issues_by_repo = load_existing_issues_map(
            epic_repo=repo,
            children=children,
            existing_issues_file=args.existing_issues_file,
        )
        sync_result = apply_sync_operations(
            epic_repo=repo,
            project_owner=project_owner,
            project_number=project_number,
            plan_path=plan_path,
            epic=epic,
            children=children,
            issues_by_repo=issues_by_repo,
            registry_root_relative=None,
        )
        payload["sync_apply"] = sync_result
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    created: list[dict[str, str]] = []
    epic_landing = issue_landing_repo(repo, epic)
    epic_url = gh_issue_create(epic_landing, epic)
    created.append(
        {"kind": "epic", "title": epic.title, "url": epic_url, "repo": epic_landing}
    )
    if project_owner and project_number:
        item_id = gh_project_add(project_owner, project_number, epic_url)
        gh_project_sync_issue_fields(
            project_owner,
            project_number,
            item_id,
            epic,
            issue_repo=epic_landing,
            plan_key=epic.source_id,
        )

    for child in children:
        child.body = "\n".join(
            [
                child.body,
                "",
                "## Parent Epic",
                epic_url,
            ]
        )
        child_landing = issue_landing_repo(repo, child)
        issue_url = gh_issue_create(child_landing, child)
        created.append(
            {
                "kind": child.kind,
                "title": child.title,
                "url": issue_url,
                "repo": child_landing,
            }
        )
        if project_owner and project_number:
            item_id = gh_project_add(project_owner, project_number, issue_url)
            gh_project_sync_issue_fields(
                project_owner,
                project_number,
                item_id,
                child,
                issue_repo=child_landing,
                plan_key=epic.source_id,
                parent_epic_url=epic_url,
            )

    json.dump({"created": created}, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
