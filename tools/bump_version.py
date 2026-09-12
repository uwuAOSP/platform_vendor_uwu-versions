#!/usr/bin/env python3
"""Record the released revision in version.mk after a successful release."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from tools.version_lib import parse_revision, read_version_mk
else:
    from .version_lib import parse_revision, read_version_mk


_REVISION_LINE = re.compile(
    r"^(\s*UWU_VERSION_REVISION\s*:=\s*)[0-9]+(\s*)$",
    re.MULTILINE,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version-file", type=Path, default=Path("version.mk"))
    parser.add_argument("--released-revision", required=True)
    args = parser.parse_args()

    try:
        version = read_version_mk(args.version_file)
        released = parse_revision(args.released_revision)
        if released <= version.revision:
            raise ValueError(
                f"released revision {released} must be greater than "
                f"{args.version_file}: {version.revision} ({version.text})"
            )

        original = args.version_file.read_text(encoding="utf-8")
        updated, replacements = _REVISION_LINE.subn(
            rf"\g<1>{released}\g<2>", original, count=1
        )
        if replacements != 1:
            raise ValueError(f"unable to update UWU_VERSION_REVISION in {args.version_file}")
        args.version_file.write_text(updated, encoding="utf-8")
        print(f"bump_version.py: version.mk is now {version.major}.{version.qpr}.{released:03d}")
    except (OSError, ValueError) as error:
        print(f"bump_version.py: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
