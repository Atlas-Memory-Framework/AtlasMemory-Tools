from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "manifests" / "atlas-tools.v1.json"
HEADER_PREFIX = "atlas-tools-generated:"
HEADER_END = "atlas-tools-generated-end"


@dataclass(frozen=True)
class GeneratedFile:
    source: Path
    target: Path
    checksum: str


def load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_checksum(relative_source: str) -> str:
    return sha256_bytes((REPO_ROOT / relative_source).read_bytes())


def harness_config(manifest: dict, harness: str) -> dict:
    adapters = manifest.get("adapters") or {}
    if harness not in adapters:
        valid = ", ".join(sorted(adapters))
        raise SystemExit(f"Unknown harness {harness!r}. Expected one of: {valid}")
    return adapters[harness]


def iter_source_files(relative_dir: str) -> list[Path]:
    root = REPO_ROOT / relative_dir
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    )


def generated_header(relative_source: str, manifest_version: str, checksum: str, prefix: str) -> str:
    return (
        f"{prefix} {HEADER_PREFIX} "
        f"source={relative_source} manifest={manifest_version} checksum=sha256:{checksum}\n"
        f"{prefix} {HEADER_END}\n"
    )


def render_generated(relative_source: str, manifest_version: str) -> bytes:
    source_path = REPO_ROOT / relative_source
    data = source_path.read_bytes()
    checksum = sha256_bytes(data)
    text = data.decode("utf-8")
    suffix = source_path.suffix.lower()

    if text.startswith("#!"):
        first, sep, rest = text.partition("\n")
        rendered = first + sep + generated_header(relative_source, manifest_version, checksum, "#") + rest
        return rendered.encode("utf-8")

    if suffix == ".md" and text.startswith("---\n"):
        first, sep, rest = text.partition("\n")
        rendered = first + sep + generated_header(relative_source, manifest_version, checksum, "#") + rest
        return rendered.encode("utf-8")

    if suffix in {".py", ".sh"} or source_path.name.startswith("atlas-agent"):
        return (generated_header(relative_source, manifest_version, checksum, "#") + text).encode("utf-8")

    if suffix == ".json":
        return data

    return (
        f"<!-- {HEADER_PREFIX} source={relative_source} manifest={manifest_version} checksum=sha256:{checksum} -->\n"
        f"<!-- {HEADER_END} -->\n"
        + text
    ).encode("utf-8")


def strip_generated_header(data: bytes) -> tuple[dict[str, str] | None, bytes]:
    text = data.decode("utf-8")
    lines = text.splitlines(keepends=True)
    search_limit = min(4, len(lines))
    for idx in range(search_limit):
        line = lines[idx]
        marker_index = line.find(HEADER_PREFIX)
        if marker_index < 0:
            continue
        metadata_text = line[marker_index + len(HEADER_PREFIX) :].strip()
        if metadata_text.endswith("-->"):
            metadata_text = metadata_text[:-3].strip()
        metadata: dict[str, str] = {}
        for part in metadata_text.split():
            if "=" in part:
                key, value = part.split("=", 1)
                metadata[key] = value
        end_idx = idx + 1
        if end_idx < len(lines) and HEADER_END in lines[end_idx]:
            end_idx += 1
        body = "".join(lines[:idx] + lines[end_idx:]).encode("utf-8")
        return metadata, body
    return None, data


def target_roots_for(harness: str, target: Path, manifest: dict) -> tuple[Path, Path]:
    config = harness_config(manifest, harness)
    return target / config["skills_path"], target / config["agents_path"]


def planned_files(harness: str, target: Path, manifest: dict | None = None) -> list[GeneratedFile]:
    manifest = manifest or load_manifest()
    version = str(manifest["version"])
    skills_root, agents_root = target_roots_for(harness, target, manifest)
    files: list[GeneratedFile] = []

    for skill in manifest.get("skills", []):
        skill_name = skill["name"]
        source_dir = Path(skill["path"])
        for source in iter_source_files(skill["path"]):
            rel_source = source.relative_to(REPO_ROOT).as_posix()
            rel_inside = source.relative_to(REPO_ROOT / source_dir)
            target_path = skills_root / skill_name / rel_inside
            files.append(
                GeneratedFile(
                    source=source,
                    target=target_path,
                    checksum=source_checksum(rel_source),
                )
            )

    for agent in manifest.get("agents", []):
        rel_source = agent["path"]
        source = REPO_ROOT / rel_source
        target_path = agents_root / Path(rel_source).name
        files.append(GeneratedFile(source=source, target=target_path, checksum=source_checksum(rel_source)))

    return files


def install_harness(harness: str, target: Path, *, check: bool = False) -> list[Path]:
    manifest = load_manifest()
    version = str(manifest["version"])
    changed: list[Path] = []
    for item in planned_files(harness, target, manifest):
        relative_source = item.source.relative_to(REPO_ROOT).as_posix()
        rendered = render_generated(relative_source, version)
        existing = item.target.read_bytes() if item.target.exists() else None
        if existing == rendered:
            continue
        changed.append(item.target)
        if not check:
            item.target.parent.mkdir(parents=True, exist_ok=True)
            item.target.write_bytes(rendered)
            shutil.copymode(item.source, item.target)
    return changed


def verify_generated_file(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        metadata, body = strip_generated_header(path.read_bytes())
    except UnicodeDecodeError:
        return []
    if not metadata:
        return [f"{path}: missing generated header"]
    source = metadata.get("source")
    checksum = metadata.get("checksum", "")
    if not source:
        return [f"{path}: generated header missing source"]
    source_path = REPO_ROOT / source
    if not source_path.exists():
        return [f"{path}: source does not exist: {source}"]
    source_bytes = source_path.read_bytes()
    actual_checksum = "sha256:" + sha256_bytes(source_bytes)
    if checksum != actual_checksum:
        errors.append(f"{path}: checksum is stale for {source}")
    if body != source_bytes:
        errors.append(f"{path}: generated body differs from {source}")
    return errors


def verify_harness_target(target: Path) -> list[str]:
    errors: list[str] = []
    manifest = load_manifest()
    installed_harnesses: list[str] = []
    roots: list[Path] = []
    planned_targets: set[Path] = set()
    for harness, adapter in (manifest.get("adapters") or {}).items():
        skills_root = target / adapter["skills_path"]
        agents_root = target / adapter["agents_path"]
        if skills_root.exists() or agents_root.exists():
            installed_harnesses.append(harness)
            roots.extend([skills_root, agents_root])

    for harness in installed_harnesses:
        for item in planned_files(harness, target, manifest):
            planned_targets.add(item.target)
            if not item.target.exists():
                errors.append(f"{item.target}: missing generated file")
            else:
                errors.extend(verify_generated_file(item.target))

    generated: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            try:
                head = path.read_bytes()[:512]
            except OSError:
                continue
            if HEADER_PREFIX.encode("utf-8") in head:
                generated.append(path)
    generated = sorted(generated)
    if not generated:
        if errors:
            return errors
        return [f"{target}: no generated harness files found"]
    for path in generated:
        if path not in planned_targets:
            errors.extend(verify_generated_file(path))
    return errors
