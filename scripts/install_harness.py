#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from harnesslib import install_harness, load_manifest


def main() -> int:
    manifest = load_manifest()
    parser = argparse.ArgumentParser(description="Install generated AtlasMemory Tools files for a harness.")
    parser.add_argument("--harness", required=True, choices=sorted((manifest.get("adapters") or {}).keys()))
    parser.add_argument("--target", required=True, help="Target project or home directory.")
    parser.add_argument("--check", action="store_true", help="Report files that would change without writing.")
    args = parser.parse_args()

    changed = install_harness(args.harness, Path(args.target).resolve(), check=args.check)
    if args.check and changed:
        for path in changed:
            print(f"stale {path}")
        return 1
    for path in changed:
        print(f"wrote {path}")
    if not changed:
        print("harness files are up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
