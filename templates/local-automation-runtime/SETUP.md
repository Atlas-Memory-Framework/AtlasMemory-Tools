# Setup

1. Install GitHub CLI and authenticate:

   ```bash
   gh auth login
   gh auth status
   ```

2. Copy and edit runtime config:

   ```bash
   cp config.env.example config.env
   cp repos.example.txt repos.txt
   cp config/required-checks.example.json required-checks.json
   ```

3. Prepare Codex auth under `codex-home/` for the worker container.

4. Build the local Codex image:

   ```bash
   ./build_codex_image.sh
   ```

5. Validate:

   ```bash
   python3 -m unittest tests.test_local_agent_autonomy
   ./atlas-agent-finalize --required-checks-file required-checks.json
   ```

6. Start with dry runs, then use `--apply` only after the target repo labels/check names are configured.
