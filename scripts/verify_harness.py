#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from harnesslib import load_manifest, verify_harness_target


def main() -> int:
    manifest = load_manifest()
    parser = argparse.ArgumentParser(description="Verify generated harness files against canonical sources.")
    parser.add_argument("--target", required=True, help="Target project or home directory.")
    parser.add_argument(
        "--harness",
        action="append",
        choices=sorted((manifest.get("adapters") or {}).keys()),
        help="Harness to verify. May be repeated. Defaults to all installed harnesses.",
    )
    args = parser.parse_args()

    errors = verify_harness_target(Path(args.target).resolve(), tuple(args.harness) if args.harness else None)
    if errors:
        for error in errors:
            print(error)
        return 1
    print("generated harness files verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
