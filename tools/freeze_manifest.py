#!/usr/bin/env python3
"""Create an immutable SHA-pinned release manifest without syncing Android."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from tools.manifest_lib import (
        make_frozen,
        normalize_tree,
        parse_manifest,
        resolve_projects,
        write_tree_immutable,
    )
    from tools.version_lib import parse_revision, read_version_mk
else:
    from .manifest_lib import (
        make_frozen,
        normalize_tree,
        parse_manifest,
        resolve_projects,
        write_tree_immutable,
    )
    from .version_lib import parse_revision, read_version_mk


def _run(command: list[str], *, cwd: Path) -> None:
    try:
        subprocess.run(command, cwd=cwd, check=True)
    except FileNotFoundError as error:
        raise RuntimeError(f"required command is unavailable: {command[0]}") from error
    except subprocess.CalledProcessError as error:
        raise RuntimeError(f"command failed with exit status {error.returncode}: {' '.join(command)}") from error


def _export_template(
    *,
    repo_root: Path | None,
    template: Path | None,
    manifest_url: str,
    manifest_branch: str,
) -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
    if template is not None:
        if not template.is_file():
            raise ValueError(f"template does not exist: {template}")
        return template, None

    if repo_root is not None:
        output = repo_root / ".uwu-freeze-template.xml"
        _run(["repo", "manifest", "-o", str(output)], cwd=repo_root)
        return output, None

    temporary = tempfile.TemporaryDirectory(prefix="uwu-freeze-")
    root = Path(temporary.name)
    _run(
        [
            "repo",
            "init",
            "-u",
            manifest_url,
            "-b",
            manifest_branch,
            "--git-lfs",
        ],
        cwd=root,
    )
    output = root / "template.xml"
    _run(["repo", "manifest", "-o", str(output)], cwd=root)
    return output, temporary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True, help="revision input, for example 078 or 1200")
    parser.add_argument("--version-file", type=Path, default=Path("version.mk"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--manifest-url",
        default="https://github.com/uwuAOSP/platform_manifests.git",
    )
    parser.add_argument("--manifest-branch", default="uwu-17.0")
    parser.add_argument("--lineage-revision", default="refs/heads/lineage-24.0")
    parser.add_argument("--repo-root", type=Path, help="use an existing repo checkout; do not initialize or sync")
    parser.add_argument("--template", type=Path, help="use an already exported repo manifest")
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--git-timeout", type=int, default=60, help="timeout in seconds for each git ls-remote")
    args = parser.parse_args()

    if args.repo_root is not None and args.template is not None:
        parser.error("--repo-root and --template cannot be used together")
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    if args.git_timeout < 1:
        parser.error("--git-timeout must be positive")

    temporary = None
    try:
        version = read_version_mk(args.version_file)
        revision = parse_revision(args.revision)
        if revision != version.revision:
            raise ValueError(
                f"requested revision {revision} does not match {args.version_file}: "
                f"{version.revision} ({version.text})"
            )

        template, temporary = _export_template(
            repo_root=args.repo_root,
            template=args.template,
            manifest_url=args.manifest_url,
            manifest_branch=args.manifest_branch,
        )
        tree = parse_manifest(template)
        projects = normalize_tree(
            tree,
            manifest_url=args.manifest_url,
            lineage_revision=args.lineage_revision,
        )
        resolve_projects(projects, args.jobs, timeout=args.git_timeout)
        make_frozen(tree, projects)
        write_tree_immutable(tree, args.output)
        print(f"Generated {args.output} for {version.text} ({len(projects)} projects)")
    except (OSError, ValueError, RuntimeError) as error:
        print(f"freeze_manifest.py: {error}", file=sys.stderr)
        return 1
    finally:
        if temporary is not None:
            temporary.cleanup()
        if args.repo_root is not None:
            generated = args.repo_root / ".uwu-freeze-template.xml"
            generated.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
