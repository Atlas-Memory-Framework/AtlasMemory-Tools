# Handoff: Instablinds Commerce Runtime

**Created:** 2026-05-26 01:42 UTC
**Project:** `/var/home/mat/Desktop/Instablinds2-Automation-Runtime`
**Branch:** runtime-managed worktrees against `Instablinds/Instablinds2` base `mat`
**Purpose for next session:** Continue only genuinely actionable Instablinds work; remaining launch issues are manual-gated unless the user provides production/DR/go-no-go decisions.
**Continues from:** `.codex/handoffs/2026-05-25-0457-shopify-commerce-runtime-handoff.md`

## Current State
WS4 and WS5 are complete. All child issues were implemented, merged, and closed. No Instablinds automation shift/unattended/repair process was running at last check.

Open Instablinds items after this pass:
- `#15` production hosting/DR eval: open and blocked.
- `#193` WS7 launch go/no-go disposition: open and blocked.
- `#185` and `#1` epics: open.

The deployed smoke was rerun on 2026-05-26 UTC and still fails:
`Commerce API request failed: 502 Bad Gateway {"status":"error","code":502,"message":"Application failed to respond","request_id":"cM8H8Qi9T1Os2QyYo3UVLg"}`.
Evidence comments were posted to #15 and #193.

## Decisions
- **Do not close #15 or #193 without human input**: both require production account/geography/DR/restore/ownership and launch go/no-go decisions.
- **Manual merges were used for billing-gated CI**: GitHub Actions jobs consistently failed before runner start due billing/spending-limit annotations. Each merged PR had exact-head local validation evidence.
- **Docs expectations updated**: closure notes now include either docs impact or docs-not-needed rationale. #254/#263 updated the commerce demo/evidence documentation surface.
- **Do not kill Atlas Memory runtime processes**: unrelated processes under `/home/mat/distrobox-homes/atlas-agent/agent-runtime` were active; leave them alone.

## Completed Issues and PRs
- WS4 parent #191 closed.
- WS4 children: #248 -> PR #249, #247 -> #250, #246 -> #251, #245 -> #252, #244 -> #253. All merged/closed.
- WS5 parent #192 closed.
- WS5 children: #258 -> PR #259, #257 -> #260, #256 -> #261, #255 -> #262, #254 -> #263. All merged/closed.

## Verification
- For PRs #249-#253 and #259-#263, local validation passed on exact PR heads. Canonical `<!-- atlas-agent-local-validation -->` markers were added where the repair agent used a non-canonical marker.
- Deployed smoke against `https://backend-production-e9a0.up.railway.app`: failed with 502. This keeps #15/#193 blocked.
- `gh pr list --repo Instablinds/Instablinds2 --state open`: empty after PR #263 merge.

## Open Questions and Blockers
- [ ] Human must decide production account/geography/DR/restore/ownership plan for #15.
- [ ] Human must make explicit launch go/no-go disposition for #193.
- [ ] GitHub Actions billing/spending-limit issue must be fixed outside repo code before CI can be trusted again.
- [ ] Railway backend 502 must be debugged/fixed before public launch readiness can pass.

## Next Steps
1. If the user provides production/DR/go-no-go decisions, update #15/#193 with that decision and create only the needed follow-up issue(s).
2. If asked to continue without those decisions, work on the deployed backend 502 as a separate bounded issue; do not mark public launch ready.
3. Before any new automation dispatch, verify no Instablinds mutating runtime process is active with `ps -eo pid,ppid,etime,stat,cmd | rg 'Instablinds2-Automation-Runtime|atlas-agent-shift|atlas-agent-unattended|project-reconcile|atlas-agent-pr-repair|codex exec'`.

## Context Notes
- Use `local-automation-runtime-operate`.
- Only one mutating Instablinds operator at a time.
- Pause sleeping shifts with `pkill -INT -f 'atlas-agent-shift --cycles 24'` before manual validation/merge.
- Do not rely on GitHub Actions until billing/spending-limit is resolved; use exact-head local validation and record evidence.
- Updated runtime policy from another agent: PRs need pre-PR verification evidence; validation waivers must be explicit; workstream review is a completion bundle including docs/docs-not-needed and garbage collection; older workstream-review outputs without `completion_review` should be treated as incomplete before dependency promotion.
