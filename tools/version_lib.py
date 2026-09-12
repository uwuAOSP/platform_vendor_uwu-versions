#!/usr/bin/env python3
"""Version and manifest helpers shared by release tooling."""

from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse


_ASSIGNMENT = re.compile(
    r"^\s*(UWU_VERSION_MAJOR|UWU_VERSION_QPR|UWU_VERSION_REVISION)\s*:=\s*([0-9]+)\s*$"
)
_SHA1 = re.compile(r"^[0-9a-fA-F]{40}$")
_VERSION = re.compile(r"^([0-9]+)\.([0-9]+)\.([0-9]+)$")


@dataclass(frozen=True)
class Version:
    major: int
    qpr: int
    revision: int

    def __post_init__(self) -> None:
        if self.major < 0:
            raise ValueError("Android major version must not be negative")
        if self.qpr < 0:
            raise ValueError("AOSP QPR must not be negative")
        if self.revision < 1:
            raise ValueError("uwu revision must be at least 1")

    @property
    def revision_display(self) -> str:
        return f"{self.revision:03d}" if self.revision < 1000 else str(self.revision)

    @property
    def text(self) -> str:
        return f"{self.major}.{self.qpr}.{self.revision_display}"

    @property
    def is_milestone(self) -> bool:
        return self.revision % 100 == 0


def parse_revision(value: str) -> int:
    value = value.strip()
    if not value or not value.isdecimal():
        raise ValueError(f"invalid revision: {value!r}")
    revision = int(value, 10)
    if revision < 1:
        raise ValueError("revision must be at least 1")
    return revision


def parse_version(value: str) -> Version:
    match = _VERSION.fullmatch(value.strip())
    if not match:
        raise ValueError(f"invalid version: {value!r}")
    return Version(*(int(part, 10) for part in match.groups()))


def read_version_mk(path: Path) -> Version:
    values: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _ASSIGNMENT.fullmatch(line)
        if match:
            key, value = match.groups()
            if key in values:
                raise ValueError(f"duplicate {key} in {path}")
            values[key] = int(value, 10)

    required = {
        "UWU_VERSION_MAJOR",
        "UWU_VERSION_QPR",
        "UWU_VERSION_REVISION",
    }
    missing = required - values.keys()
    if missing:
        raise ValueError(f"missing {', '.join(sorted(missing))} in {path}")
    return Version(
        values["UWU_VERSION_MAJOR"],
        values["UWU_VERSION_QPR"],
        values["UWU_VERSION_REVISION"],
    )


def is_sha1(value: str) -> bool:
    return bool(_SHA1.fullmatch(value.strip()))


def _manifest_parent(manifest_url: str) -> str:
    parsed = urlparse(manifest_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"manifest URL must be absolute: {manifest_url}")
    base = manifest_url if manifest_url.endswith("/") else f"{manifest_url}/"
    return urljoin(base, "../")


def repository_url(
    fetch: str,
    name: str,
    *,
    manifest_url: str,
) -> str:
    """Resolve a repo remote fetch and project name to a Git URL."""
    if not fetch:
        raise ValueError(f"remote for {name} has an empty fetch")

    if urlparse(fetch).scheme:
        base = fetch
    else:
        base = urljoin(_manifest_parent(manifest_url), fetch)

    if not base.endswith("/"):
        base += "/"
    return urljoin(base, name)


def branch_ref(revision: str) -> str:
    if revision.startswith("refs/"):
        return revision
    return f"refs/heads/{revision}"


def candidate_refs(revision: str) -> Iterable[str]:
    """Return refs to try for a branch-or-tag revision."""
    if revision.startswith("refs/"):
        yield revision
        return
    yield f"refs/heads/{revision}"
    yield f"refs/tags/{revision}"
