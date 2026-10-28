# Plain technical English validation

The canonical skill is `skills/plain-technical-english/SKILL.md`. Generated adapters are installation artifacts and must be regenerated from canonical source.

The retained semantic review is [20261016-review.json](../evals/plain-technical-english/20261016-review.json). Its judgments cover the synthetic drafts in `tests/fixtures/plain-technical-english.json`; they do not establish the quality of every future document. The record validator checks source hashes, required review fields and quotation anchors. A formally valid judgment can still be wrong, so an independent reader must assess meaning.

Run the focused checks from the repository root:

```sh
python3 -m unittest discover -s tests -p test_plain_technical_english.py
python3 scripts/install_harness.py --harness codex --target . --check
```

The full release gate is `python3 scripts/verify_repo.py` using an environment with `requirements-dev.txt` installed. No local account, installation path, private worktree, or historical security review is required to reproduce these checks.

Use the skill while authoring: state the outcome, actor, action, conditions, reason and uncertainty. Preserve technical detail and correct material ambiguity using verified context. Do not infer missing facts or confuse shorter prose with clearer reasoning.
