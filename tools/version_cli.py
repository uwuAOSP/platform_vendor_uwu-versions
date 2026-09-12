#!/usr/bin/env python3
"""Validate a requested revision and print its canonical uwuAOSP version."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from tools.version_lib import Version, parse_revision, read_version_mk
else:
    from .version_lib import Version, parse_revision, read_version_mk


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version-file", type=Path, default=Path("version.mk"))
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()

    try:
        version = read_version_mk(args.version_file)
        revision = parse_revision(args.revision)
        if revision <= version.revision:
            raise ValueError(
                f"requested revision {revision} must be greater than "
                f"{args.version_file}: {version.revision} ({version.text})"
            )
    except (OSError, ValueError) as error:
        print(f"version_cli.py: {error}", file=sys.stderr)
        return 1

    print(Version(version.major, version.qpr, revision).text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
