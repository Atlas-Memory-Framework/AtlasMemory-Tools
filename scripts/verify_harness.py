#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from harnesslib import verify_harness_target


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify generated harness files against canonical sources.")
    parser.add_argument("--target", required=True, help="Target project or home directory.")
    args = parser.parse_args()

    errors = verify_harness_target(Path(args.target).resolve())
    if errors:
        for error in errors:
            print(error)
        return 1
    print("generated harness files verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
