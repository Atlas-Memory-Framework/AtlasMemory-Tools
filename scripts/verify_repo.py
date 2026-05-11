#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_DEFAULT_TOKENS = (
    "Atlas-" + "Memory-Framework",
    "Atlat-" + "Memory-Azure-Implmentation",
    "Mateusz" + "Kordasiewicz",
    "AtlasMemory" + "-Dev",
    "fix/mime-" + "resolution-pins-mainline",
)

FORBIDDEN_NEUTRAL_COPY = (
    "Atlas " + "automation",
    "Atlas " + "Codex runtime",
    "Atlas " + "local agent",
)

SCAN_PATHS = (
    "README.md",
    "docs",
    "skills",
    "agents",
    "templates",
    "scripts",
    "tests",
    "manifests",
    ".github",
    ".cursor",
)

REQUIRED_COPY_PATHS = (
    "skills",
    "agents",
    "templates/local-automation-runtime",
    "docs/source-of-truth.md",
    "manifests/atlas-tools.v1.json",
    "scripts/install_harness.py",
    "scripts/enforce_local_ssot.py",
    "scripts/verify_harness.py",
    "scripts/verify_repo.py",
    "tests/test_manifest_and_harness.py",
    ".github/workflows/verify.yml",
    ".cursor/skills/local-automation-runtime-setup/SKILL.md",
    ".cursor/skills/local-automation-runtime-operate/SKILL.md",
    ".cursor/skills/local-automation-runtime-upgrade/SKILL.md",
)

JSON_FILES = (
    "manifests/atlas-tools.v1.json",
    "ssot-projects.example.json",
    "templates/local-automation-runtime/required-checks.json",
    "templates/local-automation-runtime/config/required-checks.example.json",
    "templates/local-automation-runtime/config/local-validation.example.json",
    "templates/local-automation-runtime/config/deployed-validation.example.json",
)

PY_COMPILE_FILES = (
    "scripts/harnesslib.py",
    "scripts/enforce_local_ssot.py",
    "scripts/install_harness.py",
    "scripts/verify_harness.py",
    "scripts/verify_repo.py",
    "skills/plan-to-issues/scripts/plan_to_issues.py",
    "skills/plan-to-issues/scripts/test_plan_to_issues.py",
    "templates/local-automation-runtime/atlas_agent_common.py",
)

class VerificationFailure(Exception):
    pass


def rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def run(args: list[str], *, env: dict[str, str] | None = None) -> None:
    print("+ " + " ".join(args), flush=True)
    proc = subprocess.run(args, cwd=ROOT, text=True, env=env)
    if proc.returncode != 0:
        raise VerificationFailure(f"command failed: {' '.join(args)}")


def run_capture(args: list[str]) -> str:
    proc = subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if proc.returncode != 0:
        raise VerificationFailure((proc.stdout or "").strip() or f"command failed: {' '.join(args)}")
    return proc.stdout


def python_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def check_required_paths() -> None:
    missing = [path for path in REQUIRED_COPY_PATHS if not (ROOT / path).exists()]
    if missing:
        raise VerificationFailure("missing required copy paths:\n- " + "\n- ".join(missing))


def check_json_files() -> None:
    failures: list[str] = []
    for relative in JSON_FILES:
        path = ROOT / relative
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            failures.append(f"{relative}: {exc}")
    if failures:
        raise VerificationFailure("invalid JSON files:\n- " + "\n- ".join(failures))


def check_py_compile() -> None:
    failures: list[str] = []
    for relative in PY_COMPILE_FILES:
        try:
            source = (ROOT / relative).read_text(encoding="utf-8")
            compile(source, str(ROOT / relative), "exec")
        except Exception as exc:
            failures.append(f"{relative}: {exc}")
    if failures:
        raise VerificationFailure("Python compile failures:\n- " + "\n- ".join(failures))


def iter_scanned_files() -> list[Path]:
    files: list[Path] = []
    for relative in SCAN_PATHS:
        path = ROOT / relative
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(
                item
                for item in path.rglob("*")
                if item.is_file()
                and "__pycache__" not in item.parts
                and item.suffix != ".pyc"
            )
    return sorted(files)


def check_forbidden_strings() -> None:
    offenders: list[str] = []
    for path in iter_scanned_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for token in FORBIDDEN_DEFAULT_TOKENS:
            if token in text:
                offenders.append(f"{rel(path)}: forbidden default {token}")
        if "examples/atlasmemory" not in rel(path):
            for token in FORBIDDEN_NEUTRAL_COPY:
                if token in text:
                    offenders.append(f"{rel(path)}: non-neutral runtime copy {token!r}")
    if offenders:
        raise VerificationFailure("forbidden strings found outside allowed examples:\n- " + "\n- ".join(offenders))


