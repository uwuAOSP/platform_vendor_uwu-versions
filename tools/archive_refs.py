#!/usr/bin/env python3
"""Create immutable archive refs for uwuAOSP-controlled repositories."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from tools.manifest_lib import normalize_tree, parse_manifest
    from tools.version_lib import is_sha1, parse_version
else:
    from .manifest_lib import normalize_tree, parse_manifest
    from .version_lib import is_sha1, parse_version


def _run(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"command timed out after {timeout}s: {' '.join(command)}") from error


def _existing_ref(repo_url: str, ref: str, *, timeout: int) -> str | None:
    result = _run(["git", "ls-remote", "--refs", repo_url, ref], timeout=timeout)
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit status {result.returncode}"
        raise RuntimeError(f"unable to query {repo_url} {ref}: {detail}")
    matches = [
        fields[0]
        for line in result.stdout.splitlines()
        if len(fields := line.split()) == 2 and fields[1] == ref
    ]
    if len(matches) > 1:
        raise RuntimeError(f"multiple commits returned for {repo_url} {ref}")
    return matches[0].lower() if matches else None


def _create_or_verify(repo_url: str, sha: str, ref: str, *, timeout: int) -> str:
    existing = _existing_ref(repo_url, ref, timeout=timeout)
    if existing is not None:
        if existing != sha:
            raise RuntimeError(
                f"archive ref conflict for {repo_url} {ref}: "
                f"existing {existing}, requested {sha}"
            )
        return "skip"

    result = _run(["git", "push", repo_url, f"{sha}:{ref}"], timeout=timeout)
    if result.returncode != 0:
        # A concurrent creator is safe if it installed the same SHA.
        existing = _existing_ref(repo_url, ref, timeout=timeout)
        if existing == sha:
            return "skip"
        detail = result.stderr.strip() or f"exit status {result.returncode}"
        raise RuntimeError(f"unable to create archive ref for {repo_url}: {detail}")

    existing = _existing_ref(repo_url, ref, timeout=timeout)
    if existing != sha:
        raise RuntimeError(
            f"archive ref verification failed for {repo_url} {ref}: {existing or 'missing'}"
        )
    return "create"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument(
        "--manifest-url",
        default="https://github.com/uwuAOSP/platform_manifests.git",
    )
    parser.add_argument("--lineage-revision", default="refs/heads/lineage-24.0")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument(
        "--controlled-remote",
        action="append",
        dest="controlled_remotes",
        default=None,
        help="remote name allowed to receive archive refs; may be repeated",
    )
    args = parser.parse_args()
    controlled_remotes = set(args.controlled_remotes or ("uwuAOSP", "UwUniverse"))

    if args.timeout < 1:
        parser.error("--timeout must be positive")

    try:
        version = parse_version(args.version)
        if version.text != args.version:
            raise ValueError(f"version is not canonical: {args.version}")
        projects = normalize_tree(
            parse_manifest(args.manifest),
            manifest_url=args.manifest_url,
            lineage_revision=args.lineage_revision,
        )
        repositories: dict[str, set[str]] = {}
        for project in projects:
            if project.remote not in controlled_remotes:
                continue
            if not is_sha1(project.revision):
                raise ValueError(
                    f"controlled project {project.name} is not SHA-pinned: {project.revision!r}"
                )
            repositories.setdefault(project.url, set()).add(project.revision.lower())

        archive_ref = f"refs/uwu/archive/{version.text}"
        for repo_url in sorted(repositories):
            shas = repositories[repo_url]
            if len(shas) != 1:
                raise ValueError(
                    f"controlled repository has multiple release SHAs: {repo_url}"
                )
            sha = next(iter(shas))
            action = _create_or_verify(repo_url, sha, archive_ref, timeout=args.timeout)
            print(f"archive: {action} {repo_url} {archive_ref} -> {sha}", flush=True)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"archive_refs.py: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
