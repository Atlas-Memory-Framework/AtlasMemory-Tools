# Dispatch governance implementation validation

The user authorized local documentation, implementation and testing of the
dispatcher, independent challenge, human handoffs and separate authority
boundary. This update builds on the completed
[RUNTIME-A–D implementation](azure-devops-runtime-validation-2026-09-08.md), with
507 passing runtime tests as its baseline. It preserves the target checkout's
existing uncommitted changes and HEAD
`0a571a5b94dfa6ea53a7ea032b4d300b5002f8bf`.

## Independent review

Four owners implemented authority, routing/human gates, action enforcement and
dispatcher/configuration. They reviewed other owners' changes before delivery.
The root integrated operating documentation, shared REST write timing, and
source-copy/upgrade exclusions for operator trust, throttle, claims and worktrees.

Review reproduced and corrected these boundaries:

- Sensitive filenames could evade risk floors; generic failure prose could
  trigger escalation without a candidate-bound failed command or review.
- A numeric supplied clock did not account for expiry during signature
  verification; the verifier now includes monotonic elapsed time.
- Worker human-receipt bindings omitted the policy digest used by the dispatcher.
- Accepted human input satisfied a gate but did not reach model context.
- Direct routed worker calls needed proof of actual parent-recorded assessment,
  and worker role calls needed the same durable budget as assessment.
- Candidate-specific human responses had to be added after preparation without
  changing its model configuration. Long human waits needed historical prepared
  proof with fresh publication authority and current Board/source checks.
- Authorization had to be checked after a shared throttle wait, immediately
  before a write, rather than only before waiting.

Public fixture signatures exercise real OpenSSL verification. Tests generate
synthetic signing material only in memory and persist no private key or real
trust enrollment. Independent mutation checks showed that the expiry,
post-throttle authority, and operator-state copy tests fail when their guards
are removed.

## Local validation

- `python3 -B -m unittest discover -s templates/local-automation-runtime/tests`:
  **702 tests passed**, including 195 more tests than the 507-test baseline.
- `python3 -B scripts/verify_repo.py`: **passed**, including 109 repository
  tests, 55 plan-to-issues checks, the 702 runtime tests, static/JSON/compile
  gates, source-copy guards, temporary harness generation and whitespace checks.
- Real integration fixtures cover signed assessment through the actual worker
  and Azure Boards provider, with local fake HTTP/model transports. They verify
  that an invalid execution grant cannot trigger identity authentication and
  that a complete native manifest survives dispatcher handoff.
- Standalone routing and inspection pilots both passed with empty effects,
  blocked readiness and no completion or dispatch. The routing report showed
  the unchanged four Astra/max defaults beside explicit Terra/medium assessment
  and Sol/high challenge settings.
- Cross-review's final transport-context mismatch was corrected: direct worker
  verification rejects an altered context hash even when the outer receipt
  digest is recomputed. New routed CLI failures return structured blocked
  results without authentication or a false completion claim.

These checks passed in both the isolated review checkout and the requested
`/home/instablinds-admin/code/AtlasMemory-Tools` checkout inside the existing
workspace-write sandbox. The target rerun passed all 702 runtime tests and the
complete repository verifier. Both target offline pilots returned no effects.
All 37 delivered files matched their reviewed hashes and modes; every unrelated
baseline file and the existing HEAD remained unchanged. The final documentation
update records these results without changing tested code.

## Operational scope

The original Website configuration still resolves all four worker roles to
`gpt-6-astra` / `max`. A separately selected policy proposes Terra/medium
assessment, Sol/high challenge, and explicit worker profiles. Tests verify
commands, configuration and transport records using fixtures; no live model or
validator canary was dispatched, and account availability remains unqualified.

The Board's 53 applied links and 18 unauthorized prerequisites are unchanged.
The Website example remains read-only and dependency eligibility remains blocked.
No Website source, live Board/Repo state, runtime installation, real issuer
enrollment, publication, workflow, deployment, merge, protected branch,
permission or service connection was changed. No credentials were accessed.

The next local read-only step is the
[inert routing pilot](azure-dispatch-governance.md#inert-routing-pilot), followed
by the separately reviewed [Azure inspection pilot](azure-devops-runtime.md#inspection-and-previews).