def check_runtime_examples_placeholder_safe() -> None:
    expected = (
        "templates/local-automation-runtime/config.env.example",
        "templates/local-automation-runtime/repos.example.txt",
        "templates/local-automation-runtime/projects.example.txt",
        "templates/local-automation-runtime/config/required-checks.example.json",
        "templates/local-automation-runtime/config/local-validation.example.json",
        "templates/local-automation-runtime/config/deployed-validation.example.json",
    )
    failures: list[str] = []
    for relative in expected:
        text = (ROOT / relative).read_text(encoding="utf-8")
        if "OWNER" not in text:
            failures.append(f"{relative}: missing OWNER placeholder")
    if "--apply" in (ROOT / "templates/local-automation-runtime/run_dry_issue.sh").read_text(encoding="utf-8"):
        failures.append("templates/local-automation-runtime/run_dry_issue.sh: dry helper must not pass --apply")
    if failures:
        raise VerificationFailure("runtime examples are not placeholder-safe:\n- " + "\n- ".join(failures))


def check_no_tracked_local_artifacts() -> None:
    if not shutil.which("git"):
        print("skip tracked artifact check: git not found", flush=True)
        return
    output = run_capture(
        [
            "git",
            "ls-files",
            "*__pycache__*",
            "*.pyc",
            ".venv/*",
            ".pytest_cache/*",
            ".ruff_cache/*",
        ]
    ).strip()
    if output:
        raise VerificationFailure("tracked local artifacts found:\n" + output)


def find_ignored_artifacts() -> list[str]:
    offenders: list[str] = []
    for dirname in (".venv", ".pytest_cache", ".ruff_cache"):
        path = ROOT / dirname
        if path.exists():
            offenders.append(f"{dirname}/" if path.is_dir() else dirname)
    for path in ROOT.rglob("__pycache__"):
        if ".git" in path.parts or ".venv" in path.parts:
            continue
        offenders.append(rel(path) + "/")
    for path in ROOT.rglob("*.pyc"):
        if ".git" not in path.parts and ".venv" not in path.parts and "__pycache__" not in path.parts:
            offenders.append(rel(path))
    return sorted(set(offenders))


def check_strict_copy_artifacts() -> None:
    offenders = find_ignored_artifacts()
    if offenders:
        raise VerificationFailure(
            "ignored local artifacts are present; do not raw-copy this tree without excluding them:\n- "
            + "\n- ".join(offenders)
        )


def check_executable_helpers() -> None:
    failures: list[str] = []
    for path in (ROOT / "templates" / "local-automation-runtime").rglob("*.sh"):
        if not os.access(path, os.X_OK):
            failures.append(rel(path))
    for path in (ROOT / "templates" / "local-automation-runtime").glob("atlas-agent-*"):
        if path.is_file() and not os.access(path, os.X_OK):
            failures.append(rel(path))
    for relative in (
        "scripts/enforce_local_ssot.py",
        "scripts/install_harness.py",
        "scripts/verify_harness.py",
        "scripts/verify_repo.py",
    ):
        path = ROOT / relative
        if not os.access(path, os.X_OK):
            failures.append(relative)
    if failures:
        raise VerificationFailure("executable helper files are not executable:\n- " + "\n- ".join(failures))


def check_temp_harness_cli() -> None:
    for harness in ("codex", "gemini", "claude"):
        with tempfile.TemporaryDirectory(prefix=f"atlas-tools-{harness}-") as tmp:
            run([sys.executable, "scripts/install_harness.py", "--harness", harness, "--target", tmp])
            run([sys.executable, "scripts/verify_harness.py", "--target", tmp])


def run_test_suite() -> None:
    env = python_env()
    run([sys.executable, "-m", "unittest", "discover", "tests"], env=env)
    if shutil.which("pytest"):
        run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "skills/plan-to-issues/scripts/test_plan_to_issues.py",
            ],
            env=env,
        )
    else:
        run([sys.executable, "skills/plan-to-issues/scripts/test_plan_to_issues.py"], env=env)
    run([sys.executable, "-m", "unittest", "discover", "templates/local-automation-runtime/tests"], env=env)


def run_git_diff_check() -> None:
    if shutil.which("git"):
        run(["git", "diff", "--check"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Run AtlasMemory Tools release/copy-readiness gates.")
    parser.add_argument("--skip-tests", action="store_true", help="Run static/release gates only.")
    parser.add_argument(
        "--strict-copy",
        action="store_true",
        help="Also fail when ignored local artifacts such as .venv or __pycache__ are present.",
    )
    args = parser.parse_args()

    checks = [
        ("required paths", check_required_paths),
        ("json files", check_json_files),
        ("python compile", check_py_compile),
        ("forbidden strings", check_forbidden_strings),
        ("runtime examples", check_runtime_examples_placeholder_safe),
        ("tracked local artifacts", check_no_tracked_local_artifacts),
        ("executable helpers", check_executable_helpers),
    ]
    if args.strict_copy:
        checks.append(("strict copy artifacts", check_strict_copy_artifacts))

    try:
        for name, check in checks:
            print(f"== {name}", flush=True)
            check()
        if not args.skip_tests:
            print("== test suite", flush=True)
            run_test_suite()
        print("== committed cursor adapter", flush=True)
        run([sys.executable, "scripts/install_harness.py", "--harness", "cursor", "--target", ".", "--check"])
        run([sys.executable, "scripts/verify_harness.py", "--target", "."])
        print("== generated adapter CLIs", flush=True)
        check_temp_harness_cli()
        print("== whitespace", flush=True)
        run_git_diff_check()
    except VerificationFailure as exc:
        print(f"verify_repo failed: {exc}", file=sys.stderr)
        return 1

    print("repo verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
