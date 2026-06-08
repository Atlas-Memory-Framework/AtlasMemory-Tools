from __future__ import annotations

import importlib.util
import sys
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "plan" / "scripts" / "validate_plan.py"


def load_validator_module():
    spec = importlib.util.spec_from_file_location("plan_validate_plan", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def base_plan(review_hash: str = "0" * 64) -> str:
    return textwrap.dedent(
        f"""\
        # Feature: Safe automation lane

        ## Plan State
        PlanFormatVersion: 2
        PlanId: safe-automation-lane
        Status: Draft
        StructuralStatus: Draft
        SubstanceStatus: NotReviewed
        ProjectionApproval: NotRequested
        DispatchApproval: NotRequested
        CurrentStage: Reviews
        PlanTier: Full
        AutomationTarget: unattended-prs
        LastUpdated: 2026-05-29T08:00:00

        ## Gate Results
        ProblemDefinitionComplete: Pass
        TechnicalClarity: Pass
        HumanReadabilityReview: Pass
        PlanReadiness: Pass
        AutomationReadiness: Pass
        PlanningReviewsComplete: Pass

        ## Decision Log
        ### DR-001: Keep dispatch bounded
        - Stage: Implementation
        - Date: 2026-05-29
        - Decision: Keep unattended work to one-point leaf issues.
        - Options considered:
          - A) One-point leaves
          - B) Broad workstream dispatch
          - C) Manual-only execution
        - Why chosen: It reduces review and merge risk.
        - Status: Accepted

        ## Problem Definition
        Problem narrative:
        Automation currently depends on a human operator noticing which work is safe. The desired workflow is a bounded local lane that exposes enough evidence for safe unattended execution.

        Current broken workflow:
        - Operator manually checks issue scope before every run.

        Desired workflow:
        - Ready issues carry scope, validation, and dependency evidence.

        Why this matters / why now:
        - Runtime dispatch is moving from manual supervision to bounded shifts.

        Current-state facts:
        - Fact 1: Runtime scripts read issue labels before dispatch. (source: file)
        - Fact 2: Project fields show dependency status. (source: command)
        - Fact 3: Operators approve dispatch manually today. (source: user)

        Success criteria (measurable):
        - SC1: A ready leaf issue can be dispatched without extra clarification.

        Constraints:
        - Preserve manual approval for risky work.

        Scope:
        - In scope:
          - Plan validation and review freshness.
        - Out of scope:
          - Product architecture changes.

        Open questions:
        - Q1: Should dispatch require project sync?
          - Status: Deferred (DR-001)
          - Trigger: Before project sync enters the hot path.

        Decision boundaries (if any):
        - Decision needed:
          - A) Keep manual approval
          - B) Auto approve all work
          - C) Disable automation
        Recommended default: A (safest)

        ## Technical Plan
        ### Technical Plan Intro
        The validator checks the authoring document for concrete readiness evidence before downstream automation consumes it. It uses local markdown structure and fails closed on stale reviews.

        ### Integration Points
        - Plan markdown files.

        ### Proposed Architecture Changes
        - Add a local validation script.

        ### Failure Modes (per integration point)
        - Missing gates - detected by validation - fixed before projection.

        ### Invariants / Non-Changes
        - GitHub issues remain execution truth.

        ## Implementation Plan
        ### Agent roster (required for PlanTier: Full)
        - implementation: validates plan structure.

        ### File Deltas (exhaustive) + rationale
        - skills/plan/scripts/validate_plan.py - create - implementation - deterministic validator

        ### Workstreams + merge points
        - WS1: Validator
          - Owner: implementation
          - Agent type: generalPurpose
          - Delegate: required
          - Intended behavior change: reject stale plans
          - Depends on: none
          - Review gates (named):
            - G-CI-Unit
          - Owns files:
            - skills/plan/scripts/validate_plan.py
          - Merge point / integration step: MP1

        ### Delegation Quality Gate (required for PlanTier: Full)
        - DQ-1 Workstream delegation metadata complete: Pass
        - DQ-2 File ownership conflict-free before merge points: Pass
        - DQ-3 Delegation coverage: Pass
        - DQ-4 Validation delegation path present: Pass

        ### Phases + tasks + exit criteria
        #### Phase 1: Validator
        - Owner(s): implementation
        - Depends on: none
        - Tasks (by owner):
          - Owner: implementation
            - [ ] Add validator
        - Exit criteria (evidence): unit tests pass
        - Gates (named):
          - G-CI-Unit

        ### Review gates (named + definitions)
        - G-CI-Unit:
          - Where it runs: Local
          - Entry point / command: python3 -m unittest tests.test_plan_validator
          - Green means: all validator tests pass

        ### Merge points -> required gates
        - MP1: validator merge
          - Blocks on:
            - G-CI-Unit

        ### Test Matrix
        - validator - stale review risk - unit - where it runs: Local

        ### Test plan (CI vs deployed)
        - CI:
          - unit tests
        - Deployed environment:
          - not applicable

        ### Rollout / Rollback
        - Rollout: run validator in planning workflow
        - Rollback trigger: false positive blocks valid plan
        - Rollback steps: disable validator gate temporarily by DR

        ## Automation Issue Manifest
        ### Dispatch policy
        - Automation target: unattended-prs
        - Dispatch strategy: sequential
        - Max concurrent work items: 1
        - Required labels: agent:ready
        - Default reviewer / reviewer pool: maintainer
        - Branch policy: feature branch per issue
        - PR policy: draft
        - Merge policy: manual
        - Rebase/update policy: update before merge
        - Failure policy: stop and report
        - Human approval required before dispatch: yes

        ### Containers
        - WS1:
          - Type: workstream
          - Parent: none
          - Dispatch: tracking-only
          - Source plan sections:
            - Implementation Plan / WS1

        ### Leaf issues
        - WS1-LEAF-001: Add validator
          - Type: story
          - Parent: WS1
          - Owner: implementation
          - Agent type: generalPurpose
          - Dispatch: agent-ready
          - Depends on:
            - none
          - Parallel group: validators
          - Blocks:
            - none
          - Critical path rank: 1
          - Merge group: validators
          - Combine policy: solo
          - Conflict class: plan-validator
          - Validation tier: T1
          - External blockers:
            - none
          - Manual blockers:
            - none
          - Files in scope:
            - skills/plan/scripts/validate_plan.py
          - Files out of scope:
            - product/runtime files
          - Required gates:
            - G-CI-Unit
          - Validation:
            - python3 -m unittest tests.test_plan_validator
          - Acceptance criteria:
            - stale reviews fail
          - One PR contract: yes
          - Risk / dispatch notes: low risk
          - Source plan sections:
            - Implementation Plan / WS1

        ### Manifest validation summary
        - Dependency graph acyclic: Pass
        - Dependencies resolvable: Pass
        - Gate coverage complete: Pass
        - File-scope conflicts resolved: Pass
        - Acceptance criteria executable: Pass
        - Required metadata complete: Pass
        - Notes / waivers (must cite DR-xxx):
          - none

        ## Planning Reviews
        ### Zero-Context Review
        - Reviewer: doc-reviewer-zero-context
        - RefreshedAt: 2026-05-29T08:30:00
        - ReviewedPlanHash: sha256:{review_hash}
        - Findings (schema):
          - Missing context:
            - F-001: none
        - Disposition:
          - Reject: F-001 -> no issue

        ### Expert Technical Review
        - Trigger: N/A
        - Rationale: not triggered; local validator only.

        ### Security/Privacy Review
        - Reviewer: security
        - RefreshedAt: 2026-05-29T08:30:00
        - ReviewedPlanHash: sha256:{review_hash}
        - Findings (schema):
          - Security/privacy risks:
            - F-001: none
        - Disposition:
          - Reject: F-001 -> no issue

        ### Human Readability Review
        - Reviewer: doc-reviewer-human
        - RefreshedAt: 2026-05-29T08:30:00
        - ReviewedPlanHash: sha256:{review_hash}
        - Findings:
          - Product/system clarity:
            - F-001: clear
        - Pass/fail readability statement: Pass
        - Disposition:
          - Accept: F-001 -> DR-001

        ### Implementer Readiness Review
        - Reviewer: doc-reviewer-implementer
        - RefreshedAt: 2026-05-29T08:30:00
        - ReviewedPlanHash: sha256:{review_hash}
        - Findings:
          - Top 5 gotchas:
            - F-001: none
        - Disposition:
          - Reject: F-001 -> no issue

        ### Automation Readiness Review
        - Reviewer: automation-readiness
        - RefreshedAt: 2026-05-29T08:30:00
        - ReviewedPlanHash: sha256:{review_hash}
        - Findings:
          - Manifest gaps:
            - F-001: none
        - Disposition:
          - Reject: F-001 -> no issue
        """
    )


class PlanValidatorTests(unittest.TestCase):
    def test_passing_plan_accepts_matching_review_hashes(self) -> None:
        module = load_validator_module()
        plan = base_plan()
        digest = module.reviewed_plan_hash(plan)
        results = module.validate(base_plan(digest))

        self.assertEqual({result.gate: result.status for result in results}, {
            "ProblemDefinitionComplete": "Pass",
            "PlanReadiness": "Pass",
            "AutomationReadiness": "Pass",
            "PlanningReviewsComplete": "Pass",
            "PlanStateSanity": "Pass",
        })

    def test_problem_definition_requires_three_sourced_facts(self) -> None:
        module = load_validator_module()
        plan = base_plan(module.reviewed_plan_hash(base_plan())).replace(
            "- Fact 3: Operators approve dispatch manually today. (source: user)\n",
            "",
        )
        result = next(result for result in module.validate(plan) if result.gate == "ProblemDefinitionComplete")

        self.assertEqual(result.status, "Fail")
        self.assertTrue(any("at least 3 sourced facts" in message for message in result.messages))

    def test_planning_reviews_require_hash_or_refreshed_at(self) -> None:
        module = load_validator_module()
        digest = module.reviewed_plan_hash(base_plan())
        plan = base_plan(digest)
        plan = plan.replace("- RefreshedAt: 2026-05-29T08:30:00\n", "- Refreshed: 2026-05-29\n")
        plan = plan.replace(f"- ReviewedPlanHash: sha256:{digest}\n", "")

        result = next(result for result in module.validate(plan) if result.gate == "PlanningReviewsComplete")

        self.assertEqual(result.status, "Fail")
        self.assertTrue(any("Legacy Refreshed date is not enough" in message for message in result.messages))

    def test_plan_state_sanity_blocks_open_questions(self) -> None:
        module = load_validator_module()
        digest = module.reviewed_plan_hash(base_plan())
        plan = base_plan(digest).replace("Status: Deferred (DR-001)", "Status: Open")

        result = next(result for result in module.validate(plan) if result.gate == "PlanStateSanity")

        self.assertEqual(result.status, "Fail")
        self.assertTrue(any("Open questions remain" in message for message in result.messages))


if __name__ == "__main__":
    unittest.main()
