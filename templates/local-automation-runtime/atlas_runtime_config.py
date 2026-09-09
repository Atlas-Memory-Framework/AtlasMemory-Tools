"""Non-secret provider configuration and deterministic Codex command boundaries.

Loading configuration is read-only. Capabilities describe available operations;
they never replace the operation-specific authorization packet.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import pwd
import re
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit


ROLES = ("planning", "implementation", "review", "repair")
CAPABILITIES = frozenset({"read", "local_execute", "draft_pr", "board_write", "assess"})
PROVIDERS = frozenset({"azure-devops", "github"})
REASONING = frozenset({"minimal", "low", "medium", "high", "xhigh", "max", "ultra"})
MODEL_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}\Z")


class RuntimeConfigError(ValueError):
    """Configuration is missing, ambiguous, or outside the permitted boundary."""


def normalize_provider(value: Any) -> str:
    if value == "azure_devops":
        value = "azure-devops"
    if not isinstance(value, str) or value not in PROVIDERS:
        raise RuntimeConfigError("provider must explicitly be azure-devops or github")
    return value


def _within(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def validate_input_path(raw: str | Path) -> Path:
    """Validate an owned non-secret input before a caller reads its contents."""
    source = Path(raw).absolute()
    identity_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    allowed_roots = (identity_home, Path("/tmp"))
    if ".." in source.parts or not any(_within(source, root) for root in allowed_roots):
        raise RuntimeConfigError("input must be inside the current identity home or its temporary work area")
    try:
        source = source.resolve(strict=True)
        if not any(_within(source, root.resolve()) for root in allowed_roots):
            raise RuntimeConfigError("input resolves outside the current identity work area")
        if not source.is_file() or source.stat().st_uid != os.getuid():
            raise RuntimeConfigError("input must be a regular file owned by the current identity")
    except (OSError, RuntimeError) as exc:
        raise RuntimeConfigError("non-secret input is unavailable") from exc
    return source


def validate_runtime_path(
    raw: str | Path | None, *, home: str | Path | None = None, uid: int | None = None
) -> Path:
    """Resolve an existing owned directory inside the current passwd identity.

    HOME is deliberately ignored. The optional home/uid arguments allow isolated
    fixture tests; production callers must use the current identity defaults.
    This function creates no directories and reads no configuration or secrets.
    """
    identity_uid = os.getuid() if uid is None else uid
    identity_home = Path(pwd.getpwuid(identity_uid).pw_dir if home is None else home).resolve(strict=True)
    if raw is None or not str(raw).strip():
        raise RuntimeConfigError("an explicit existing runtime directory is required")
    supplied = str(raw)
    if supplied == "~" or supplied.startswith("~/"):
        supplied = str(identity_home) + supplied[1:]
    elif supplied.startswith("~"):
        raise RuntimeConfigError("runtime directory must belong to the current identity")
    path = Path(supplied)
    if not path.is_absolute() or ".." in path.parts:
        raise RuntimeConfigError("runtime directory must be an absolute path without parent traversal")
    if not _within(path, identity_home) or path == identity_home:
        raise RuntimeConfigError("runtime directory must be inside the current passwd home")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise RuntimeConfigError("runtime directory must already exist") from exc
    if not _within(resolved, identity_home) or resolved == identity_home:
        raise RuntimeConfigError("runtime directory resolves outside the current identity")
    if not resolved.is_dir():
        raise RuntimeConfigError("runtime path is not a directory")
    for component in (resolved, *resolved.parents):
        if not _within(component, identity_home):
            break
        if component.stat().st_uid != identity_uid:
            raise RuntimeConfigError("runtime directory and its home ancestors must be owned by the current identity")
    return resolved


@dataclass(frozen=True)
class RoleSettings:
    model: str
    reasoning: str
    source: str

    @property
    def argv(self) -> list[str]:
        return [
            "codex", "exec", "--ignore-user-config", "--sandbox", "workspace-write",
            "-c", 'approval_policy="on-request"', "-m", self.model,
            "-c", f'model_reasoning_effort="{self.reasoning}"',
            "-c", "sandbox_workspace_write.network_access=false",
            "-c", "sandbox_workspace_write.writable_roots=[]",
            "-c", "sandbox_workspace_write.exclude_tmpdir_env_var=true",
            "-c", "sandbox_workspace_write.exclude_slash_tmp=true", "--ephemeral", "--json",
        ]

    def report(self) -> dict[str, Any]:
        return {"model": self.model, "reasoning": self.reasoning, "source": self.source, "argv": self.argv}


@dataclass(frozen=True)
class RuntimeConfig:
    provider: str
    runtime_dir: Path | None
    repository: dict[str, str]
    capabilities: frozenset[str]
    roles: dict[str, RoleSettings]
    source: str
    sandbox: str = "workspace-write"
    approval_policy: str = "on-request"
    routing: dict[str, Any] | None = None

    def report(self) -> dict[str, Any]:
        report = {
            "provider": self.provider,
            "runtime_dir": str(self.runtime_dir) if self.runtime_dir else None,
            "repository": dict(self.repository),
            "capabilities": sorted(self.capabilities),
            "models": {role: self.roles[role].report() for role in ROLES},
            "sandbox": self.sandbox,
            "approval_policy": self.approval_policy,
            "authority": "operation-specific authorization is required separately",
        }
        if self.routing is not None:
            from atlas_authority import canonical_digest
            report["routing"] = {"provenance_sha256": canonical_digest(self.routing),
                                 "decision_sha256": self.routing.get("decision", {}).get("decision_sha256"),
                                 "policy_sha256": canonical_digest(self.routing.get("policy")),
                                 "intake_sha256": canonical_digest(self.routing.get("intake"))}
        return report


def resolve_role_settings(config: RuntimeConfig | Mapping[str, Any], *, source: str = "config") -> dict[str, RoleSettings]:
    if isinstance(config, RuntimeConfig):
        return dict(config.roles)
    models = config.get("models")
    if not isinstance(models, dict) or set(models) - {*ROLES, "default"}:
        raise RuntimeConfigError("models must explicitly configure planning, implementation, review and repair")
    resolved: dict[str, RoleSettings] = {}
    for role in ROLES:
        key = role if role in models else "default"
        entry = models.get(key)
        if not isinstance(entry, dict) or set(entry) != {"model", "reasoning"}:
            raise RuntimeConfigError(f"models.{role} requires explicit model and reasoning; command overrides are forbidden")
        model, reasoning = entry.get("model"), entry.get("reasoning")
        if not isinstance(model, str) or not MODEL_PATTERN.fullmatch(model):
            raise RuntimeConfigError(f"models.{role}.model is invalid")
        if not isinstance(reasoning, str) or reasoning not in REASONING:
            raise RuntimeConfigError(f"models.{role}.reasoning is invalid")
        resolved[role] = RoleSettings(model=model, reasoning=reasoning, source=f"{source}:models.{key}")
    return resolved


def _repository_config(provider: str, raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict) or not raw:
        raise RuntimeConfigError("repository must be explicitly configured")
    allowed = {"organization", "project", "name", "url", "base_branch", "checkout"}
    if set(raw) - allowed or any(not isinstance(v, str) or not v.strip() for v in raw.values()):
        raise RuntimeConfigError("repository has unsupported or empty fields")
    repository = dict(raw)
    url = repository.get("url", "")
    parts = urlsplit(url)
    if parts.username or parts.password or parts.query or parts.fragment:
        raise RuntimeConfigError("repository URL must contain no credentials, query or fragment")
    if provider == "azure-devops":
        required = {"organization", "project", "name", "url", "base_branch"}
        if not required.issubset(repository):
            raise RuntimeConfigError("Azure repository requires organization, project, name, url and base_branch")
        if parts.scheme != "https" or parts.netloc.lower() != "dev.azure.com":
            raise RuntimeConfigError("Azure provider requires an explicit https://dev.azure.com repository URL")
        expected = [repository["organization"], repository["project"], "_git", repository["name"]]
        if [unquote(p) for p in parts.path.strip("/").split("/")] != expected:
            raise RuntimeConfigError("Azure repository URL does not match configured organization/project/name")
    elif url:
        if parts.scheme != "https" or parts.netloc.lower() != "github.com":
            raise RuntimeConfigError("GitHub provider cannot operate on an Azure or unknown repository URL")
        if len(parts.path.strip("/").split("/")) != 2:
            raise RuntimeConfigError("GitHub repository URL requires an owner and repository")
    base = repository.get("base_branch", "")
    if base and (base.startswith("-") or any(c.isspace() for c in base) or ".." in base):
        raise RuntimeConfigError("base_branch must be an explicit safe branch name")
    return repository


def load_runtime_config(
    path: str | Path, *, runtime_dir: str | Path | None = None, require_runtime: bool = True
) -> RuntimeConfig:
    source = validate_input_path(path)
    try:
        def object_pairs(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise RuntimeConfigError("duplicate configuration JSON keys are forbidden")
                result[key] = value
            return result
        def invalid_constant(value):
            raise RuntimeConfigError("nonfinite configuration values are forbidden")
        if source.stat().st_size > 262_144:
            raise RuntimeConfigError("configuration exceeds the bounded input limit")
        raw = json.loads(source.read_text(encoding="utf-8"), object_pairs_hook=object_pairs, parse_constant=invalid_constant)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeConfigError("cannot read the non-secret runtime JSON configuration") from exc
    if not isinstance(raw, dict):
        raise RuntimeConfigError("runtime configuration must be a JSON object")
    allowed = {"schema_version", "provider", "runtime_dir", "repository", "capabilities", "models", "sandbox", "approval_policy"}
    if set(raw) - allowed:
        raise RuntimeConfigError("runtime configuration contains unsupported fields; arbitrary command/config overrides are forbidden")
    if type(raw.get("schema_version")) is not int or raw["schema_version"] != 1:
        raise RuntimeConfigError("runtime configuration requires schema_version 1")
    provider = normalize_provider(raw.get("provider"))
    capabilities = raw.get("capabilities")
    if not isinstance(capabilities, list) or any(not isinstance(v, str) for v in capabilities):
        raise RuntimeConfigError("capabilities must be an explicit list")
    if set(capabilities) - CAPABILITIES or len(capabilities) != len(set(capabilities)):
        raise RuntimeConfigError("unknown or duplicate runtime capability")
    if raw.get("sandbox") != "workspace-write" or raw.get("approval_policy") != "on-request":
        raise RuntimeConfigError("workspace-write sandbox and on-request approvals must be explicit")
    location = runtime_dir if runtime_dir is not None else raw.get("runtime_dir")
    root = validate_runtime_path(location) if location is not None or require_runtime else None
    return RuntimeConfig(
        provider=provider, runtime_dir=root, repository=_repository_config(provider, raw.get("repository")),
        capabilities=frozenset(capabilities), roles=resolve_role_settings(raw, source=str(source)), source=str(source),
    )


def require_capability(config: RuntimeConfig, capability: str) -> None:
    if capability not in CAPABILITIES or capability not in config.capabilities:
        raise RuntimeConfigError(f"runtime capability is not enabled: {capability}")


def build_codex_command(config: RuntimeConfig, role: str, workspace: str | Path) -> list[str]:
    if config.provider != "azure-devops":
        raise RuntimeConfigError("the bounded Azure worker requires provider azure-devops")
    if config.runtime_dir is None:
        raise RuntimeConfigError("the bounded worker requires an explicit runtime directory")
    validate_runtime_path(config.runtime_dir)
    if config.sandbox != "workspace-write" or config.approval_policy != "on-request":
        raise RuntimeConfigError("unsafe Codex sandbox or approval policy")
    if role not in ROLES:
        raise RuntimeConfigError("unknown Codex role")
    workspace_path = validate_runtime_path(workspace)
    settings = config.roles.get(role)
    if not isinstance(settings, RoleSettings):
        raise RuntimeConfigError("missing effective role settings")
    # Revalidate manually constructed configuration objects as well as JSON input.
    resolve_role_settings({"models": {"default": {"model": settings.model, "reasoning": settings.reasoning}}})
    return [*settings.argv, "-C", str(workspace_path)]


def _validated_route(provenance: dict[str, Any], *, now: float | None = None) -> dict[str, Any]:
    """Recompute routing; model recommendations never become policy by assertion."""
    from atlas_authority import canonical_digest
    from atlas_routing import decide_route
    required = {"intake", "policy", "assessment", "challenge", "decision", "human_receipts"}
    if not isinstance(provenance, dict) or set(provenance) != required:
        raise RuntimeConfigError("routed configuration requires exact immutable routing provenance")
    if not isinstance(provenance["human_receipts"], list):
        raise RuntimeConfigError("routed human receipts must be a separate bound list")
    decision = decide_route(provenance["intake"], provenance["policy"], provenance["assessment"],
                            provenance["challenge"], now=now)
    if canonical_digest(decision) != canonical_digest(provenance["decision"]):
        raise RuntimeConfigError("routing decision is stale or differs from deterministic policy")
    if decision.get("route_ready") is not True:
        raise RuntimeConfigError("routing prerequisites are incomplete")
    if set(decision.get("models", {})) != set(ROLES):
        raise RuntimeConfigError("route does not select all four bounded worker roles")
    return decision


def resolve_routed_config(config: RuntimeConfig, provenance: dict[str, Any], *, now: float | None = None) -> RuntimeConfig:
    """Return an explicit role override without modifying the source configuration.

    This performs no authorization, authentication, state writes or subprocesses.
    The worker must independently verify signed authority and human receipts.
    """
    from atlas_authority import canonical_digest
    decision = _validated_route(provenance, now=now)
    if config.provider != "azure-devops" or config.routing is not None:
        raise RuntimeConfigError("routing must start from an explicit unrouted Azure configuration")
    if provenance["policy"].get("repository_url") != config.repository.get("url"):
        raise RuntimeConfigError("routing policy targets a different repository")
    source = "routing:" + canonical_digest(provenance["policy"]) + ":" + str(decision.get("profile"))
    roles = resolve_role_settings({"models": decision["models"]}, source=source)
    # A defensive JSON copy prevents later caller mutations of a frozen dataclass.
    copied = json.loads(json.dumps(provenance, allow_nan=False))
    return replace(config, roles=roles, routing=copied)


def verify_routed_config(config: RuntimeConfig, packet: dict[str, Any], *, now: float | None = None) -> dict[str, Any]:
    """Recheck a composed object at the actual worker authority boundary."""
    if config.routing is None:
        return {}
    from atlas_authority import canonical_digest
    decision = _validated_route(config.routing, now=now)
    if canonical_digest(config.routing["intake"].get("worker_packet")) != canonical_digest(packet):
        raise RuntimeConfigError("routed worker packet changed")
    base = replace(config, routing=None)
    resolved = resolve_routed_config(base, config.routing, now=now)
    if canonical_digest(resolved.report()) != canonical_digest(config.report()):
        raise RuntimeConfigError("effective models do not match the recomputed routing decision")
    return {"routing_decision_sha256": decision["decision_sha256"],
            "intake_sha256": canonical_digest(config.routing["intake"]),
            "policy_sha256": canonical_digest(config.routing["policy"])}
