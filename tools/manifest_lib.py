#!/usr/bin/env python3
"""Manifest expansion and revision resolution helpers."""

from __future__ import annotations

from dataclasses import dataclass
import subprocess
from concurrent.futures import as_completed, ThreadPoolExecutor
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

from .version_lib import candidate_refs, is_sha1, repository_url


SHA_EXEMPT_REMOTES = frozenset({"aosp"})


@dataclass(frozen=True)
class ProjectRevision:
    project: ET.Element
    name: str
    revision: str
    remote: str
    url: str


def parse_manifest(path: Path) -> ET.ElementTree:
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    return ET.parse(path, parser=parser)


def _remote_data(root: ET.Element) -> dict[str, ET.Element]:
    return {
        remote.get("name", ""): remote
        for remote in root.findall("remote")
        if remote.get("name")
    }


def _effective_remote(root: ET.Element, project: ET.Element) -> str:
    default = root.find("default")
    remote = project.get("remote")
    if remote:
        return remote
    if default is not None and default.get("remote"):
        return default.get("remote", "")
    raise ValueError(f"project {project.get('name', '<unnamed>')} has no remote")


def _effective_revision(
    root: ET.Element,
    project: ET.Element,
    remotes: dict[str, ET.Element],
    *,
    lineage_revision: str,
) -> str:
    explicit = project.get("revision")
    if explicit:
        return explicit

    name = project.get("name", "")
    if name.startswith("LineageOS/"):
        return lineage_revision

    remote_name = _effective_remote(root, project)
    remote = remotes.get(remote_name)
    if remote is not None and remote.get("revision"):
        return remote.get("revision", "")

    default = root.find("default")
    if default is not None and default.get("revision"):
        return default.get("revision", "")

    raise ValueError(f"project {name} has no effective revision")


def normalize_tree(
    tree: ET.ElementTree,
    *,
    manifest_url: str,
    lineage_revision: str,
) -> list[ProjectRevision]:
    """Materialize every project's effective revision without resolving SHAs."""
    root = tree.getroot()
    remotes = _remote_data(root)
    projects: list[ProjectRevision] = []

    for project in root.iter("project"):
        name = project.get("name")
        if not name:
            raise ValueError("project is missing name")
        remote_name = _effective_remote(root, project)
        remote = remotes.get(remote_name)
        if remote is None:
            raise ValueError(f"project {name} references unknown remote {remote_name}")
        revision = _effective_revision(
            root,
            project,
            remotes,
            lineage_revision=lineage_revision,
        )
        project.set("revision", revision)
        projects.append(
            ProjectRevision(
                project=project,
                name=name,
                revision=revision,
                remote=remote_name,
                url=repository_url(
                    remote.get("fetch", ""),
                    name,
                    manifest_url=manifest_url,
                ),
            )
        )

    return projects


def resolve_ref(repo_url: str, revision: str, *, timeout: int = 60) -> str:
    """Resolve a revision to a commit SHA using git ls-remote."""
    if is_sha1(revision):
        return revision.lower()

    last_error = ""
    for ref in candidate_refs(revision):
        command = ["git", "ls-remote", "--refs", repo_url, ref]
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            last_error = f"timed out after {timeout}s"
            continue
        if result.returncode != 0:
            last_error = result.stderr.strip() or f"exit status {result.returncode}"
            continue

        matches = []
        for line in result.stdout.splitlines():
            fields = line.split()
            if len(fields) == 2 and fields[1] == ref:
                matches.append(fields[0])
        if len(matches) == 1 and is_sha1(matches[0]):
            return matches[0].lower()
        if len(matches) > 1:
            raise RuntimeError(f"multiple commits returned for {repo_url} {ref}")

    detail = f": {last_error}" if last_error else ""
    raise RuntimeError(f"unable to resolve {repo_url} {revision}{detail}")


