#!/usr/bin/env python3
"""Workflow template models for Atlas agent-role runs."""

from __future__ import annotations

import json
import pathlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def now_rfc3339() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


@dataclass(frozen=True)
class TeamRole:
    id: str
    label: str
    agent_ref: str
    must_produce: list[str]
    skills: list[str] = field(default_factory=list)
    consumes: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TeamRole":
        return cls(
            id=str(payload["id"]),
            label=str(payload.get("label") or payload["id"]),
            agent_ref=str(payload.get("agent_ref") or payload.get("agent") or ""),
            must_produce=as_list(payload.get("must_produce") or payload.get("required_outputs")),
            skills=as_list(payload.get("skills")),
            consumes=as_list(payload.get("consumes")),
            acceptance_criteria=as_list(payload.get("acceptance_criteria")),
        )

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.id:
            errors.append("role id is required")
        if not self.agent_ref:
            errors.append(f"role {self.id} is missing agent_ref")
        if not self.must_produce:
            errors.append(f"role {self.id} must declare at least one output")
        if len(set(self.must_produce)) != len(self.must_produce):
            errors.append(f"role {self.id} has duplicate outputs")
        if self.id in self.consumes:
            errors.append(f"role {self.id} cannot consume itself")
        return errors


@dataclass(frozen=True)
class TeamTemplate:
    id: str
    name: str
    purpose: str
    workflow_kind: str
    roles: list[TeamRole]
    rollup: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TeamTemplate":
        roles = [TeamRole.from_dict(role) for role in payload.get("roles", [])]
        return cls(
            id=str(payload["id"]),
            name=str(payload.get("name") or payload["id"]),
            purpose=str(payload.get("purpose") or ""),
            workflow_kind=str(payload.get("workflow_kind") or payload.get("kind") or "generic"),
            roles=roles,
            rollup=dict(payload.get("rollup") or {}),
        )

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.id:
            errors.append("template id is required")
        if not self.roles:
            errors.append(f"template {self.id} must declare at least one role")
        seen: set[str] = set()
        produced_by: dict[str, str] = {}
        for role in self.roles:
            if role.id in seen:
                errors.append(f"duplicate role id: {role.id}")
            seen.add(role.id)
            errors.extend(role.validate())
            for output in role.must_produce:
                if output in produced_by:
                    errors.append(f"output {output} is produced by both {produced_by[output]} and {role.id}")
                produced_by[output] = role.id
        for role in self.roles:
            for dependency in role.consumes:
                if dependency not in seen:
                    errors.append(f"role {role.id} consumes unknown role {dependency}")
        errors.extend(self.dependency_cycle_errors(seen))
        errors.extend(self.rollup_coverage_errors())
        return errors

    def dependency_cycle_errors(self, known_roles: set[str] | None = None) -> list[str]:
        known = known_roles or {role.id for role in self.roles}
        dependencies = {
            role.id: [dependency for dependency in role.consumes if dependency in known]
            for role in self.roles
        }
        visiting: set[str] = set()
        visited: set[str] = set()
        stack: list[str] = []
        errors: list[str] = []

        def visit(role_id: str) -> None:
            if role_id in visited:
                return
            if role_id in visiting:
                start = stack.index(role_id) if role_id in stack else 0
                cycle = [*stack[start:], role_id]
                errors.append("role dependency cycle: " + " -> ".join(cycle))
                return
            visiting.add(role_id)
            stack.append(role_id)
            for dependency in dependencies.get(role_id, []):
                visit(dependency)
            stack.pop()
            visiting.remove(role_id)
            visited.add(role_id)

        for role_id in dependencies:
            visit(role_id)
        return errors

    def role_phases(self) -> list[list[str]]:
        roles_by_id = {role.id: role for role in self.roles}
        remaining = set(roles_by_id)
        completed: set[str] = set()
        phases: list[list[str]] = []
        while remaining:
            ready = [
                role.id
                for role in self.roles
                if role.id in remaining and set(role.consumes).issubset(completed)
            ]
            if not ready:
                blocked = ", ".join(sorted(remaining))
                raise ValueError(f"role dependency graph cannot be scheduled; blocked roles: {blocked}")
            phases.append(ready)
            completed.update(ready)
            remaining.difference_update(ready)
        return phases

    def rollup_required(self) -> bool:
        return bool(self.rollup.get("missing_outputs_block_completion") or self.rollup.get("require_coverage"))

    def rollup_coverage_errors(self) -> list[str]:
        if not self.rollup_required() or not self.roles:
            return []
        try:
            phases = self.role_phases()
        except ValueError as exc:
            return [str(exc)]
        final_phase = set(phases[-1])
        prior_roles = {role.id for role in self.roles if role.id not in final_phase}
        if not prior_roles:
            return ["rollup coverage requires at least one prior role before the final rollup phase"]
        rollup_roles = [
            role
            for role in self.roles
            if role.id in final_phase and prior_roles.issubset(set(role.consumes))
        ]
        if not rollup_roles:
            return [
                "rollup coverage requires a final-phase role that consumes all prior roles: "
                + ", ".join(sorted(prior_roles))
            ]
        return []

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AgentDefinition:
    id: str
    ref: str
    description: str = ""
    skills: list[str] = field(default_factory=list)
    source: str = ""
    execution_profile: str = ""

    @classmethod
    def from_dict(cls, agent_id: str, payload: dict[str, Any]) -> "AgentDefinition":
        return cls(
            id=str(payload.get("id") or agent_id),
            ref=str(payload.get("ref") or f"agent-registry://{payload.get('id') or agent_id}"),
            description=str(payload.get("description") or ""),
            skills=as_list(payload.get("skills")),
            source=str(payload.get("source") or ""),
            execution_profile=str(payload.get("execution_profile") or payload.get("profile") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AgentRegistry:
    agents: dict[str, AgentDefinition]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AgentRegistry":
        raw_agents = payload.get("agents") if isinstance(payload.get("agents"), (dict, list)) else payload
        agents: dict[str, AgentDefinition] = {}
        if isinstance(raw_agents, dict):
            for agent_id, value in raw_agents.items():
                if isinstance(value, dict):
                    definition = AgentDefinition.from_dict(str(agent_id), value)
                else:
                    definition = AgentDefinition(id=str(agent_id), ref=str(value))
                agents[definition.id] = definition
        elif isinstance(raw_agents, list):
            for value in raw_agents:
                if not isinstance(value, dict):
                    continue
                definition = AgentDefinition.from_dict(str(value.get("id") or value.get("ref") or ""), value)
                if definition.id:
                    agents[definition.id] = definition
        return cls(agents=agents)

    def resolve(self, ref: str) -> AgentDefinition | None:
        if ref.startswith("agent-registry://"):
            agent_id = ref.removeprefix("agent-registry://")
            return self.agents.get(agent_id)
        for definition in self.agents.values():
            if ref in {definition.ref, definition.source}:
                return definition
        return None

    def to_dict(self) -> dict[str, Any]:
        return {"agents": {agent_id: agent.to_dict() for agent_id, agent in sorted(self.agents.items())}}


def markdown_frontmatter(path: str | pathlib.Path) -> dict[str, str]:
    source = pathlib.Path(path)
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    if not lines or lines[0].strip() != "---":
        return {}
    values: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, separator, value = line.partition(":")
        if separator:
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def local_agent_definition(ref: str, agent_root: str | pathlib.Path | None) -> AgentDefinition | None:
    if agent_root is None:
        return None
    candidate = pathlib.Path(ref)
    if not candidate.is_absolute():
        candidate = pathlib.Path(agent_root) / ref
    if not candidate.exists() or not candidate.is_file():
        return None
    frontmatter = markdown_frontmatter(candidate)
    return AgentDefinition(
        id=frontmatter.get("name") or candidate.stem,
        ref=ref,
        description=frontmatter.get("description") or "",
        skills=as_list(frontmatter.get("skills")),
        source=str(candidate),
        execution_profile=frontmatter.get("execution_profile") or frontmatter.get("profile") or "",
    )


def resolve_role_agent(
    role: TeamRole,
    *,
    registry: AgentRegistry | None = None,
    agent_root: str | pathlib.Path | None = None,
) -> AgentDefinition | None:
    if registry is not None:
        resolved = registry.resolve(role.agent_ref)
        if resolved is not None:
            return resolved
    if role.agent_ref.endswith(".md") or "/" in role.agent_ref:
        return local_agent_definition(role.agent_ref, agent_root)
    return None


@dataclass(frozen=True)
class TeamRunRoleResult:
    role_id: str
    status: str
    outputs: dict[str, str]
    evidence: list[str] = field(default_factory=list)
    notes: str = ""
    contract_issues: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TeamRunRoleResult":
        return cls(
            role_id=str(payload["role_id"]),
            status=str(payload.get("status") or "pending"),
            outputs={str(key): str(value) for key, value in dict(payload.get("outputs") or {}).items()},
            evidence=as_list(payload.get("evidence")),
            notes=str(payload.get("notes") or ""),
            contract_issues=as_list(payload.get("contract_issues")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TeamRun:
    id: str
    template_id: str
    work_item_id: str
    status: str
    created_at: str
    role_results: dict[str, TeamRunRoleResult] = field(default_factory=dict)

    @classmethod
    def start(cls, *, run_id: str, template: TeamTemplate, work_item_id: str) -> "TeamRun":
        return cls(
            id=run_id,
            template_id=template.id,
            work_item_id=work_item_id,
            status="running",
            created_at=now_rfc3339(),
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TeamRun":
        results = {
            role_id: TeamRunRoleResult.from_dict(result)
            for role_id, result in dict(payload.get("role_results") or {}).items()
        }
        return cls(
            id=str(payload["id"]),
            template_id=str(payload["template_id"]),
            work_item_id=str(payload.get("work_item_id") or ""),
            status=str(payload.get("status") or "running"),
            created_at=str(payload.get("created_at") or now_rfc3339()),
            role_results=results,
        )

    def record_role_result(self, result: TeamRunRoleResult) -> None:
        self.role_results[result.role_id] = result

    def refresh_status(self, template: TeamTemplate) -> str:
        self.status = "complete" if not self.missing_outputs(template) else "running"
        return self.status

    def missing_outputs(self, template: TeamTemplate) -> dict[str, list[str]]:
        missing: dict[str, list[str]] = {}
        for role in template.roles:
            result = self.role_results.get(role.id)
            if result is None or result.status != "complete":
                missing[role.id] = list(role.must_produce)
                continue
            absent = [name for name in role.must_produce if not result.outputs.get(name)]
            if absent:
                missing[role.id] = absent
        return missing

    def rollup_markdown(self, template: TeamTemplate) -> str:
        missing = self.missing_outputs(template)
        roles_by_id = {role.id: role for role in template.roles}
        lines = [
            f"# {template.name} Evidence",
            "",
            f"- Template: `{template.id}`",
            f"- Run: `{self.id}`",
            f"- Work item: `{self.work_item_id}`",
            f"- Status: `{self.status}`",
            "",
            "## Role Outputs",
            "",
        ]
        for role in template.roles:
            result = self.role_results.get(role.id)
            lines.append(f"### {role.label}")
            lines.append("")
            lines.append(f"- Agent: `{role.agent_ref}`")
            if role.consumes:
                lines.append(f"- Consumes: {', '.join(role.consumes)}")
            dependency_blockers = role_dependency_blockers(role, self, roles_by_id)
            for blocker in dependency_blockers:
                lines.append(f"- Dependency blocker: {blocker}")
            if result is None:
                lines.append("- Status: `missing`")
            else:
                lines.append(f"- Status: `{result.status}`")
                for name in role.must_produce:
                    value = result.outputs.get(name, "")
                    lines.append(f"- {name}: {value or '`missing`'}")
                for evidence in result.evidence:
                    lines.append(f"- Evidence: {evidence}")
                for issue in result.contract_issues:
                    lines.append(f"- Contract issue: {issue}")
                if result.notes:
                    lines.extend(["", result.notes])
            lines.append("")
        lines.extend(["## Missing Outputs", ""])
        if not missing:
            lines.append("- none")
        else:
            for role_id, names in missing.items():
                lines.append(f"- `{role_id}`: {', '.join(names)}")
        return "\n".join(lines).rstrip() + "\n"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["role_results"] = {role_id: result.to_dict() for role_id, result in self.role_results.items()}
        return payload


def load_team_template(path: str | pathlib.Path) -> TeamTemplate:
    payload = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    template = TeamTemplate.from_dict(payload)
    errors = template.validate()
    if errors:
        raise ValueError("; ".join(errors))
    return template


def load_agent_registry(path: str | pathlib.Path) -> AgentRegistry:
    payload = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("agent registry must be a JSON object")
    return AgentRegistry.from_dict(payload)


def validate_template_agent_refs(
    template: TeamTemplate,
    *,
    registry: AgentRegistry | None = None,
    agent_root: str | pathlib.Path | None = None,
) -> list[str]:
    errors: list[str] = []
    root = pathlib.Path(agent_root) if agent_root else None
    for role in template.roles:
        ref = role.agent_ref
        if ref.startswith("agent-registry://"):
            resolved = registry.resolve(ref) if registry is not None else None
            if registry is not None and resolved is None:
                errors.append(f"role {role.id} references unknown registry agent {ref}")
            if resolved is not None and resolved.source and root is not None:
                source = pathlib.Path(resolved.source)
                if not source.is_absolute():
                    source = root / source
                if not source.exists():
                    errors.append(f"role {role.id} registry agent source is missing {resolved.source}")
            continue
        if ref.endswith(".md") or "/" in ref:
            if root is None:
                continue
            candidate = pathlib.Path(ref)
            if not candidate.is_absolute():
                candidate = root / ref
            if not candidate.exists():
                errors.append(f"role {role.id} references missing agent file {ref}")
            continue
        if registry is not None and registry.resolve(ref) is None:
            errors.append(f"role {role.id} references unknown agent {ref}")
    return errors


def load_team_run(path: str | pathlib.Path) -> TeamRun:
    payload = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    return TeamRun.from_dict(payload)


def save_team_run(path: str | pathlib.Path, run: TeamRun) -> None:
    pathlib.Path(path).write_text(json.dumps(run.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_team_rollup(path: str | pathlib.Path, run: TeamRun, template: TeamTemplate) -> None:
    pathlib.Path(path).write_text(run.rollup_markdown(template), encoding="utf-8")


def load_team_templates(path: str | pathlib.Path) -> list[TeamTemplate]:
    source = pathlib.Path(path)
    if source.is_file():
        return [load_team_template(source)]
    templates: list[TeamTemplate] = []
    for item in sorted(source.glob("*.json")):
        templates.append(load_team_template(item))
    return templates


def select_team_template(
    templates: list[TeamTemplate],
    *,
    workflow_kind: str,
    required_outputs: list[str] | None = None,
) -> TeamTemplate | None:
    required = set(required_outputs or [])
    candidates = [template for template in templates if template.workflow_kind == workflow_kind]
    if not required:
        return candidates[0] if candidates else None
    selectable = [
        template
        for template in candidates
        if required.issubset(set(template_output_names(template)))
    ]
    return best_template_match(selectable, required_outputs=required_outputs)


def template_output_names(template: TeamTemplate) -> list[str]:
    return sorted({output for role in template.roles for output in role.must_produce})


def template_selection_sort_key(template: TeamTemplate, required_outputs: list[str] | set[str] | None = None) -> tuple[int, int, str]:
    required = set(required_outputs or [])
    outputs = set(template_output_names(template))
    extra_outputs = len(outputs.difference(required)) if required else len(outputs)
    return (extra_outputs, len(template.roles), template.id)


def best_template_match(
    templates: list[TeamTemplate],
    *,
    required_outputs: list[str] | set[str] | None = None,
) -> TeamTemplate | None:
    if not templates:
        return None
    return sorted(templates, key=lambda template: template_selection_sort_key(template, required_outputs))[0]


def candidate_gap_sort_key(candidate: dict[str, Any]) -> tuple[int, int, int, str]:
    return (
        len(as_list(candidate.get("missing_required_outputs"))),
        int(candidate.get("extra_output_count") or 0),
        len(as_list(candidate.get("role_ids"))),
        str(candidate.get("id") or ""),
    )


def template_selection_status(
    *,
    selected: dict[str, Any] | None,
    candidates: list[dict[str, Any]],
    matching_candidates: list[dict[str, Any]],
    request: dict[str, Any],
) -> dict[str, Any]:
    required = set(as_list(request.get("required_outputs")))
    explicit_template = str(request.get("team_template") or "")
    workflow_kind = str(request.get("workflow_kind") or "")
    closest = sorted(matching_candidates, key=candidate_gap_sort_key)[0] if matching_candidates else None

    if selected:
        missing: list[str] = []
        covered = sorted(required)
        status = "use_existing_template"
        action = "use_existing_template"
        closest_id = selected.get("id")
    else:
        missing = as_list(closest.get("missing_required_outputs")) if closest else sorted(required)
        covered = sorted(required.difference(set(missing)))
        closest_id = closest.get("id") if closest else None
        if explicit_template and not any(candidate.get("id_matches") for candidate in candidates):
            status = "requested_template_not_found"
            action = "create_new_template"
        elif explicit_template:
            status = "requested_template_incomplete"
            action = "edit_requested_template_or_create_new"
        elif workflow_kind and not matching_candidates:
            status = "no_matching_workflow_kind"
            action = "create_new_template"
        elif matching_candidates:
            status = "no_covering_template"
            action = "edit_closest_template_or_create_new"
        else:
            status = "no_templates_available"
            action = "create_new_template"

    return {
        "status": status,
        "suggested_action": action,
        "closest_template": closest_id,
        "covered_required_outputs": covered,
        "uncovered_required_outputs": missing,
        "candidate_count": len(candidates),
        "matching_candidate_count": len(matching_candidates),
    }


def template_selection_report(
    templates: list[TeamTemplate],
    request: dict[str, Any],
) -> dict[str, Any]:
    workflow_kind = str(request.get("workflow_kind") or "")
    explicit_template = str(request.get("team_template") or "")
    required_outputs = as_list(request.get("required_outputs"))
    required = set(required_outputs)
    candidates: list[dict[str, Any]] = []
    for template in templates:
        outputs = template_output_names(template)
        missing = sorted(required.difference(outputs))
        kind_matches = not workflow_kind or template.workflow_kind == workflow_kind
        id_matches = not explicit_template or template.id == explicit_template
        sort_key = template_selection_sort_key(template, required)
        candidates.append(
            {
                "id": template.id,
                "name": template.name,
                "workflow_kind": template.workflow_kind,
                "role_ids": [role.id for role in template.roles],
                "role_phases": template.role_phases(),
                "outputs": outputs,
                "kind_matches": kind_matches,
                "id_matches": id_matches,
                "covers_required_outputs": not missing,
                "missing_required_outputs": missing,
                "selectable": kind_matches and id_matches and not missing,
                "extra_output_count": sort_key[0],
                "selection_rank": list(sort_key),
            }
        )
    selected_template = best_template_match(
        [template for template in templates if next(candidate for candidate in candidates if candidate["id"] == template.id)["selectable"]],
        required_outputs=required,
    )
    selected = next((candidate for candidate in candidates if selected_template and candidate["id"] == selected_template.id), None)
    matching_candidates = [candidate for candidate in candidates if candidate["kind_matches"] and candidate["id_matches"]]
    request_record = {
        "workflow_kind": workflow_kind,
        "team_template": explicit_template,
        "required_outputs": required_outputs,
    }
    return {
        "request": request_record,
        "selected_template": selected["id"] if selected else None,
        "selection": template_selection_status(
            selected=selected,
            candidates=candidates,
            matching_candidates=matching_candidates,
            request=request_record,
        ),
        "candidates": candidates,
    }


def compact_template_selection_report(report: dict[str, Any]) -> dict[str, Any]:
    required = set(as_list(report.get("request", {}).get("required_outputs")))
    return {
        "request": report.get("request", {}),
        "selected_template": report.get("selected_template"),
        "selection": report.get("selection", {}),
        "candidates": [
            {
                "id": candidate.get("id"),
                "workflow_kind": candidate.get("workflow_kind"),
                "selectable": bool(candidate.get("selectable")),
                "role_phases": candidate.get("role_phases") or [],
                "covered_required_outputs": sorted(
                    required.difference(set(as_list(candidate.get("missing_required_outputs"))))
                ),
                "missing_required_outputs": candidate.get("missing_required_outputs") or [],
            }
            for candidate in report.get("candidates", [])
        ],
    }


def work_item_workflow_request(work_item: dict[str, Any]) -> dict[str, Any]:
    scheduler = work_item.get("scheduler") if isinstance(work_item.get("scheduler"), dict) else {}
    metadata = work_item.get("metadata") if isinstance(work_item.get("metadata"), dict) else {}
    return {
        "workflow_kind": str(
            scheduler.get("workflow_kind") or metadata.get("workflow_kind") or work_item.get("workflow_kind") or ""
        ),
        "team_template": str(
            scheduler.get("team_template") or metadata.get("team_template") or work_item.get("team_template") or ""
        ),
        "required_outputs": as_list(
            scheduler.get("required_outputs") or metadata.get("required_outputs") or work_item.get("required_outputs")
        ),
    }


def select_team_template_for_work_item(
    templates: list[TeamTemplate],
    work_item: dict[str, Any],
) -> TeamTemplate | None:
    request = work_item_workflow_request(work_item)
    required = set(request["required_outputs"])
    explicit_template = request["team_template"]
    if explicit_template:
        for template in templates:
            if template.id != explicit_template:
                continue
            produced = {output for role in template.roles for output in role.must_produce}
            return template if required.issubset(produced) else None
        return None
    workflow_kind = request["workflow_kind"]
    if not workflow_kind:
        return None
    return select_team_template(templates, workflow_kind=workflow_kind, required_outputs=request["required_outputs"])


def load_role_results(path: str | pathlib.Path) -> list[TeamRunRoleResult]:
    source = pathlib.Path(path)
    if not source.exists():
        return []
    payload = json.loads(source.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "role_results" in payload:
        raw_results = payload["role_results"]
    else:
        raw_results = payload
    if isinstance(raw_results, dict):
        return [
            TeamRunRoleResult.from_dict({"role_id": role_id, **result})
            for role_id, result in raw_results.items()
            if isinstance(result, dict)
        ]
    if isinstance(raw_results, list):
        return [TeamRunRoleResult.from_dict(result) for result in raw_results if isinstance(result, dict)]
    raise ValueError("role results must be a list or role_results object")


def role_required_missing(role: TeamRole, result: TeamRunRoleResult) -> list[str]:
    return [name for name in role.must_produce if not result.outputs.get(name)]


def role_result_satisfies_outputs(role: TeamRole, result: TeamRunRoleResult | None) -> bool:
    return result is not None and result.status == "complete" and not role_required_missing(role, result)


GENERATED_CONTRACT_ISSUE_PREFIXES = (
    "missing required output(s):",
    "dependency not complete:",
    "unexpected output(s):",
    "unknown status:",
)


def generated_contract_issue(issue: str) -> bool:
    return any(issue.startswith(prefix) for prefix in GENERATED_CONTRACT_ISSUE_PREFIXES)


def role_result_contract_issues(
    role: TeamRole,
    result: TeamRunRoleResult,
    *,
    roles_by_id: dict[str, TeamRole] | None = None,
    results_by_role: dict[str, TeamRunRoleResult] | None = None,
) -> list[str]:
    issues: list[str] = []
    required = set(role.must_produce)
    missing = role_required_missing(role, result)
    unexpected = sorted(set(result.outputs).difference(required))
    if result.status == "complete" and missing:
        issues.append("missing required output(s): " + ", ".join(missing))
    if result.status == "complete" and role.consumes:
        role_lookup = roles_by_id or {}
        result_lookup = results_by_role or {}
        incomplete_dependencies = [
            dependency
            for dependency in role.consumes
            if not role_result_satisfies_outputs(role_lookup.get(dependency, TeamRole(dependency, dependency, "", [])), result_lookup.get(dependency))
        ]
        if incomplete_dependencies:
            issues.append("dependency not complete: " + ", ".join(incomplete_dependencies))
    if unexpected:
        issues.append("unexpected output(s): " + ", ".join(unexpected))
    if result.status not in {"complete", "failed", "blocked", "pending", "running", "incomplete", "dry-run"}:
        issues.append(f"unknown status: {result.status}")
    return issues


def normalize_role_result(
    role: TeamRole,
    result: TeamRunRoleResult,
    *,
    roles_by_id: dict[str, TeamRole] | None = None,
    results_by_role: dict[str, TeamRunRoleResult] | None = None,
) -> TeamRunRoleResult:
    issues = [
        *[issue for issue in result.contract_issues if not generated_contract_issue(issue)],
        *role_result_contract_issues(
            role,
            result,
            roles_by_id=roles_by_id,
            results_by_role=results_by_role,
        ),
    ]
    status = result.status
    if status == "complete" and any(
        issue.startswith("missing required output") or issue.startswith("dependency not complete")
        for issue in issues
    ):
        status = "incomplete"
    if (
        status == "incomplete"
        and any(generated_contract_issue(issue) for issue in result.contract_issues)
        and not issues
        and not role_required_missing(role, result)
    ):
        status = "complete"
    if status not in {"complete", "failed", "blocked", "pending", "running", "incomplete", "dry-run"}:
        status = "incomplete"
    return TeamRunRoleResult(
        role_id=result.role_id,
        status=status,
        outputs=dict(result.outputs),
        evidence=list(result.evidence),
        notes=result.notes,
        contract_issues=list(dict.fromkeys(issues)),
    )


def role_dependency_blockers(role: TeamRole, run: TeamRun, roles_by_id: dict[str, TeamRole]) -> list[str]:
    blockers: list[str] = []
    for dependency in role.consumes:
        dependency_role = roles_by_id.get(dependency)
        dependency_result = run.role_results.get(dependency)
        if dependency_role is None:
            blockers.append(f"unknown dependency: {dependency}")
        elif not role_result_satisfies_outputs(dependency_role, dependency_result):
            blockers.append(f"dependency not complete: {dependency}")
    return blockers


def apply_role_results(
    *,
    template: TeamTemplate,
    run: TeamRun,
    results: list[TeamRunRoleResult],
) -> TeamRun:
    roles_by_id = {role.id: role for role in template.roles}
    staged_results = dict(run.role_results)
    for result in results:
        if result.role_id not in roles_by_id:
            raise ValueError(f"role result references unknown role {result.role_id}")
        staged_results[result.role_id] = result
    for phase in template.role_phases():
        for role_id in phase:
            result = staged_results.get(role_id)
            if result is None:
                continue
            role = roles_by_id[role_id]
            normalized = normalize_role_result(
                role,
                result,
                roles_by_id=roles_by_id,
                results_by_role=staged_results,
            )
            staged_results[role_id] = normalized
            run.record_role_result(normalized)
    run.refresh_status(template)
    return run


def role_task_packets(
    template: TeamTemplate,
    run: TeamRun,
    *,
    registry: AgentRegistry | None = None,
    agent_root: str | pathlib.Path | None = None,
) -> list[dict[str, Any]]:
    missing = run.missing_outputs(template)
    roles_by_id = {role.id: role for role in template.roles}
    phase_by_role = {
        role_id: index
        for index, phase in enumerate(template.role_phases())
        for role_id in phase
    }
    packets: list[dict[str, Any]] = []
    for role in template.roles:
        result = run.role_results.get(role.id)
        agent_definition = resolve_role_agent(role, registry=registry, agent_root=agent_root)
        consumed = {
            dependency: run.role_results[dependency].to_dict()
            for dependency in role.consumes
            if dependency in run.role_results
        }
        packets.append(
            {
                "run_id": run.id,
                "template_id": template.id,
                "work_item_id": run.work_item_id,
                "role_id": role.id,
                "label": role.label,
                "phase_index": phase_by_role.get(role.id, 0),
                "agent_ref": role.agent_ref,
                "skills": role.skills,
                "consumes": role.consumes,
                "must_produce": role.must_produce,
                "missing_outputs": missing.get(role.id, []),
                "status": result.status if result else "pending",
                "contract_issues": result.contract_issues if result else [],
                "dependency_blockers": role_dependency_blockers(role, run, roles_by_id),
                "acceptance_criteria": role.acceptance_criteria,
                "consumed_role_results": consumed,
                "agent_definition": agent_definition.to_dict() if agent_definition else None,
            }
        )
    return packets


def team_run_summary(template: TeamTemplate, run: TeamRun) -> dict[str, Any]:
    return {
        "run_id": run.id,
        "template_id": template.id,
        "workflow_kind": template.workflow_kind,
        "work_item_id": run.work_item_id,
        "status": run.status,
        "role_phases": template.role_phases(),
        "missing_outputs": run.missing_outputs(template),
        "roles": [
            {
                "role_id": role.id,
                "status": run.role_results[role.id].status if role.id in run.role_results else "pending",
                "required_outputs": role.must_produce,
                "completed_outputs": sorted(run.role_results[role.id].outputs) if role.id in run.role_results else [],
                "contract_issues": run.role_results[role.id].contract_issues if role.id in run.role_results else [],
                "dependency_blockers": role_dependency_blockers(role, run, {item.id: item for item in template.roles}),
            }
            for role in template.roles
        ],
    }


def write_role_task_packets(
    path: str | pathlib.Path,
    template: TeamTemplate,
    run: TeamRun,
    *,
    registry: AgentRegistry | None = None,
    agent_root: str | pathlib.Path | None = None,
) -> None:
    pathlib.Path(path).write_text(
        json.dumps(
            {"tasks": role_task_packets(template, run, registry=registry, agent_root=agent_root)},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
