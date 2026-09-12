#!/usr/bin/env python3
"""Create immutable archive refs for uwuAOSP-controlled repositories."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from tools.manifest_lib import normalize_tree, parse_manifest
    from tools.version_lib import is_sha1, parse_version
else:
    from .manifest_lib import normalize_tree, parse_manifest
    from .version_lib import is_sha1, parse_version


def _github_repository(repo_url: str) -> tuple[str, str]:
    parsed = urlparse(repo_url)
    if parsed.scheme != "https" or parsed.hostname != "github.com":
        raise ValueError(f"archive API only supports github.com repositories: {repo_url}")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2:
        raise ValueError(f"invalid GitHub repository URL: {repo_url}")
    return parts[0], parts[1].removesuffix(".git")


def _api_url(api_url: str, owner: str, repository: str, suffix: str) -> str:
    return (
        f"{api_url.rstrip('/')}/repos/{quote(owner, safe='')}/"
        f"{quote(repository, safe='')}/{suffix}"
    )


def _api_request(
    method: str,
    url: str,
    *,
    token: str,
    timeout: int,
    payload: dict[str, str] | None = None,
    not_found_ok: bool = False,
) -> dict[str, object] | None:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        url,
        data=body,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "uwuAOSP-release-bot",
            "X-GitHub-Api-Version": "2022-11-28",
            **({"Content-Type": "application/json"} if payload is not None else {}),
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        if error.code == 404 and not_found_ok:
            return None
        try:
            detail = error.read().decode("utf-8")
        except OSError:
            detail = error.reason
        raise RuntimeError(f"GitHub API request failed ({error.code}): {detail}") from error
    except URLError as error:
        raise RuntimeError(f"GitHub API request failed: {error.reason}") from error


def _existing_ref(
    owner: str,
    repository: str,
    ref: str,
    *,
    api_url: str,
    token: str,
    timeout: int,
) -> str | None:
    # GitHub's single-ref endpoint only supports heads and tags. Matching refs
    # also supports custom namespaces such as refs/uwu/archive/.
    lookup = ref.removeprefix("refs/")
    url = _api_url(api_url, owner, repository, f"git/matching-refs/{quote(lookup, safe='/')}")
    response = _api_request(
        "GET",
        url,
        token=token,
        timeout=timeout,
        not_found_ok=True,
    )
    if response is None:
        return None
    if not isinstance(response, list):
        raise RuntimeError(f"unexpected GitHub API response while querying {ref}")
    matches = [item for item in response if item.get("ref") == ref]
    if len(matches) > 1:
        raise RuntimeError(f"multiple commits returned for {owner}/{repository} {ref}")
    if not matches:
        return None
    return str(matches[0]["object"]["sha"]).lower()


def _create_ref(
    owner: str,
    repository: str,
    sha: str,
    ref: str,
    *,
    api_url: str,
    token: str,
    timeout: int,
) -> None:
    _api_request(
        "POST",
        _api_url(api_url, owner, repository, "git/refs"),
        token=token,
        timeout=timeout,
        payload={"ref": ref, "sha": sha},
    )


def _create_or_verify(
    repo_url: str,
    sha: str,
    ref: str,
    *,
    api_url: str,
    token: str,
    timeout: int,
) -> str:
    owner, repository = _github_repository(repo_url)
    existing = _existing_ref(
        owner,
        repository,
        ref,
        api_url=api_url,
        token=token,
        timeout=timeout,
    )
    if existing is not None:
        if existing != sha:
            raise RuntimeError(
                f"archive ref conflict for {repo_url} {ref}: "
                f"existing {existing}, requested {sha}"
            )
        return "skip"

    try:
        _create_ref(
            owner,
            repository,
            sha,
            ref,
            api_url=api_url,
            token=token,
            timeout=timeout,
        )
    except RuntimeError as error:
        # A concurrent creator is safe if it installed the same SHA.
        existing = _existing_ref(
            owner,
            repository,
            ref,
            api_url=api_url,
            token=token,
            timeout=timeout,
        )
        if existing == sha:
            return "skip"
        raise error

    existing = _existing_ref(
        owner,
        repository,
        ref,
        api_url=api_url,
        token=token,
        timeout=timeout,
    )
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
    parser.add_argument("--api-url", default="https://api.github.com")
    parser.add_argument(
        "--controlled-remote",
        action="append",
        dest="controlled_remotes",
        default=None,
        help="remote name allowed to receive archive refs; may be repeated",
    )
    args = parser.parse_args()
    controlled_remotes = set(args.controlled_remotes or ("uwuAOSP",))

    if args.timeout < 1:
        parser.error("--timeout must be positive")
    token = os.environ.get("UWU_RELEASE_TOKEN")
    if not token:
        parser.error("UWU_RELEASE_TOKEN environment variable is required")

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
            action = _create_or_verify(
                repo_url,
                sha,
                archive_ref,
                api_url=args.api_url,
                token=token,
                timeout=args.timeout,
            )
            print(f"archive: {action} {repo_url} {archive_ref} -> {sha}", flush=True)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"archive_refs.py: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
