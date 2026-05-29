from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).with_name("plan_to_issues.py")


def load_plan_to_issues_module():
    module_name = "plan_to_issues_under_test"
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def run_cli(*args: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_dry_run_collects_bullet_workstreams_and_project_url(tmp_path: Path) -> None:
    plan_path = tmp_path / "ws1_example.plan.md"
    plan_path.write_text(
        """---
name: ws1 workflow control plane
overview: "Shared workflow control plane rollout."
---

# WS1 Shared Workflow Control Plane Migration Plan

## Implementation Plan

### File Deltas (exhaustive) + rationale

- [core/contracts/foo.yaml](core/contracts/foo.yaml) - create/modify - Contracts - schema changes
- [core/local/runtime.py](core/local/runtime.py) - modify - Local Runtime - runtime changes
- [functions/function_app.py](functions/function_app.py) - modify - Azure Parity - hosted changes
- [infra/modules/gateway.bicep](infra/modules/gateway.bicep) - modify - Azure Parity - gateway changes

### Workstreams + merge points

- WS1A: Shared contracts and codegen foundation
  - Owner: Contracts
  - Depends on: WS0 contract freeze from SSOT
  - Review gates: `G-SCHEMA-VALIDATE`, `G-CODEGEN`
  - Merge point: `WS1-MP1`
- WS1B: Local workflow control-plane runtime and persistence
  - Owner: Local Runtime
  - Review gates: `G-LOCAL-WORKFLOW-RELIABILITY`
- WS1D: Azure parity and hosted rollout
  - Owner: Azure Parity
  - Depends on: `WS1-MP2`
  - Review gates: `G-DEPLOYED-WORKFLOW-AUTH-PARITY`, `G-DEPLOYED-WORKFLOW-PARITY`
  - Merge point: `WS1-MP4`

#### 4) Assumptions -> tests

- A1: The new workflow API can coexist with a short compatibility window without semantic drift.
- A2: Local and Azure can share the same workflow contract without forking DTOs.
- A3: Retrieval citations can stay separate from workflow evidence without blocking drafting later.

#### 5) Ranked risks

- R3 (Medium): Azure parity slips behind local delivery.

### Test plan (CI vs deployed)

- Deployed runner inputs:
- `HOSTED_BASE_URL` - required for both deployed parity gates; points at the configured hosted API deployment.
  - `E2E_API_KEY` - required for both deployed parity gates; exercises the canonical API-key auth path.

## Review Readiness

- GitHub issue conversion rule: materialize `A1`, `A2`, `A3`, and `R3` as explicit blocking issues or epic acceptance criteria; do not treat them as already-proven just because plan reviews passed.
- Deterministic hosted smoke for WS1 should be led by `summary.v1`; deployed drafting closeout for `case_summary_draft.v1` is still tracked under `G-MVP-DEPLOYED-DRAFTING-PARITY`, but that gate is required for overall MVP completion on Azure.
""",
        encoding="utf-8",
    )

    payload = run_cli(
        "--plan",
        str(plan_path),
        "--repo",
        "owner/repo",
        "--strategy",
        "workstreams",
        "--project-url",
        "https://github.com/orgs/OWNER/projects/2",
        "--dry-run",
    )

    assert payload["repo"] == "owner/repo"
    assert payload["project"]["owner"] == "OWNER"
    assert payload["project"]["number"] == 2
    assert [child["source_id"] for child in payload["children"]] == ["WS1A", "WS1B", "WS1D"]
    assert payload["children"][0]["title"] == "[WS1A] Shared contracts and codegen foundation"
    assert "G-SCHEMA-VALIDATE" in payload["children"][0]["body"]
    assert payload["children"][0]["suggested_points"] == 8
    assert payload["children"][0]["dependencies"] == ["WS0"]
    assert payload["children"][0]["merge_points"] == ["WS1-MP1"]
    assert payload["children"][0]["repo_targets"] == ["OWNER/core"]
    assert any(label == "repo:core" for label in payload["children"][0]["labels"])
    assert "workstream:ws1-a" in payload["children"][0]["labels"]
    assert payload["children"][2]["repo_targets"] == [
        "OWNER/service",
        "OWNER/infra",
    ]
    assert "workstream:ws1-d" in payload["children"][2]["labels"]
    assert payload["children"][2]["highest_tier"] == "T5"
    assert "A2: Local and Azure can share the same workflow contract without forking DTOs." in payload["children"][2]["blockers"]
    assert "HOSTED_BASE_URL" in "\n".join(payload["children"][2]["validation_requirements"])
    assert payload["stability"]["needs_user_input"] == []
    assert payload["stability"]["plan_status"] == "multi-repo-preview"
    assert payload["stability"]["multi_repo_projection"] is True
    assert payload["stability"]["dispatch_blocked"] is False
    assert len(payload["stability"]["distinct_child_repo_slugs"]) > 1
    assert any("multiple distinct GitHub repos" in c for c in payload["stability"]["caveats"])
    assert "R3" in payload["stability"]["explicit_blockers"]


def test_project_url_conflict_is_rejected(tmp_path: Path) -> None:
    plan_path = tmp_path / "ws1_example.plan.md"
    plan_path.write_text(
        """---
name: ws1 workflow control plane
---

# WS1 Shared Workflow Control Plane Migration Plan
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--plan",
            str(plan_path),
            "--repo",
            "owner/repo",
            "--project-owner",
            "SomeoneElse",
            "--project-url",
            "https://github.com/orgs/OWNER/projects/2",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "Project owner mismatch" in result.stderr


def test_project_field_values_populate_execution_board_metadata() -> None:
    mod = load_plan_to_issues_module()
    draft = mod.IssueDraft(
        title="[LEAF-001] Add sync",
        body="body",
        labels=["type:story", "status:ready", "repo:service", "tier:t2"],
        kind="story",
        source_id="LEAF-001",
        execution_repo="OWNER/service",
        base_branch="main",
        suggested_points=1,
        dependencies=["LEAF-000", "OWNER/service#42"],
        gates=["G-SYNC"],
        highest_tier="T2",
        repo_targets=["OWNER/service"],
        status_label="status:ready",
        dispatch_recommendation="auto-dispatch",
        dispatch_mode="agent-ready",
        agent_type="generalPurpose",
        write_scope=["skills/plan-to-issues/scripts/plan_to_issues.py"],
        validation_commands=["python3 -m pytest"],
        validation_scope="local",
        risk_tags=["cross-repo"],
    )

    values = mod.project_field_values(
        draft,
        issue_repo="OWNER/service",
        plan_key="PLAN-1",
        parent_epic_url="https://github.com/OWNER/service/issues/1",
    )

    assert values["Status"] == "Todo"
    assert values["ItemType"] == "Story"
    assert values["PlanKey"] == "PLAN-1"
    assert values["ParentEpic"] == "https://github.com/OWNER/service/issues/1"
    assert values["DispatchMode"] == "agent-ready"
    assert values["DispatchRecommendation"] == "auto-dispatch"
    assert values["AgentType"] == "generalPurpose"
    assert values["IssueReady"] == "Ready"
    assert values["AutomationState"] == "Ready"
    assert values["Size"] == 1
    assert values["OnePRContract"] == "Yes"
    assert values["Validation"] == "python3 -m pytest"


def test_project_field_values_do_not_mark_oversized_auto_dispatch_ready() -> None:
    mod = load_plan_to_issues_module()
    draft = mod.IssueDraft(
        title="[LEAF-002] Broad sync",
        body="body",
        labels=["type:story", "status:ready", "repo:service", "points:5"],
        kind="story",
        source_id="LEAF-002",
        execution_repo="OWNER/service",
        suggested_points=5,
        repo_targets=["OWNER/service"],
        status_label="status:ready",
        dispatch_recommendation="auto-dispatch",
        dispatch_mode="agent-ready",
    )

    values = mod.project_field_values(draft, issue_repo="OWNER/service", plan_key="PLAN-1")

    assert values["AutomationState"] == "Manual"
    assert values["OnePRContract"] == "No"


def test_project_field_values_omit_unknown_agent_type() -> None:
    mod = load_plan_to_issues_module()
    draft = mod.IssueDraft(
        title="[LEAF-003] Unknown agent",
        body="body",
        labels=["type:story", "status:ready"],
        kind="story",
        source_id="LEAF-003",
        status_label="status:ready",
        dispatch_recommendation="auto-dispatch",
        dispatch_mode="agent-ready",
        agent_type="backend-engineer",
        suggested_points=1,
    )

    values = mod.project_field_values(draft, issue_repo="OWNER/service", plan_key="PLAN-1")

    assert "AgentType" not in values


def test_project_field_sync_uses_project_item_edit_for_supported_fields() -> None:
    mod = load_plan_to_issues_module()
    draft = mod.IssueDraft(
        title="[WS1] Story",
        body="body",
        labels=["type:story", "status:ready"],
        kind="story",
        source_id="WS1",
        status_label="status:ready",
        dispatch_recommendation="auto-dispatch",
        dispatch_mode="agent-ready",
        suggested_points=1,
    )
    fields = {
        "Status": {
            "id": "status-field",
            "name": "Status",
            "options": [{"name": "Todo", "id": "todo-option"}],
        },
        "ItemType": {
            "id": "item-type-field",
            "name": "ItemType",
            "options": [{"name": "Story", "id": "story-option"}],
        },
        "Size": {"id": "size-field", "name": "Size"},
        "SourceId": {"id": "source-field", "name": "SourceId"},
    }
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_: object) -> object:
        calls.append(cmd)
        return object()

    with (
        patch.object(mod, "gh_project_config", return_value={"project_id": "project-id", "fields": fields}),
        patch.object(mod, "gh_project_item_id_record_map", return_value={}),
        patch.object(mod.subprocess, "run", side_effect=fake_run),
    ):
        mod.gh_project_sync_issue_fields(
            "OWNER",
            2,
            "item-id",
            draft,
            issue_repo="OWNER/service",
            plan_key="PLAN-1",
        )

    assert any("--single-select-option-id" in call and "todo-option" in call for call in calls)
    assert any("--single-select-option-id" in call and "story-option" in call for call in calls)
    assert any("--number" in call and "1.0" in call for call in calls)
    assert any("--text" in call and "WS1" in call for call in calls)


def test_project_field_sync_skips_matching_project_item_values() -> None:
    mod = load_plan_to_issues_module()
    draft = mod.IssueDraft(
        title="[WS1] Story",
        body="body",
        labels=["type:story", "status:ready"],
        kind="story",
        source_id="WS1",
        status_label="status:ready",
        dispatch_recommendation="auto-dispatch",
        dispatch_mode="agent-ready",
        suggested_points=1,
    )
    fields = {
        "Status": {
            "id": "status-field",
            "name": "Status",
            "options": [{"name": "Todo", "id": "todo-option"}],
        },
        "ItemType": {
            "id": "item-type-field",
            "name": "ItemType",
            "options": [{"name": "Story", "id": "story-option"}],
        },
        "Size": {"id": "size-field", "name": "Size"},
        "SourceId": {"id": "source-field", "name": "SourceId"},
    }
    current_item = {
        "status": "Todo",
        "itemType": "Story",
        "size": 1,
        "sourceId": "WS1",
    }
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_: object) -> object:
        calls.append(cmd)
        return object()

    with (
        patch.object(mod, "gh_project_config", return_value={"project_id": "project-id", "fields": fields}),
        patch.object(mod, "gh_project_item_id_record_map", return_value={"item-id": current_item}),
        patch.object(mod.subprocess, "run", side_effect=fake_run),
    ):
        mod.gh_project_sync_issue_fields(
            "OWNER",
            2,
            "item-id",
            draft,
            issue_repo="OWNER/service",
            plan_key="PLAN-1",
        )

    assert calls == []


def test_frontmatter_supports_multiline_overview_summary_alias_and_nested_tracking(tmp_path: Path) -> None:
    plan_path = tmp_path / "instablinds.plan.md"
    plan_path.write_text(
        """---
name: instablinds rollout
overview: |
  Installable blinds checkout automation.
  Keep hosting undecided.
tracking:
  epicRepo: owner/instablinds
  baseBranch: feature/plan-source
---

# Instablinds Automation

## Implementation Plan

### Workstreams + merge points
- WS1A: One-point setup
  - Points: 1
  - Issue ready: true
  - Target repo: owner/instablinds
""",
        encoding="utf-8",
    )

    payload = run_cli("--plan", str(plan_path), "--strategy", "workstreams", "--dry-run")

    assert payload["repo"] == "owner/instablinds"
    assert "Installable blinds checkout automation." in payload["epic"]["body"]
    assert "Keep hosting undecided." in payload["epic"]["body"]
    assert payload["children"][0]["base_branch"] == "feature/plan-source"
    assert payload["children"][0]["suggested_points"] == 1
    assert "points:1" in payload["children"][0]["labels"]


def test_summary_frontmatter_alias_populates_epic_summary(tmp_path: Path) -> None:
    plan_path = tmp_path / "summary_alias.plan.md"
    plan_path.write_text(
        """---
name: summary alias
summary: 'Use summary when overview is absent.'
---

# Summary Alias
""",
        encoding="utf-8",
    )

    payload = run_cli("--plan", str(plan_path), "--repo", "owner/repo", "--dry-run")

    assert "Use summary when overview is absent." in payload["epic"]["body"]
    assert "No overview found in frontmatter." not in payload["epic"]["body"]


def test_long_plan_key_generates_github_safe_epic_workstream_label(tmp_path: Path) -> None:
    plan_path = tmp_path / "atlas_memory_core_operations_mvp_launch_readiness_and_runtime_control.plan.md"
    plan_path.write_text(
        """---
name: atlas memory core operations mvp launch readiness and runtime control
overview: "Long plan names should not break label preflight."
---

# Atlas Memory Core Operations MVP Launch Readiness And Runtime Control

## Implementation Plan

### Workstreams + merge points
- WS1A: One point
  - Points: 1
  - Issue ready: true
  - Target repo: owner/repo
""",
        encoding="utf-8",
    )

    payload = run_cli(
        "--plan",
        str(plan_path),
        "--repo",
        "owner/repo",
        "--strategy",
        "workstreams",
        "--dry-run",
    )

    workstream_labels = [
        label for label in payload["epic"]["labels"] if label.startswith("workstream:")
    ]
    assert len(workstream_labels) == 1
    assert len(workstream_labels[0]) <= 50
    assert payload["preflight"]["invalid_labels"] == []
    assert payload["preflight"]["ok"] is True


def test_projection_workstream_label_alias_overrides_epic_label_scope(tmp_path: Path) -> None:
    plan_path = tmp_path / "long_name.plan.md"
    plan_path.write_text(
        """---
name: atlas memory core operations mvp launch readiness and runtime control
ProjectionWorkstreamLabel: atlas-core-ops-mvp
overview: "Plans may choose a stable short projection label."
---

# Atlas Memory Core Operations MVP Launch Readiness And Runtime Control
""",
        encoding="utf-8",
    )

    payload = run_cli("--plan", str(plan_path), "--repo", "owner/repo", "--dry-run")

    assert "workstream:atlas-core-ops-mvp" in payload["epic"]["labels"]
    assert payload["preflight"]["invalid_labels"] == []


def test_canonical_plan_url_uses_current_source_branch(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "git@github.com:owner/instablinds.git"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(["git", "checkout", "-b", "issue/instablinds-plan"], cwd=tmp_path, check=True, capture_output=True, text=True)
    plan_path = tmp_path / "docs" / "instablinds.plan.md"
    plan_path.parent.mkdir()
    plan_path.write_text(
        """---
name: instablinds
overview: Plan URL should use issue branch.
---

# Instablinds
""",
        encoding="utf-8",
    )

    payload = run_cli("--plan", str(plan_path), "--repo", "owner/instablinds", "--dry-run")

    assert "https://github.com/owner/instablinds/blob/issue/instablinds-plan/docs/instablinds.plan.md" in payload["epic"]["body"]
    assert "/blob/main/docs/instablinds.plan.md" not in payload["epic"]["body"]


def test_ws2_gates_and_validation_do_not_use_ws1_deployed_heuristics(tmp_path: Path) -> None:
    plan_path = tmp_path / "ws2_example.plan.md"
    plan_path.write_text(
        """---
name: WS2 retrieval trust
overview: "Benchmark-backed retrieval validation."
---

# WS2 Retrieval Trust

## Implementation Plan

### Workstreams + merge points

- `WS2-A`: Fixture pack
  - Owner: test-owner
  - Depends on: none
  - Review gates: `G-WS2-FixtureCatalog`, `G-WS2-TruthSet`
- `WS2-D`: Scope fixes
  - Owner: retrieval-runtime-owner
  - Depends on: `WS2-A`
  - Review gates: `G-WS2-ScopeIsolation`
- `WS2-E`: Provenance
  - Owner: contracts-owner
  - Review gates: `G-WS2-Linkage`
- `WS2-F`: Route parity
  - Owner: platform-test-owner
  - Depends on: `WS2-A`, `WS1B` / `WS1-MP2`
  - Review gates: `G-WS2-RouteParity`, `G-DEPLOYED-WORKFLOW-PARITY`
- `WS2-G`: Workflow doc gate (title mentions workflow; still not WS2-F)
  - Owner: ws2-orchestrator
  - Review gates: `G-WS2-Docs-Ready`

### Test plan (CI vs deployed)

- Deployed runner inputs:
  - `HOSTED_BASE_URL` - should not be injected into WS2-D/E by mistake.
""",
        encoding="utf-8",
    )

    payload = run_cli(
        "--plan",
        str(plan_path),
        "--repo",
        "owner/repo",
        "--strategy",
        "workstreams",
        "--dry-run",
    )

    by_id = {c["source_id"]: c for c in payload["children"]}
    assert by_id["WS2-A"]["gates"] == ["G-WS2-FIXTURECATALOG", "G-WS2-TRUTHSET"]
    assert by_id["WS2-D"]["gates"] == ["G-WS2-SCOPEISOLATION"]
    assert by_id["WS2-E"]["gates"] == ["G-WS2-LINKAGE"]
    assert by_id["WS2-F"]["gates"] == ["G-WS2-ROUTEPARITY", "G-DEPLOYED-WORKFLOW-PARITY"]
    assert "workstream:ws2-a" in by_id["WS2-A"]["labels"]
    assert "workstream:ws2-g" in by_id["WS2-G"]["labels"]

    assert "G-DEPLOYED-WORKFLOW" not in "\n".join(by_id["WS2-D"]["validation_requirements"])
    assert "HOSTED_BASE_URL" not in "\n".join(by_id["WS2-D"]["validation_requirements"])
    assert by_id["WS2-E"]["blockers"] == []
    assert "WS1B" in by_id["WS2-F"]["dependencies"]
    assert "WS1-MP2" in by_id["WS2-F"]["dependencies"]

    f_req = "\n".join(by_id["WS2-F"]["validation_requirements"])
    assert "G-WS2-RouteParity" in f_req
    assert "G-SEC-APIM-BACKEND-PARITY" in f_req
    g_req = "\n".join(by_id["WS2-G"]["validation_requirements"])
    assert "G-WS2-RouteParity" not in g_req
    assert "ws2_ci" in g_req

    epic = payload["epic"]
    assert "DR-003" in "\n".join(epic["validation_requirements"])
    assert "phase35-search-io" in "\n".join(epic["validation_requirements"])


def test_ws3_plan_prefers_bullets_and_filters_arrow_headings(tmp_path: Path) -> None:
    """Regression: `### WS2 -> WS3 -> WS4` must not shadow `### Workstreams + merge points` bullets."""
    plan_path = tmp_path / "ws3_example.plan.md"
    plan_path.write_text(
        """---
name: ws3 drafting workflow
overview: "Drafting workflow MVP."
---

# WS3 Drafting Workflow Plan

## Technical Plan

### WS2 -> WS3 -> WS4 Status Mapping

- `WS1` persists lifecycle.
- `WS3` records bundle metadata.

## Implementation Plan

### Workstreams + merge points

- WS3-A: Drafting contract freeze
  - Owner: Contracts
  - Depends on: `WS1A`, `WS2-E`
  - Review gates: `G-WS3-SCHEMA`
  - Merge point: `WS3-MP1`
- WS3-B: Local runtime
  - Owner: Workflow Runtime
  - Depends on: `WS3-MP1`
  - Review gates: `G-WS3-LOCAL-DRAFTING`
  - Merge point: `WS3-MP2`

### Test plan (CI vs deployed)

- Deployed runner inputs:
  - `HOSTED_BASE_URL` - not required for WS3 local closure.
""",
        encoding="utf-8",
    )

    payload = run_cli(
        "--plan",
        str(plan_path),
        "--repo",
        "OWNER/core",
        "--strategy",
        "workstreams",
        "--dry-run",
    )

    assert [c["source_id"] for c in payload["children"]] == ["WS3-A", "WS3-B"]
    epic = payload["epic"]
    joined = "\n".join(epic["validation_requirements"])
    assert "G-DEPLOYED-WORKFLOW" not in joined
    assert "WS3-MP3" in joined or "G-MVP-DEPLOYED-DRAFTING-PARITY" in joined
    assert "tier:" not in " ".join(epic["labels"])
    assert "Deployed / Manual Validation Requirements" in epic["body"]
    assert epic["execution_repo"] == "OWNER/core"
    assert epic["base_branch"] is None
    child_joined = "\n".join(payload["children"][0]["validation_requirements"])
    assert "G-WS3-SCHEMA" not in child_joined  # gates are separate; validation is the WS3 child blurb
    assert "G-DEPLOYED-WORKFLOW" not in child_joined


def test_infer_labels_can_override_workstream_scope_without_changing_plan_stem() -> None:
    mod = load_plan_to_issues_module()
    labels = mod.infer_labels(
        "WS2-A Fixture pack",
        "Workflow control plane docs",
        "story",
        "WS2",
        workstream_label_scope="WS2-A",
        repo_targets=["OWNER/core"],
        status_label="status:ready",
    )

    assert "workstream:ws2-a" in labels
    assert "area:workflow-control-plane" in labels


def test_ws4_nested_review_gates_and_no_assumption_dump_as_epic_blockers(tmp_path: Path) -> None:
    plan_path = tmp_path / "ws4_example.plan.md"
    plan_path.write_text(
        """---
name: WS4 workflow surfaces
overview: "Admin-first workflow operator surfaces."
---

# WS4 Workflow Surfaces Plan

## Risks / Assumptions / Tests

- A1: operator_summary is sufficient for MVP views.
- R1: workflows.py could drift.

## Problem Definition

- Deployed drafting parity is a named Azure MVP closeout track under `G-MVP-DEPLOYED-DRAFTING-PARITY`.

## Implementation Plan

### Workstreams + merge points

- WS4-A: Backend operator contract freeze
  - Owner: Workflow API / Local Runtime
  - Depends on: WS1 route inventory
  - Review gates (named):
    - `G-WS4-Contract`
    - `G-WS4-Docs`
  - Merge point: `WS4-MP1`
- WS4-B: Admin operator UI
  - Owner: Admin UI
  - Depends on: `WS4-MP1`
  - Review gates (named):
    - `G-WS4-UI-CONTRACT`
    - `G-ADMIN-UI-BUILD`
  - Merge point: `WS4-MP2`

### Test plan (CI vs deployed)

- Deployed runner inputs:
  - `HOSTED_BASE_URL` - used only when verifying hosted paths.
""",
        encoding="utf-8",
    )

    payload = run_cli(
        "--plan",
        str(plan_path),
        "--repo",
        "OWNER/admin-ui",
        "--strategy",
        "workstreams",
        "--dry-run",
    )

    epic = payload["epic"]
    assert "## Explicit Blockers" not in epic["body"]
    assert payload["stability"]["explicit_blockers"] == {}
    joined_epic = "\n".join(epic["validation_requirements"])
    assert "G-MVP-DEPLOYED-DRAFTING-PARITY" in joined_epic
    assert "PARITY-1" in joined_epic
    assert "G-DEPLOYED-WORKFLOW-AUTH-PARITY" not in joined_epic
    assert "Deployed / Manual Validation Requirements" in epic["body"]
    assert epic["execution_repo"] == "OWNER/admin-ui"
    assert epic["base_branch"] is None

    by_id = {c["source_id"]: c for c in payload["children"]}
    assert by_id["WS4-A"]["gates"] == ["G-WS4-CONTRACT", "G-WS4-DOCS"]
    assert set(by_id["WS4-B"]["gates"]) == {"G-ADMIN-UI-BUILD", "G-WS4-UI-CONTRACT"}
    assert "## Deployed / Manual Validation Requirements" in by_id["WS4-A"]["body"]
    child_a_req = "\n".join(by_id["WS4-A"]["validation_requirements"])
    assert "local/ci-first" in child_a_req.lower()
    assert "HOSTED_BASE_URL" not in child_a_req
    assert "Azure closeout only: true" not in child_a_req


def test_tracking_base_branch_and_story_override_are_emitted(tmp_path: Path) -> None:
    plan_path = tmp_path / "ws1_branching.plan.md"
    plan_path.write_text(
        """---
name: ws1 workflow control plane
tracking:
  baseBranch: release/main
---

# WS1 Shared Workflow Control Plane Migration Plan

## Implementation Plan

### Workstreams + merge points

- WS1A: Core implementation
  - Target repo: core
- WS1B: Azure follow-up
  - Target repo: service
  - Base branch: release/hotfix-control-plane
""",
        encoding="utf-8",
    )

    core_payload = run_cli(
        "--plan",
        str(plan_path),
        "--repo",
        "OWNER/core",
        "--strategy",
        "workstreams",
        "--dry-run",
    )
    root_payload = run_cli(
        "--plan",
        str(plan_path),
        "--repo",
        "OWNER/service",
        "--strategy",
        "workstreams",
        "--dry-run",
    )

    epic = core_payload["epic"]
    core_children = {c["source_id"]: c for c in core_payload["children"]}
    root_children = {c["source_id"]: c for c in root_payload["children"]}

    assert epic["base_branch"] == "release/main"
    assert "Base branch: `release/main`" in epic["body"]
    assert list(core_children) == ["WS1A", "WS1B"]
    assert list(root_children) == ["WS1A", "WS1B"]
    assert core_children["WS1A"]["execution_repo"] == "OWNER/core"
    assert core_children["WS1A"]["base_branch"] == "release/main"
    assert core_children["WS1B"]["execution_repo"] == "OWNER/service"
    assert core_children["WS1B"]["base_branch"] == "release/hotfix-control-plane"
    assert root_children["WS1A"]["execution_repo"] == "OWNER/core"
    assert root_children["WS1A"]["base_branch"] == "release/main"
    assert root_children["WS1B"]["execution_repo"] == "OWNER/service"
    assert root_children["WS1B"]["base_branch"] == "release/hotfix-control-plane"
    assert "fallback-to-`main`" in core_children["WS1A"]["body"]


def test_plan_state_base_branch_is_used_when_tracking_branch_is_missing(tmp_path: Path) -> None:
    plan_path = tmp_path / "lane_with_plan_state_base_branch.plan.md"
    plan_path.write_text(
        """---
tracking:
  provider: github
  project: ""
  epic: ""
  mode: draft
---

# Feature: Ingestion lane

## Plan State
BaseBranch: main

## Implementation Plan

### Workstreams + merge points
- WS1: parser stress
  - Review gates (named):
    - G-ISSUE-Dry-Run
  - Owns files:
    - `plans/example.plan.md`
""",
        encoding="utf-8",
    )

    payload = run_cli(
        "--plan",
        str(plan_path),
        "--repo",
        "OWNER/service",
        "--strategy",
        "workstreams",
        "--dry-run",
    )

    epic = payload["epic"]
    child = payload["children"][0]

    assert epic["base_branch"] == "main"
    assert child["base_branch"] == "main"
    assert "Base branch: `main`" in epic["body"]
    assert "Base branch: `main`" in child["body"]


def test_dry_run_without_repo_reports_needed_metadata(tmp_path: Path) -> None:
    plan_path = tmp_path / "ws_meta.plan.md"
    plan_path.write_text(
        """---
name: WS9 metadata test
overview: "Metadata-only readiness."
---

# WS9 Metadata Test

## Implementation Plan

### Workstreams + merge points

- WS9-A: Draft-only follow-up
  - Issue ready: false
  - Azure closeout only: true
  - Target repo: core, admin-ui
  - Blocked by: `WS1A`, `WS1-MP1`, `G-MVP-DEPLOYED-DRAFTING-PARITY`
  - Review gates: `G-MVP-DEPLOYED-DRAFTING-PARITY`
""",
        encoding="utf-8",
    )

    payload = run_cli(
        "--plan",
        str(plan_path),
        "--strategy",
        "workstreams",
        "--dry-run",
    )

    assert payload["repo"] is None
    assert payload["stability"]["plan_status"] == "needs-user-input"
    assert payload["stability"]["needs_user_input"] == ["tracking.epicRepo"]
    child = payload["children"][0]
    assert child["title"] == "[WS9-A] Draft-only follow-up"
    assert child["repo_targets"] == [
        "OWNER/core",
        "OWNER/admin-ui",
    ]
    assert child["execution_repo"] is None
    assert child["blockers"] == ["WS1A", "WS1-MP1", "G-MVP-DEPLOYED-DRAFTING-PARITY"]
    assert child["status_label"] == "status:draft"


def test_dependency_issue_refs_are_canonicalized_and_emitted_in_linked_refs_section(tmp_path: Path) -> None:
    plan_path = tmp_path / "linked_refs.plan.md"
    plan_path.write_text(
        """---
tracking:
  provider: github
  project: ""
  epic: ""
  mode: draft
---

# Feature: Linked refs

## Implementation Plan

### Workstreams + merge points
- WS1: Explicit upstream refs
  - Target repo: core
  - Depends on:
    - https://github.com/OWNER/core/issues/51
    - OWNER/core#52
  - Blocked by: OWNER/core#53
""",
        encoding="utf-8",
    )

    payload = run_cli(
        "--plan",
        str(plan_path),
        "--repo",
        "OWNER/core",
        "--strategy",
        "workstreams",
        "--dry-run",
    )

    child = payload["children"][0]
    assert child["dependencies"] == [
        "OWNER/core#51",
        "OWNER/core#52",
    ]
    assert child["dependency_issue_refs"] == [
        "OWNER/core#51",
        "OWNER/core#52",
    ]
    assert child["blocker_issue_refs"] == ["OWNER/core#53"]
    assert "## Linked Issue Refs" in child["body"]
    assert "  - OWNER/core#51" in child["body"]
    assert "  - OWNER/core#53" in child["body"]


def test_merge_point_dependencies_force_tracking_only_dispatch_and_guardrails(tmp_path: Path) -> None:
    plan_path = tmp_path / "merge_guardrail.plan.md"
    plan_path.write_text(
        """---
tracking:
  provider: github
  project: ""
  epic: ""
  mode: draft
---

# Feature: Merge point dependency

## Implementation Plan

### Workstreams + merge points
- WS1: Auto-dispatch candidate with unsupported dependency token
  - Target repo: core
  - Points: 1
  - Depends on: `WS1-MP2`
""",
        encoding="utf-8",
    )

    payload = run_cli(
        "--plan",
        str(plan_path),
        "--repo",
        "OWNER/core",
        "--strategy",
        "workstreams",
        "--dry-run",
    )

    child = payload["children"][0]
    assert child["dispatch_recommendation"] == "tracking-only"
    assert child["automation_blockers"] == [
        "Convert dependency token `WS1-MP2` into an explicit issue ref or runnable workstream before auto-dispatch."
    ]
    assert "## Dispatch Guardrails" in child["body"]
    assert "Convert dependency token `WS1-MP2`" in child["body"]


def test_agent_ready_manifest_leaf_over_one_point_is_tracking_only(tmp_path: Path) -> None:
    plan_path = tmp_path / "automation_manifest_oversized.plan.md"
    plan_path.write_text(
        """---
tracking:
  epicRepo: OWNER/service
---

# Feature: Oversized manifest lane

## Implementation Plan

## Automation Issue Manifest
### Leaf issues
- LEAF-020: Oversized agent-ready leaf
  - Dispatch: agent-ready
  - Points: 5
  - Target repo: service
  - Depends on: none
  - Files in scope:
    - `src/app.ts`
  - Validation:
    - `npm test`
""",
        encoding="utf-8",
    )

    payload = run_cli(
        "--plan",
        str(plan_path),
        "--repo",
        "OWNER/service",
        "--strategy",
        "leaf-issues",
        "--dry-run",
    )

    child = payload["children"][0]
    assert child["dispatch_mode"] == "tracking-only"
    assert child["dispatch_recommendation"] == "tracking-only"
    assert child["status_label"] == "status:draft"
    assert child["suggested_points"] == 5
    assert child["automation_blockers"] == [
        "Decompose `points:5` issue into one-point child issues before local automation dispatch."
    ]
    assert "agent:decomposed" in child["labels"]
    assert "decomposition:required" in child["labels"]
    assert "priority:p2" in child["labels"]
    assert "Issue ready: `false`" in child["body"]
    assert "Requested dispatch mode: `agent-ready`" in child["body"]
    assert "Dispatch mode: `tracking-only`" in child["body"]
    assert "## Dispatch Guardrails" in child["body"]
    assert payload["preflight"]["ok"] is True


def test_dry_run_preflight_reports_duplicate_source_ids(tmp_path: Path) -> None:
    plan_path = tmp_path / "duplicate_source_ids.plan.md"
    plan_path.write_text(
        """---
tracking:
  epicRepo: OWNER/service
---

# Feature: Duplicate source ids

## Automation Issue Manifest
### Leaf issues
- LEAF-001: First projected row
  - Dispatch: manual-review
  - Points: 1
  - Target repo: service
  - Depends on: none
- LEAF-001: Second projected row
  - Dispatch: manual-review
  - Points: 1
  - Target repo: service
  - Depends on: none
""",
        encoding="utf-8",
    )

    payload = run_cli(
        "--plan",
        str(plan_path),
        "--repo",
        "OWNER/service",
        "--strategy",
        "leaf-issues",
        "--dry-run",
    )

    assert payload["preflight"]["ok"] is False
    assert payload["preflight"]["duplicate_source_ids"] == [
        {
            "source_id": "LEAF-001",
            "titles": ["[LEAF-001] First projected row", "[LEAF-001] Second projected row"],
        }
    ]
    assert any("Duplicate SourceId" in error for error in payload["preflight"]["errors"])


def test_projection_preflight_reports_invalid_label_length() -> None:
    mod = load_plan_to_issues_module()
    draft = mod.IssueDraft(
        title="[WS1] Long label",
        body="body",
        labels=["type:story", "owner:" + "x" * 60],
        kind="story",
        source_id="WS1",
        priority="P2",
    )

    preflight = mod.projection_preflight_report([draft])

    assert preflight["ok"] is False
    assert preflight["invalid_labels"] == [
        {
            "source_id": "WS1",
            "label": "owner:" + "x" * 60,
            "length": 66,
            "max_length": 50,
        }
    ]
    assert "GitHub label names must be <= 50 characters" in preflight["errors"][0]


def test_priority_inference_keeps_p0_explicit_only_and_maps_gate_tiers() -> None:
    mod = load_plan_to_issues_module()

    assert (
        mod.infer_priority_value(
            explicit_priority="P0",
            title="Routine work",
            excerpt="",
            highest_tier="T4",
            risk_tags=[],
            blockers=[],
            automation_blockers=[],
            validation_scope="local",
            gates=[],
        )
        == "P0"
    )
    assert (
        mod.infer_priority_value(
            explicit_priority=None,
            title="Critical blocker fix",
            excerpt="",
            highest_tier=None,
            risk_tags=[],
            blockers=[],
            automation_blockers=[],
            validation_scope="local",
            gates=[],
        )
        == "P1"
    )
    assert (
        mod.infer_priority_value(
            explicit_priority=None,
            title="T0 lane",
            excerpt="",
            highest_tier="T0",
            risk_tags=[],
            blockers=[],
            automation_blockers=[],
            validation_scope="local",
            gates=[],
        )
        == "P1"
    )
    assert (
        mod.infer_priority_value(
            explicit_priority=None,
            title="T2 lane",
            excerpt="",
            highest_tier="T2",
            risk_tags=[],
            blockers=[],
            automation_blockers=[],
            validation_scope="local",
            gates=[],
        )
        == "P2"
    )
    assert (
        mod.infer_priority_value(
            explicit_priority=None,
            title="T5 lane",
            excerpt="",
            highest_tier="T5",
            risk_tags=[],
            blockers=[],
            automation_blockers=[],
            validation_scope="local",
            gates=[],
        )
        == "P3"
    )


def test_dry_run_uses_repo_relative_plan_path_for_git_checkout(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    plan_path = tmp_path / "plans" / "ws1_example.plan.md"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text(
        """---
name: ws1 workflow control plane
tracking:
  epicRepo: owner/repo
---

# WS1 Shared Workflow Control Plane Migration Plan

## Implementation Plan

### Workstreams + merge points

- WS1A: Shared contracts
  - Issue ready: true
  - Target repo: core
""",
        encoding="utf-8",
    )

    payload = run_cli(
        "--plan",
        str(plan_path.resolve()),
        "--strategy",
        "workstreams",
        "--dry-run",
    )

    assert payload["plan"] == "plans/ws1_example.plan.md"
    assert "`/plans/" not in payload["epic"]["body"]
    assert "`/plans/" not in payload["children"][0]["body"]
    assert "plans/ws1_example.plan.md" in payload["epic"]["body"]
    assert "plans/ws1_example.plan.md" in payload["children"][0]["body"]


def test_non_ws_lane_dry_run_does_not_inherit_workflow_parity_defaults(tmp_path: Path) -> None:
    plan_path = tmp_path / "non_ws_lane.plan.md"
    plan_path.write_text(
        """---
tracking:
  provider: github
  project: ""
  epic: ""
  mode: draft
---

# Feature: Admin control-plane backend lane

## Implementation Plan

### File Deltas (exhaustive) + rationale
- `plans/backend-ui-support_8e30ccc5.plan.md` - create - planning orchestrator - wrapper plan

### Workstreams + merge points
- WS1: Bootstrap and assurance semantics
  - Agent type: generalPurpose
  - Delegate: optional
  - Review gates (named):
    - G-ISSUE-Dry-Run
  - Owns files:
    - `docs/ADMIN_UI_API_SURFACES.md`
""",
        encoding="utf-8",
    )

    payload = run_cli(
        "--plan",
        str(plan_path),
        "--repo",
        "owner/repo",
        "--strategy",
        "workstreams",
        "--dry-run",
    )

    epic = payload["epic"]
    child = payload["children"][0]

    assert epic["source_id"] == "NON-WS-LANE"
    assert epic["title"].startswith("[Epic][NON-WS-LANE]")
    assert "area:workflow-control-plane" not in epic["labels"]
    assert "area:portfolio" in epic["labels"]
    assert epic["validation_requirements"] == []

    child_req = "\n".join(child["validation_requirements"])
    assert "WS-specific hosted workflow parity" in child_req
    assert "G-DEPLOYED-WORKFLOW-AUTH-PARITY" not in child_req
    assert "area:workflow-control-plane" not in child["labels"]
    assert child["repo_targets"] == ["OWNER/service"]
    assert "repo:service" in child["labels"]


def test_lane_dry_run_supports_ws_p_and_repo_specific_projection(tmp_path: Path) -> None:
    plan_path = tmp_path / "lane.plan.md"
    plan_path.write_text(
        """---
tracking:
  provider: github
  project: ""
  epic: ""
  mode: draft
---

# Feature: API SSOT, codegen, auth, SDK, and security lane

## Implementation Plan

### Workstreams + merge points
- WS-P: prerequisite cluster for core framework auth additions
  - Target repo: core
  - Depends on: none
  - Review gates (named):
    - G-ISSUE-Dry-Run
  - Merge point / integration step:
    - MP-P: prerequisite cluster approved
- WS1: Epic A for API SSOT, gateway/runtime alignment, codegen, and SDK parity
  - Target repo: root, core, infra
  - Depends on:
    - WS-P for any child issue that consumes core auth prerequisites
  - Review gates (named):
    - G-ISSUE-Dry-Run
  - Merge point / integration step:
    - MP-A: Epic A issue cluster approved
- WS2: Epic B for security, compliance, and admin identity hardening
  - Target repo: root, infra
  - Depends on:
    - WS-P
    - WS1 only for child issues that explicitly depend on APIM/Functions route alignment
  - Review gates (named):
    - G-ISSUE-Dry-Run
  - Merge point / integration step:
    - MP-B: Epic B issue cluster approved
""",
        encoding="utf-8",
    )

    root_payload = run_cli(
        "--plan",
        str(plan_path),
        "--repo",
        "OWNER/service",
        "--strategy",
        "workstreams",
        "--dry-run",
    )
    core_payload = run_cli(
        "--plan",
        str(plan_path),
        "--repo",
        "OWNER/core",
        "--strategy",
        "workstreams",
        "--dry-run",
    )
    infra_payload = run_cli(
        "--plan",
        str(plan_path),
        "--repo",
        "OWNER/infra",
        "--strategy",
        "workstreams",
        "--dry-run",
    )

    root_children = {child["source_id"]: child for child in root_payload["children"]}
    core_children = {child["source_id"]: child for child in core_payload["children"]}
    infra_children = {child["source_id"]: child for child in infra_payload["children"]}

    assert list(root_children) == ["WS-P", "WS1", "WS2"]
    assert root_children["WS-P"]["repo_targets"] == ["OWNER/core"]
    assert root_children["WS-P"]["execution_repo"] == "OWNER/core"
    assert root_children["WS-P"]["merge_points"] == ["MP-P"]
    assert root_children["WS1"]["repo_targets"] == [
        "OWNER/service",
        "OWNER/core",
        "OWNER/infra",
    ]
    assert root_children["WS1"]["dependencies"] == ["WS-P"]
    assert root_children["WS1"]["merge_points"] == ["MP-A"]
    assert root_children["WS1"]["execution_repo"] == "OWNER/service"
    assert "repo:cross-repo" in root_children["WS1"]["labels"]
    assert root_children["WS2"]["dependencies"] == ["WS-P", "WS1"]
    assert root_children["WS2"]["repo_targets"] == [
        "OWNER/service",
        "OWNER/infra",
    ]
    assert "repo:cross-repo" in root_children["WS2"]["labels"]

    assert list(core_children) == ["WS-P", "WS1", "WS2"]
    assert core_children["WS-P"]["repo_targets"] == ["OWNER/core"]
    assert core_children["WS-P"]["merge_points"] == ["MP-P"]
    assert core_children["WS1"]["repo_targets"] == [
        "OWNER/service",
        "OWNER/core",
        "OWNER/infra",
    ]
    assert core_children["WS1"]["execution_repo"] == "OWNER/core"
    assert "repo:cross-repo" in core_children["WS1"]["labels"]
    assert core_children["WS2"]["repo_targets"] == [
        "OWNER/service",
        "OWNER/infra",
    ]
    assert core_children["WS2"]["execution_repo"] == "OWNER/service"

    assert list(infra_children) == ["WS-P", "WS1", "WS2"]
    assert infra_children["WS-P"]["repo_targets"] == ["OWNER/core"]
    assert infra_children["WS-P"]["execution_repo"] == "OWNER/core"
    assert infra_children["WS1"]["repo_targets"] == [
        "OWNER/service",
        "OWNER/core",
        "OWNER/infra",
    ]
    assert infra_children["WS2"]["repo_targets"] == [
        "OWNER/service",
        "OWNER/infra",
    ]
    assert infra_children["WS2"]["merge_points"] == ["MP-B"]
    assert infra_children["WS2"]["execution_repo"] == "OWNER/infra"
    assert "repo:cross-repo" in infra_children["WS1"]["labels"]


def test_dispatch_metadata_blocks_apply_when_plan_state_defers_issue_materialization(tmp_path: Path) -> None:
    plan_path = tmp_path / "dispatch_blocked.plan.md"
    plan_path.write_text(
        """---
tracking:
  provider: github
  project: ""
  epic: ""
  mode: draft
---

# Feature: Auth hardening lane

## Plan State
Status: Approved
CurrentStage: Reviews
NextRequiredUserAction: do not start issue materialization until `G-SEC-WORKFLOW-AUTH-CONTRACT` is green.
BlockingDecision: G-SEC-WORKFLOW-AUTH-CONTRACT
UnresolvedBlockers: 1

## Implementation Plan

### Workstreams + merge points
- WS1: Auth and APIM hardening
  - Target repo: service
  - Issue ready: true
  - Review gates (named):
    - G-SEC-WORKFLOW-AUTH-CONTRACT
    - G-SEC-APIM-POLICY-CONTRACT

### Test plan (CI vs deployed)
- Deployed runner inputs:
  - `HOSTED_BASE_URL` - required for hosted parity.
  - `E2E_API_KEY` - required for shared-dev verification.
""",
        encoding="utf-8",
    )

    payload = run_cli(
        "--plan",
        str(plan_path),
        "--repo",
        "OWNER/service",
        "--strategy",
        "workstreams",
        "--dry-run",
    )

    plan_execution = payload["plan_execution"]
    child = payload["children"][0]

    assert plan_execution["dispatch_blocked"] is True
    assert plan_execution["recommended_dispatch_mode"] == "tracking-only"
    assert child["dispatch_recommendation"] == "tracking-only"
    assert child["validation_scope"] == "deployed"
    assert "needs-deployed-validation" in child["risk_tags"]
    assert "auth" in child["risk_tags"]
    assert "## Dispatch Guardrails" in child["body"]
    assert payload["stability"]["plan_status"] == "dispatch-blocked"
    assert payload["stability"]["dispatch_blocked"] is True
    assert any("blocks issue dispatch" in c.lower() for c in payload["stability"]["caveats"])


def test_ready_projection_can_include_draft_only_followup_items(tmp_path: Path) -> None:
    plan_path = tmp_path / "ws_ready.plan.md"
    plan_path.write_text(
        """---
name: WS8 projection readiness
tracking:
  epicRepo: owner/repo
---

# WS8 Projection Readiness

## Plan State

- Draft issue projection rule: keep Azure closeout on dedicated follow-up issues; do not block issue creation for ready workstreams.

## Implementation Plan

### Workstreams + merge points

- WS8-A: Ready story
  - Issue ready: true
  - Target repo: core
- WS8-F1: Azure closeout follow-up
  - Issue ready: false
  - Azure closeout only: true
  - Target repo: service
  - Blocked by: `G-MVP-DEPLOYED-DRAFTING-PARITY`
""",
        encoding="utf-8",
    )

    payload = run_cli(
        "--plan",
        str(plan_path),
        "--strategy",
        "workstreams",
        "--dry-run",
    )

    assert payload["stability"]["plan_status"] == "multi-repo-preview"
    assert payload["stability"]["multi_repo_projection"] is True
    assert payload["stability"]["needs_user_input"] == []
    assert len(payload["stability"]["unstable_items"]) == 1
    assert payload["epic"]["status_label"] == "status:draft"
    by_id = {child["source_id"]: child for child in payload["children"]}
    assert by_id["WS8-A"]["status_label"] == "status:draft"
    assert "decomposition:required" in by_id["WS8-A"]["labels"]
    assert by_id["WS8-F1"]["status_label"] == "status:draft"
    assert by_id["WS8-F1"]["azure_closeout_only"] is True


def test_stability_single_repo_plan_is_ready_for_apply_when_dispatch_clear(tmp_path: Path) -> None:
    """One child, one normalized repo: stability may report ready-for-apply when not blocked."""
    plan_path = tmp_path / "single_repo_lane.plan.md"
    plan_path.write_text(
        """---
tracking:
  provider: github
  project: ""
  epic: ""
  mode: draft
---

# Feature: Single-repo lane

## Implementation Plan

### Workstreams + merge points
- WS1: Only root work
  - Target repo: service
  - Review gates (named):
    - G-ISSUE-Dry-Run
""",
        encoding="utf-8",
    )

    payload = run_cli(
        "--plan",
        str(plan_path),
        "--repo",
        "OWNER/service",
        "--strategy",
        "workstreams",
        "--dry-run",
    )

    assert payload["stability"]["plan_status"] == "ready-for-apply"
    assert payload["stability"]["multi_repo_projection"] is False
    assert payload["stability"]["distinct_child_repo_slugs"] == [
        "OWNER/service"
    ]
    assert payload["stability"]["caveats"] == []


def test_root_alias_normalizes_to_literal_slug_in_labels_and_notes(tmp_path: Path) -> None:
    """Alias `root` should resolve to the configured root/service repo slug."""
    plan_path = tmp_path / "root_alias.plan.md"
    plan_path.write_text(
        """---
tracking:
  provider: github
  project: ""
  epic: ""
  mode: draft
---

# Feature: Root alias label check

## Implementation Plan

### Workstreams + merge points
- WS1: Root scoped story
  - Target repo: root
  - Review gates (named):
    - G-ISSUE-Dry-Run
""",
        encoding="utf-8",
    )

    payload = run_cli(
        "--plan",
        str(plan_path),
        "--repo",
        "OWNER/service",
        "--strategy",
        "workstreams",
        "--dry-run",
    )

    child = payload["children"][0]
    assert child["repo_targets"] == ["OWNER/service"]
    assert "repo:service" in child["labels"]
    assert "Implementation work stays in the target repo." in child["body"]


def test_legacy_full_repo_slug_normalizes_to_current_slug() -> None:
    mod = load_plan_to_issues_module()

    assert mod.normalize_repo_slug("OWNER/core") == "OWNER/core"
    assert (
        mod.normalize_repo_slug("OWNER/app")
        == "OWNER/app"
    )


def test_dispatch_metadata_distinguishes_auto_from_review_before_dispatch(tmp_path: Path) -> None:
    plan_path = tmp_path / "dispatch_mix.plan.md"
    plan_path.write_text(
        """---
tracking:
  provider: github
  project: ""
  epic: ""
  mode: draft
---

# Feature: Dispatch classification sample

## Implementation Plan

### Workstreams + merge points
- WS1: README inventory cleanup
  - Target repo: core
  - Issue ready: true
  - Points: 1
- WS2: Schema migration and infra rollout
  - Target repo: core, infra
  - Issue ready: true
  - Points: 1
  - Review gates (named):
    - G-CI-SCHEMA
""",
        encoding="utf-8",
    )

    payload = run_cli(
        "--plan",
        str(plan_path),
        "--repo",
        "OWNER/core",
        "--strategy",
        "workstreams",
        "--dry-run",
    )

    plan_execution = payload["plan_execution"]
    by_id = {child["source_id"]: child for child in payload["children"]}

    assert plan_execution["dispatch_blocked"] is False
    assert plan_execution["recommended_dispatch_mode"] == "dispatch-eligible"

    assert by_id["WS1"]["dispatch_recommendation"] == "auto-dispatch"
    assert by_id["WS1"]["validation_scope"] == "local"
    assert "Dispatch recommendation: `auto-dispatch`" in by_id["WS1"]["body"]

    assert by_id["WS2"]["dispatch_recommendation"] == "review-before-dispatch"
    assert "cross-repo" in by_id["WS2"]["risk_tags"]
    assert "migration" in by_id["WS2"]["risk_tags"]


def test_sync_preview_matches_existing_issues_and_reports_updates(tmp_path: Path) -> None:
    plan_path = tmp_path / "sync_preview.plan.md"
    plan_path.write_text(
        """---
tracking:
  provider: github
  project: ""
  epic: ""
  mode: draft
---

# Feature: Sync preview sample

## Implementation Plan

### Workstreams + merge points
- WS1: Existing issue body should be refreshed
  - Target repo: service
  - Issue ready: true
  - Review gates (named):
    - G-CI-SYNC
- WS2: Missing issue should be surfaced
  - Target repo: service
  - Issue ready: true
""",
        encoding="utf-8",
    )

    existing_issues_path = tmp_path / "existing_issues.json"
    existing_issues_path.write_text(
        json.dumps(
            [
                {
                    "number": 40,
                    "title": "[Epic][SYNC-PREVIEW] Feature: Sync preview sample",
                    "body": "## Source Plan\n- Plan path: `sync_preview.plan.md`\n- Plan key: `SYNC-PREVIEW`\n",
                    "labels": ["type:epic", "status:ready"],
                    "url": "https://example.test/issues/40",
                },
                {
                    "number": 41,
                    "title": "[WS1] Existing issue body should be refreshed",
                    "body": "## Source Plan\n- Plan path: `sync_preview.plan.md`\n- Source section: `WS1 Existing issue body should be refreshed`\n\n## Parent Epic\nhttps://example.test/issues/40\n",
                    "labels": ["type:story", "status:ready"],
                    "url": "https://example.test/issues/41",
                },
                {
                    "number": 99,
                    "title": "[WS-OLD] Stale issue",
                    "body": "## Source Plan\n- Plan path: `sync_preview.plan.md`\n- Source section: `WS-OLD Stale issue`\n",
                    "labels": ["type:story"],
                    "url": "https://example.test/issues/99",
                },
            ]
        ),
        encoding="utf-8",
    )

    payload = run_cli(
        "--plan",
        str(plan_path),
        "--repo",
        "OWNER/service",
        "--strategy",
        "workstreams",
        "--existing-issues-file",
        str(existing_issues_path),
        "--sync-preview",
    )

    ops = {op["source_id"]: op for op in payload["sync_preview"]["operations"]}
    assert ops["SYNC-PREVIEW"]["match"]["number"] == 40
    assert ops["SYNC-PREVIEW"]["action"] == "update"
    assert "body" in ops["SYNC-PREVIEW"]["changed_fields"]

    assert ops["WS1"]["match"]["number"] == 41
    assert ops["WS1"]["action"] == "update"
    assert "labels" in ops["WS1"]["changed_fields"]
    assert ops["WS1"]["body_changed"] is True

    assert ops["WS2"]["action"] == "create-missing"
    assert ops["WS2"]["match"] is None

    assert payload["sync_preview"]["unmatched_existing"] == [
        {
            "repo": "OWNER/service",
            "number": 99,
            "title": "[WS-OLD] Stale issue",
            "url": "https://example.test/issues/99",
        }
    ]
    assert payload["sync_preview"]["repos_considered"] == [
        "OWNER/service"
    ]
    assert payload["sync_preview"]["operations"][0]["issue_repo"] == (
        "OWNER/service"
    )


def test_sync_preview_prefers_open_duplicate_title_match(tmp_path: Path) -> None:
    mod = load_plan_to_issues_module()
    plan_path = tmp_path / "duplicate_title.plan.md"
    plan_path.write_text("# Duplicate title plan\n", encoding="utf-8")
    rel = mod.plan_reference_context(plan_path)[1]
    draft = mod.IssueDraft(
        title="[FUTURE-MAP-001] Publish future project map",
        body=(
            f"## Source Plan\n- Plan path: `{rel}`\n"
            "- Source section: `FUTURE-MAP-001 Publish future project map`\n"
        ),
        labels=["type:story"],
        kind="story",
        source_id="FUTURE-MAP-001",
    )

    match = mod.find_matching_issue(
        draft,
        existing_issues=[
            {
                "number": 160,
                "title": draft.title,
                "body": draft.body,
                "labels": ["type:story"],
                "url": "https://example.test/issues/160",
                "state": "CLOSED",
            },
            {
                "number": 96,
                "title": draft.title,
                "body": draft.body,
                "labels": ["type:story"],
                "url": "https://example.test/issues/96",
                "state": "OPEN",
            },
        ],
        relative_plan_path=rel,
    )

    assert match is not None
    assert match["number"] == 96


def test_sync_preview_adopts_existing_issue_from_non_landing_repo(tmp_path: Path) -> None:
    mod = load_plan_to_issues_module()
    plan_path = tmp_path / "cross_repo_adopt.plan.md"
    plan_path.write_text("# Cross repo adopt\n", encoding="utf-8")
    rel = mod.plan_reference_context(plan_path)[1]
    root = "OWNER/service"
    ui = "OWNER/ui"
    epic = mod.IssueDraft(
        title="[Epic][HAND] Cross repo adopt",
        body=f"## Source Plan\n- Plan path: `{rel}`\n- Plan key: `HAND`\n",
        labels=["type:epic", "status:draft"],
        kind="epic",
        source_id="HAND",
    )
    child = mod.IssueDraft(
        title="[UI-CONTRACT-001] Add UI contract",
        body=(
            f"## Source Plan\n- Plan path: `{rel}`\n"
            "- Source section: `UI-CONTRACT-001 Add UI contract`\n"
        ),
        labels=["type:story", "status:draft"],
        kind="story",
        source_id="UI-CONTRACT-001",
        execution_repo=ui,
        dispatch_recommendation="tracking-only",
        validation_scope="local",
    )
    epic_url = "https://example.test/root/72"
    issues_by_repo = {
        root: [
            {
                "number": 72,
                "title": epic.title,
                "body": epic.body,
                "labels": epic.labels,
                "url": epic_url,
                "state": "OPEN",
            },
            {
                "number": 90,
                "title": child.title,
                "body": mod.desired_body_for_sync(child, parent_epic_url=epic_url),
                "labels": mod.merged_labels_for_sync([], child.labels),
                "url": "https://example.test/root/90",
                "state": "OPEN",
            },
        ],
        ui: [],
    }

    preview = mod.build_sync_preview(
        epic_repo=root,
        plan_path=plan_path,
        epic=epic,
        children=[child],
        issues_by_repo=issues_by_repo,
    )

    op = {item["source_id"]: item for item in preview["operations"]}["UI-CONTRACT-001"]
    assert op["action"] != "create-missing"
    assert op["issue_repo"] == root
    assert op["desired_issue_repo"] == ui
    assert op["matched_outside_landing_repo"] is True
    assert op["match"]["number"] == 90


def test_load_existing_issues_fetches_large_state_snapshot() -> None:
    mod = load_plan_to_issues_module()
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)

        class Result:
            stdout = "[]"

        return Result()

    with patch.object(mod.subprocess, "run", fake_run):
        assert mod.load_existing_issues("OWNER/repo") == []

    cmd = calls[0]
    assert cmd[cmd.index("--limit") + 1] == "1000"
    assert cmd[cmd.index("--json") + 1] == "number,title,body,labels,url,state"


def test_gh_project_add_reuses_existing_project_item_cache() -> None:
    mod = load_plan_to_issues_module()
    mod.PROJECT_ITEM_URL_CACHE.clear()
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        assert "item-add" not in cmd

        class Result:
            stdout = json.dumps(
                {
                    "items": [
                        {
                            "id": "PVTI_existing",
                            "content": {
                                "url": "https://github.com/OWNER/repo/issues/145",
                            },
                        }
                    ]
                }
            )

        return Result()

    with patch.object(mod.subprocess, "run", fake_run):
        assert (
            mod.gh_project_add(
                "OWNER",
                5,
                "https://github.com/OWNER/repo/issues/145",
            )
            == "PVTI_existing"
        )

    assert calls[0][:3] == ["gh", "project", "item-list"]
    assert calls[0][calls[0].index("--limit") + 1] == "1000"


def test_multi_repo_sync_preview_uses_per_repo_issue_inventories(tmp_path: Path) -> None:
    mod = load_plan_to_issues_module()
    plan_path = tmp_path / "hand_multi_sync.plan.md"
    plan_path.write_text("# Hand multi-repo sync preview\n", encoding="utf-8")

    root = "OWNER/service"
    core = "OWNER/core"
    rel = mod.plan_reference_context(plan_path)[1]

    epic = mod.IssueDraft(
        title="[Epic][HAND] Hand multi-repo sync preview",
        body=f"## Source Plan\n- Plan path: `{rel}`\n- Plan key: `HAND`\n",
        labels=["type:epic", "status:draft"],
        kind="epic",
        source_id="HAND",
        execution_repo=root,
        dispatch_recommendation="tracking-only",
        validation_scope="local",
    )
    child_core = mod.IssueDraft(
        title="[WS1] Core sidecar",
        body=(
            f"## Source Plan\n- Plan path: `{rel}`\n"
            "- Source section: `WS1 Core sidecar`\n"
        ),
        labels=["type:story", "status:draft"],
        kind="story",
        source_id="WS1",
        execution_repo=core,
        dispatch_recommendation="tracking-only",
        validation_scope="local",
    )
    child_root = mod.IssueDraft(
        title="[WS2] Root follow-up",
        body=(
            f"## Source Plan\n- Plan path: `{rel}`\n"
            "- Source section: `WS2 Root follow-up`\n"
        ),
        labels=["type:story", "status:draft"],
        kind="story",
        source_id="WS2",
        execution_repo=root,
        dispatch_recommendation="tracking-only",
        validation_scope="local",
    )
    epic_url = "https://example.test/root/10"
    core_body = mod.desired_body_for_sync(child_core, parent_epic_url=epic_url)
    root_child_body = mod.desired_body_for_sync(child_root, parent_epic_url=epic_url)

    issues_by_repo = {
        root: [
            {
                "number": 10,
                "title": epic.title,
                "body": epic.body,
                "labels": mod.merged_labels_for_sync([], epic.labels),
                "url": epic_url,
            },
            {
                "number": 12,
                "title": child_root.title,
                "body": root_child_body,
                "labels": mod.merged_labels_for_sync(["type:story"], child_root.labels),
                "url": "https://example.test/root/12",
            },
        ],
        core: [
            {
                "number": 55,
                "title": child_core.title,
                "body": core_body,
                "labels": mod.merged_labels_for_sync(["type:story"], child_core.labels),
                "url": "https://example.test/core/55",
            },
            {
                "number": 77,
                "title": "[WS1] Decoy wrong plan file",
                "body": (
                    "## Source Plan\n- Plan path: `other.plan.md`\n"
                    "- Source section: `WS1 Core sidecar`\n"
                ),
                "labels": ["type:story"],
                "url": "https://example.test/core/77",
            },
        ],
    }

    preview = mod.build_sync_preview(
        epic_repo=root,
        plan_path=plan_path,
        epic=epic,
        children=[child_core, child_root],
        issues_by_repo=issues_by_repo,
    )

    assert set(preview["repos_considered"]) == {root, core}
    ops = {op["source_id"]: op for op in preview["operations"]}
    assert ops["HAND"]["issue_repo"] == root
    assert ops["HAND"]["match"]["number"] == 10
    assert ops["WS1"]["issue_repo"] == core
    assert ops["WS1"]["match"]["number"] == 55
    assert ops["WS1"]["action"] == "noop"
    assert ops["WS2"]["issue_repo"] == root
    assert ops["WS2"]["match"]["number"] == 12
    assert ops["WS2"]["action"] == "noop"
    assert preview["unmatched_existing"] == []


def test_multi_repo_sync_preview_rejects_legacy_array_issue_fixture(tmp_path: Path) -> None:
    plan_path = tmp_path / "multi_repo_array_sync.plan.md"
    plan_path.write_text(
        """---
tracking:
  provider: github
  project: ""
  epic: ""
  mode: draft
---

# Feature: Multi-repo array sync preview

## Implementation Plan

### Workstreams + merge points
- WS1: Admin UI issue
  - Target repo: admin-ui
  - Issue ready: true
""",
        encoding="utf-8",
    )

    existing_issues_path = tmp_path / "existing_issues.json"
    existing_issues_path.write_text(
        json.dumps(
            [
                {
                    "number": 1,
                    "title": "[Epic][MULTI-REPO-ARRAY-SYNC-PREVIEW] Feature: Multi-repo array sync preview",
                    "body": "## Source Plan\n- Plan path: `multi_repo_array_sync.plan.md`\n- Plan key: `MULTI-REPO-ARRAY-SYNC-PREVIEW`\n",
                    "labels": ["type:epic"],
                    "url": "https://example.test/issues/1",
                }
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--plan",
            str(plan_path),
            "--repo",
            "OWNER/service",
            "--strategy",
            "workstreams",
            "--existing-issues-file",
            str(existing_issues_path),
            "--sync-preview",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "Multi-repo sync requires --existing-issues-file to be a JSON object keyed by repo slug" in result.stderr


def test_multi_repo_sync_apply_updates_correct_repos(tmp_path: Path) -> None:
    mod = load_plan_to_issues_module()
    plan_path = tmp_path / "multi_sync_apply.plan.md"
    plan_path.write_text(
        """---
tracking:
  provider: github
  project: ""
  epic: ""
  mode: draft
---

# Feature: Multi-repo sync apply

## Implementation Plan

### Workstreams + merge points
- WS1: Core sidecar
  - Target repo: root, core
  - Issue ready: true
  - Review gates (named):
    - G-ISSUE-Dry-Run
- WS2: Root follow-up
  - Target repo: service
  - Issue ready: true
  - Review gates (named):
    - G-ISSUE-Dry-Run
""",
        encoding="utf-8",
    )

    root = "OWNER/service"
    core = "OWNER/core"
    dry = run_cli(
        "--plan",
        str(plan_path),
        "--repo",
        root,
        "--strategy",
        "workstreams",
        "--dry-run",
    )
    epic = mod.IssueDraft(**dry["epic"])
    children = [mod.IssueDraft(**c) for c in dry["children"]]
    by_id = {c.source_id: c for c in children}
    by_id["WS1"].execution_repo = core

    rel = mod.plan_reference_context(plan_path)[1]
    issues_by_repo = {
        root: [
            {
                "number": 1,
                "title": epic.title,
                "body": mod.desired_body_for_sync(epic),
                "labels": mod.merged_labels_for_sync([], epic.labels),
                "url": "https://example.test/root/1",
            }
        ],
        core: [],
    }

    edit_calls: list[tuple[str, int]] = []
    create_calls: list[tuple[str, str]] = []

    def fake_edit(repo: str, number: int, **kwargs: object) -> str:
        edit_calls.append((repo, number))
        return "ok"

    def fake_create(repo: str, draft: mod.IssueDraft) -> str:
        create_calls.append((repo, draft.source_id))
        return f"https://example.test/{repo.replace('/', '_')}/new"

    with (
        patch.object(mod, "gh_issue_edit", side_effect=fake_edit),
        patch.object(mod, "gh_issue_create", side_effect=fake_create),
        patch.object(mod, "gh_project_add"),
    ):
        result = mod.apply_sync_operations(
            epic_repo=root,
            project_owner=None,
            project_number=None,
            plan_path=plan_path,
            epic=epic,
            children=children,
            issues_by_repo=issues_by_repo,
        )

    assert edit_calls == []
    assert create_calls == [(core, "WS1"), (root, "WS2")]
    created = {item["source_id"]: item for item in result["created"]}
    assert created["WS1"]["issue_repo"] == core
    assert created["WS2"]["issue_repo"] == root
    assert "repos_considered" in result
    assert rel in epic.body


def test_multi_repo_apply_creates_children_in_execution_repos(tmp_path: Path) -> None:
    mod = load_plan_to_issues_module()
    plan_path = tmp_path / "multi_apply.plan.md"
    plan_path.write_text(
        """---
tracking:
  provider: github
  project: ""
  epic: ""
  mode: draft
---

# Feature: Multi-repo apply loop

## Implementation Plan

### Workstreams + merge points
- WS1: Nested repo work
  - Target repo: root, core
  - Issue ready: true
  - Review gates (named):
    - G-ISSUE-Dry-Run
- WS2: Root only work
  - Target repo: service
  - Issue ready: true
  - Review gates (named):
    - G-ISSUE-Dry-Run
""",
        encoding="utf-8",
    )

    root = "OWNER/service"
    core = "OWNER/core"
    dry = run_cli("--plan", str(plan_path), "--repo", root, "--strategy", "workstreams", "--dry-run")
    epic = mod.IssueDraft(**dry["epic"])
    children = [mod.IssueDraft(**c) for c in dry["children"]]
    children[0].execution_repo = core

    create_calls: list[tuple[str, str]] = []

    def fake_create(repo: str, draft: mod.IssueDraft) -> str:
        create_calls.append((repo, draft.kind))
        if draft.kind == "epic":
            return "https://example.test/epic/100"
        return f"https://example.test/{repo.replace('/', '_')}/child"

    with patch.object(mod, "gh_issue_create", side_effect=fake_create):
        epic_url = mod.gh_issue_create(mod.issue_landing_repo(root, epic), epic)
        for child in children:
            child.body = "\n".join([child.body, "", "## Parent Epic", epic_url])
            mod.gh_issue_create(mod.issue_landing_repo(root, child), child)

    assert create_calls[0] == (root, "epic")
    assert create_calls[1] == (core, "story")
    assert create_calls[2] == (root, "story")
    assert "## Parent Epic" in children[0].body
    assert epic_url in children[0].body


def test_leaf_issues_strategy_prefers_automation_issue_manifest(tmp_path: Path) -> None:
    plan_path = tmp_path / "automation_manifest.plan.md"
    plan_path.write_text(
        """---
name: automation manifest lane
tracking:
  epicRepo: OWNER/service
  baseBranch: main
---

# Feature: Automation manifest lane

## Implementation Plan

### Workstreams + merge points
- WS1: Legacy planning bucket
  - Target repo: service

## Automation Issue Manifest
### Leaf issues
- LEAF-001: Parser support for manifest leaves
  - Dispatch: agent-ready
  - Points: 1
  - Target repo: service
  - Depends on: none
  - Files in scope:
    - `skills/plan-to-issues/scripts/plan_to_issues.py`
    - `skills/plan-to-issues/scripts/test_plan_to_issues.py`
  - Validation:
    - `pytest skills/plan-to-issues/scripts/test_plan_to_issues.py`
  - Required gates: `G-ISSUE-Dry-Run`
- LEAF-002: Document manifest projection
  - Dispatch: manual-review
  - Suggested points: 2
  - Depends on: `LEAF-001`, OWNER/service#42
  - Files in scope:
    - `skills/plan-to-issues/SKILL.md`
    - `skills/plan-to-issues/reference.md`
  - Validation:
    - `pytest skills/plan-to-issues/scripts/test_plan_to_issues.py`
""",
        encoding="utf-8",
    )

    payload = run_cli(
        "--plan",
        str(plan_path),
        "--strategy",
        "leaf-issues",
        "--dry-run",
    )

    assert payload["strategy"] == "leaf-issues"
    assert [child["source_id"] for child in payload["children"]] == ["LEAF-001", "LEAF-002"]
    assert payload["children"][0]["title"] == "[LEAF-001] Parser support for manifest leaves"
    assert payload["children"][0]["dispatch_mode"] == "agent-ready"
    assert payload["children"][0]["dispatch_recommendation"] == "auto-dispatch"
    assert payload["children"][0]["suggested_points"] == 1
    assert "points:1" in payload["children"][0]["labels"]
    assert payload["children"][0]["write_scope"] == [
        "skills/plan-to-issues/scripts/plan_to_issues.py",
        "skills/plan-to-issues/scripts/test_plan_to_issues.py",
    ]
    assert payload["children"][0]["validation_commands"] == [
        "pytest skills/plan-to-issues/scripts/test_plan_to_issues.py"
    ]
    assert payload["children"][0]["validation_requirements"] == [
        "pytest skills/plan-to-issues/scripts/test_plan_to_issues.py"
    ]
    assert payload["children"][0]["gates"] == ["G-ISSUE-DRY-RUN"]
    assert payload["children"][0]["execution_repo"] == "OWNER/service"
    assert payload["children"][0]["base_branch"] == "main"
    assert "- Open dependencies: `none`" in payload["children"][0]["body"]
    assert "- Manual gates remaining: `none`" in payload["children"][0]["body"]
    assert payload["children"][1]["dependencies"] == ["LEAF-001", "OWNER/service#42"]
    assert payload["children"][1]["dependency_issue_refs"] == ["OWNER/service#42"]
    assert payload["children"][1]["dispatch_mode"] == "tracking-only"
    assert payload["children"][1]["dispatch_recommendation"] == "tracking-only"
    assert payload["children"][1]["status_label"] == "status:draft"
    assert "decomposition:required" in payload["children"][1]["labels"]
    assert payload["children"][1]["suggested_points"] == 2
    assert "points:2" in payload["children"][1]["labels"]
    assert "- Open dependencies: `LEAF-001; OWNER/service#42`" in payload["children"][1]["body"]
    assert "Decompose `points:2` issue into one-point child issues before local automation dispatch." in payload["children"][1]["body"]
    assert len(payload["children"]) == 2


def test_manifest_leaf_explicit_execution_repo_overrides_custom_source_repo(tmp_path: Path) -> None:
    plan_path = tmp_path / "custom_execution_repo.plan.md"
    plan_path.write_text(
        """---
name: custom execution repo
tracking:
  epicRepo: OWNER/service
  baseBranch: fix/base
---

# Feature: Custom execution repo

## Automation Issue Manifest
### Leaf issues
- UI-LEAF-001: Build UI fixture
  - Dispatch: manual-review
  - Points: 3
  - Target repo: OWNER/ui
  - Execution repo: OWNER/ui
  - Base branch: main
  - Depends on: none
  - Files in scope:
    - Atlas-Memory-UI/src/api/workflows.ts
  - Validation:
    - cd "Atlas-Memory-UI" && npm run test -- workflow-intake-contract.test.ts
  - Required gates: `G-UI-IntakeContract`
""",
        encoding="utf-8",
    )

    payload = run_cli(
        "--plan",
        str(plan_path),
        "--repo",
        "OWNER/service",
        "--strategy",
        "leaf-issues",
        "--dry-run",
    )

    child = payload["children"][0]
    assert child["repo_targets"] == ["OWNER/ui"]
    assert child["execution_repo"] == "OWNER/ui"
    assert child["base_branch"] == "main"


def test_manifest_leaf_scheduler_metadata_projects_to_body_and_project_fields(tmp_path: Path) -> None:
    plan_path = tmp_path / "automation_manifest_scheduler.plan.md"
    plan_path.write_text(
        """---
name: automation manifest scheduler lane
tracking:
  epicRepo: OWNER/service
---

# Feature: Automation manifest scheduler lane

## Implementation Plan

## Automation Issue Manifest
### Leaf issues
- LEAF-010: Scheduler-aware leaf
  - Dispatch: agent-ready
  - Agent type: generalPurpose
  - Points: 1
  - Target repo: service
  - Depends on: none
  - Parallel group: docs-and-parser
  - Blocks:
    - LEAF-020
    - OWNER/service#44
  - Critical path rank: 3
  - Merge group: manifest-projection
  - Combine policy: combine-with-merge-group
  - Conflict class: plan-to-issues-parser
  - Validation tier: T2
  - Files in scope:
    - `skills/plan-to-issues/scripts/plan_to_issues.py`
  - Validation:
    - `pytest skills/plan-to-issues/scripts/test_plan_to_issues.py`
""",
        encoding="utf-8",
    )

    payload = run_cli(
        "--plan",
        str(plan_path),
        "--repo",
        "OWNER/service",
        "--strategy",
        "leaf-issues",
        "--dry-run",
    )

    child = payload["children"][0]
    assert child["agent_type"] == "generalPurpose"
    assert child["parallel_group"] == "docs-and-parser"
    assert child["blocks"] == ["LEAF-020", "OWNER/service#44"]
    assert child["critical_path_rank"] == 3
    assert child["merge_group"] == "manifest-projection"
    assert child["combine_policy"] == "combine-with-merge-group"
    assert child["conflict_class"] == "plan-to-issues-parser"
    assert child["validation_tier"] == "T2"
    assert "- Parallel group: `docs-and-parser`" in child["body"]
    assert "- Blocks: `LEAF-020; OWNER/service#44`" in child["body"]
    assert "- Critical path rank: `3`" in child["body"]
    assert "- Merge group: `manifest-projection`" in child["body"]
    assert "- Combine policy: `combine-with-merge-group`" in child["body"]
    assert "- Conflict class: `plan-to-issues-parser`" in child["body"]
    assert "- Validation tier: `T2`" in child["body"]
    assert "- Agent type: `generalPurpose`" in child["body"]

    mod = load_plan_to_issues_module()
    values = mod.project_field_values(
        mod.IssueDraft(**child),
        issue_repo="OWNER/service",
        plan_key="PLAN-1",
    )

    assert values["ParallelGroup"] == "docs-and-parser"
    assert values["Blocks"] == "LEAF-020\nOWNER/service#44"
    assert values["CriticalPathRank"] == 3
    assert values["MergeGroup"] == "manifest-projection"
    assert values["CombinePolicy"] == "combine-with-merge-group"
    assert values["ConflictClass"] == "plan-to-issues-parser"
    assert values["ValidationTier"] == "T2"
    assert values["AgentType"] == "generalPurpose"


def test_leaf_issues_strategy_blocks_missing_dependency_metadata(tmp_path: Path) -> None:
    plan_path = tmp_path / "automation_manifest_missing_dependencies.plan.md"
    plan_path.write_text(
        """---
name: automation manifest missing dependency metadata
tracking:
  epicRepo: OWNER/service
---

# Feature: Automation manifest missing dependency metadata

## Implementation Plan

## Automation Issue Manifest
### Leaf issues
- LEAF-001: Missing dependency field
  - Dispatch: agent-ready
  - Points: 1
  - Target repo: service
  - Files in scope:
    - `skills/plan-to-issues/scripts/plan_to_issues.py`
  - Validation:
    - `pytest skills/plan-to-issues/scripts/test_plan_to_issues.py`
""",
        encoding="utf-8",
    )

    payload = run_cli(
        "--plan",
        str(plan_path),
        "--repo",
        "OWNER/service",
        "--strategy",
        "leaf-issues",
        "--dry-run",
    )

    child = payload["children"][0]
    assert child["dependencies"] == []
    assert child["status_label"] == "status:blocked"
    assert child["dispatch_recommendation"] == "tracking-only"
    assert "- Open dependencies: `none`" in child["body"]
    assert "Add explicit manifest dependency metadata" in child["body"]
    assert child["automation_blockers"] == [
        "Add explicit manifest dependency metadata (`Depends on: none` or concrete leaf ids/issue refs) before auto-dispatch."
    ]


def test_leaf_issues_strategy_marks_oversized_parents_not_issue_ready(tmp_path: Path) -> None:
    plan_path = tmp_path / "automation_manifest_oversized_parent.plan.md"
    plan_path.write_text(
        """---
name: automation manifest oversized parent
tracking:
  epicRepo: OWNER/service
---

# Feature: Automation manifest oversized parent

## Implementation Plan

## Automation Issue Manifest
### Leaf issues
- LEAF-001: Oversized parent
  - Dispatch: manual-review
  - Points: 3
  - Target repo: service
  - Depends on:
    - none
  - Files in scope:
    - `skills/plan-to-issues/scripts/plan_to_issues.py`
  - Validation:
    - `pytest skills/plan-to-issues/scripts/test_plan_to_issues.py`
""",
        encoding="utf-8",
    )

    payload = run_cli(
        "--plan",
        str(plan_path),
        "--repo",
        "OWNER/service",
        "--strategy",
        "leaf-issues",
        "--dry-run",
    )

    child = payload["children"][0]
    assert child["issue_ready"] is False
    assert child["status_label"] == "status:draft"
    assert child["dispatch_recommendation"] == "tracking-only"
    assert "- Issue ready: `false`" in child["body"]
    assert child["automation_blockers"] == [
        "Decompose `points:3` issue into one-point child issues before local automation dispatch."
    ]

    mod = load_plan_to_issues_module()
    values = mod.project_field_values(
        mod.IssueDraft(**child),
        issue_repo="OWNER/service",
        plan_key="PLAN-1",
    )

    assert values["IssueReady"] == "Draft"
    assert values["AutomationState"] == "Manual"


def test_leaf_issues_strategy_blocks_opaque_and_unsupported_dependencies(tmp_path: Path) -> None:
    plan_path = tmp_path / "automation_manifest_blocked.plan.md"
    plan_path.write_text(
        """---
name: automation manifest blocked lane
tracking:
  epicRepo: OWNER/service
---

# Feature: Automation manifest blocked lane

## Implementation Plan

## Automation Issue Manifest
### Leaf issues
- LEAF-010: Blocked leaf
  - Dispatch: agent-ready
  - Points: 1
  - Target repo: service
  - Depends on:
    - `WS1-MP2`
    - upstream planning sync
  - Files in scope:
    - `skills/plan-to-issues/scripts/plan_to_issues.py`
  - Validation:
    - `pytest skills/plan-to-issues/scripts/test_plan_to_issues.py`
""",
        encoding="utf-8",
    )

    payload = run_cli(
        "--plan",
        str(plan_path),
        "--repo",
        "OWNER/service",
        "--strategy",
        "leaf-issues",
        "--dry-run",
    )

    child = payload["children"][0]
    assert child["dependencies"] == ["WS1-MP2", "upstream planning sync"]
    assert child["dispatch_recommendation"] == "tracking-only"
    assert child["status_label"] == "status:blocked"
    assert child["automation_blockers"] == [
        "Convert dependency token `WS1-MP2` into an explicit issue ref or Automation Issue Manifest leaf id before auto-dispatch.",
        "Resolve opaque dependency `upstream planning sync` into an explicit issue ref or Automation Issue Manifest leaf id before auto-dispatch.",
    ]
    assert "## Dispatch Guardrails" in child["body"]
    assert "Convert dependency token `WS1-MP2`" in child["body"]