def resolve_projects(projects: list[ProjectRevision], jobs: int, *, timeout: int = 60) -> None:
    """Resolve unique repository/revision pairs, reporting and retrying failures."""
    to_resolve = [project for project in projects if project.remote not in SHA_EXEMPT_REMOTES]
    pending = {(project.url, project.revision) for project in to_resolve}
    resolved: dict[tuple[str, str], str] = {}
    attempt = 1

    if any(project.remote in SHA_EXEMPT_REMOTES for project in projects):
        exempt_count = sum(project.remote in SHA_EXEMPT_REMOTES for project in projects)
        print(f"freeze: skipped SHA1 resolution for {exempt_count} AOSP project(s)")

    while pending:
        print(
            f"freeze: resolving {len(pending)} repository/revision pair(s) "
            f"with -j{max(1, jobs)} (attempt {attempt})",
            flush=True,
        )
        failures: dict[tuple[str, str], str] = {}
        ordered_pending = sorted(pending)
        with ThreadPoolExecutor(max_workers=max(1, jobs)) as executor:
            futures = {
                executor.submit(resolve_ref, url, revision, timeout=timeout): (url, revision)
                for url, revision in ordered_pending
            }
            for completed, future in enumerate(as_completed(futures), start=1):
                url, revision = futures[future]
                try:
                    sha = future.result()
                except Exception as error:  # Report all failures before deciding what to retry.
                    failures[(url, revision)] = str(error).replace("\n", " ")
                else:
                    resolved[(url, revision)] = sha
                    print(
                        f"freeze: [{completed}/{len(ordered_pending)}] "
                        f"SHA1 {sha} <- {url} ({revision})",
                        flush=True,
                    )

        if not failures:
            break

        print(f"freeze: {len(failures)} SHA1 resolution(s) failed:", file=sys.stderr)
        for url, revision in sorted(failures):
            print(
                f"freeze:   {url} ({revision}): {failures[(url, revision)]}",
                file=sys.stderr,
            )
        if not _ask_retry():
            raise RuntimeError(f"{len(failures)} SHA1 resolution(s) failed")
        pending = set(failures)
        attempt += 1

    for project in to_resolve:
        project.project.set("revision", resolved[(project.url, project.revision)])


def _ask_retry() -> bool:
    if not sys.stdin.isatty():
        print("freeze: non-interactive input; not retrying", file=sys.stderr)
        return False

    while True:
        try:
            answer = input("freeze: retry failed repositories? [y/N]: ").strip().lower()
        except EOFError:
            print("freeze: no answer received; not retrying", file=sys.stderr)
            return False
        if answer in ("y", "yes"):
            return True
        if answer in ("", "n", "no"):
            return False
        print("freeze: please answer y or n", file=sys.stderr)


def make_frozen(tree: ET.ElementTree, projects: list[ProjectRevision]) -> None:
    """Remove inherited floating revisions after every project is explicit."""
    root = tree.getroot()
    default = root.find("default")
    if default is not None:
        default.attrib.pop("revision", None)
    for remote in root.findall("remote"):
        remote.attrib.pop("revision", None)
    exempt_projects = {
        id(project.project)
        for project in projects
        if project.remote in SHA_EXEMPT_REMOTES
    }
    for project in root.iter("project"):
        revision = project.get("revision", "")
        if not is_sha1(revision) and id(project) not in exempt_projects:
            raise ValueError(
                f"project {project.get('name', '<unnamed>')} is not SHA-pinned: {revision!r}"
            )


def write_tree_immutable(tree: ET.ElementTree, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    import io

    buffer = io.BytesIO()
    tree.write(buffer, encoding="utf-8", xml_declaration=True)
    data = buffer.getvalue().rstrip(b"\n") + b"\n"
    if path.exists():
        existing = path.read_bytes()
        if existing != data:
            raise FileExistsError(f"refusing to overwrite existing artifact {path}")
        return
    path.write_bytes(data)
