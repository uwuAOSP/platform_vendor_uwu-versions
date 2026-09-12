#!/usr/bin/env python3
"""Materialize effective manifest revisions before SHA freezing."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from tools.manifest_lib import normalize_tree, parse_manifest, write_tree_immutable
else:
    from .manifest_lib import normalize_tree, parse_manifest, write_tree_immutable


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--manifest-url",
        default="https://github.com/uwuAOSP/platform_manifests.git",
    )
    parser.add_argument(
        "--lineage-revision",
        default="refs/heads/lineage-24.0",
    )
    args = parser.parse_args()

    try:
        tree = parse_manifest(args.input)
        normalize_tree(
            tree,
            manifest_url=args.manifest_url,
            lineage_revision=args.lineage_revision,
        )
        write_tree_immutable(tree, args.output)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"normalize_manifest.py: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
