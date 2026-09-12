#!/usr/bin/env python3

from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

from tools.manifest_lib import (
    make_frozen,
    normalize_tree,
    repository_url,
    resolve_ref,
    write_tree_immutable,
)
from tools.version_lib import Version, parse_revision, parse_version, read_version_mk


class VersionTest(unittest.TestCase):
    def test_revision_display_is_not_limited_to_three_digits(self) -> None:
        self.assertEqual(Version(17, 0, 1).text, "17.0.001")
        self.assertEqual(Version(17, 0, 37).text, "17.0.037")
        self.assertEqual(Version(17, 0, 100).text, "17.0.100")
        self.assertEqual(Version(17, 1, 1200).text, "17.1.1200")

    def test_revision_input_is_decimal(self) -> None:
        self.assertEqual(parse_revision("078"), 78)
        self.assertEqual(parse_revision("1200"), 1200)

    def test_version_mk_is_split_into_integer_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "version.mk"
            path.write_text(
                "UWU_VERSION_MAJOR := 17\n"
                "UWU_VERSION_QPR := 1\n"
                "UWU_VERSION_REVISION := 1200\n",
                encoding="utf-8",
            )
            self.assertEqual(read_version_mk(path), Version(17, 1, 1200))

    def test_parse_version(self) -> None:
        self.assertEqual(parse_version("17.0.078"), Version(17, 0, 78))


class ManifestTest(unittest.TestCase):
    def test_relative_remote_and_revision_inheritance(self) -> None:
        tree = ET.ElementTree(
            ET.fromstring(
                """<manifest>
                  <remote name="aosp" fetch="https://android.googlesource.com" />
                  <remote name="lineageos" fetch=".." revision="refs/heads/lineage-24.0" />
                  <default remote="aosp" revision="refs/tags/android-17.0.0_r1" />
                  <project name="platform/frameworks/base" />
                  <project name="LineageOS/android_bionic" remote="lineageos" />
                  <project name="LineageOS/android_external_dng_sdk"
                           remote="lineageos" revision="refs/changes/72/490572/1" />
                </manifest>"""
            )
        )
        projects = normalize_tree(
            tree,
            manifest_url="https://github.com/uwuAOSP/platform_manifests.git",
            lineage_revision="refs/heads/lineage-24.0",
        )
        self.assertEqual(projects[0].revision, "refs/tags/android-17.0.0_r1")
        self.assertEqual(projects[1].revision, "refs/heads/lineage-24.0")
        self.assertEqual(projects[1].url, "https://github.com/LineageOS/android_bionic")
        self.assertEqual(projects[2].revision, "refs/changes/72/490572/1")

    def test_absolute_remote_url(self) -> None:
        self.assertEqual(
            repository_url(
                "https://github.com/uwuAOSP",
                "platform_frameworks_base",
                manifest_url="https://github.com/uwuAOSP/platform_manifests.git",
            ),
            "https://github.com/uwuAOSP/platform_frameworks_base",
        )

    @patch("tools.manifest_lib.subprocess.run")
    def test_branch_resolution_uses_heads(self, run) -> None:
        run.return_value = type("Result", (), {
            "returncode": 0,
            "stdout": "a" * 40 + " refs/heads/uwu-17.0\n",
            "stderr": "",
        })()
        self.assertEqual(
            resolve_ref("https://github.com/uwuAOSP/example", "uwu-17.0"),
            "a" * 40,
        )
        self.assertEqual(run.call_args.args[0][-1], "refs/heads/uwu-17.0")

    def test_frozen_tree_rejects_unresolved_revision(self) -> None:
        tree = ET.ElementTree(
            ET.fromstring(
                '<manifest><project name="example" revision="main" /></manifest>'
            )
        )
        with self.assertRaises(ValueError):
            projects = normalize_tree(
                tree,
                manifest_url="https://github.com/uwuAOSP/platform_manifests.git",
                lineage_revision="refs/heads/lineage-24.0",
            )
            make_frozen(tree, projects)

    def test_aosp_revision_is_not_sha_pinned(self) -> None:
        tree = ET.ElementTree(
            ET.fromstring(
                """<manifest>
                  <remote name="aosp" fetch="https://android.googlesource.com" />
                  <default remote="aosp" revision="refs/tags/android-17.0.0_r1" />
                  <project name="platform/frameworks/base" />
                </manifest>"""
            )
        )
        projects = normalize_tree(
            tree,
            manifest_url="https://github.com/uwuAOSP/platform_manifests.git",
            lineage_revision="refs/heads/lineage-24.0",
        )
        make_frozen(tree, projects)
        self.assertEqual(
            tree.getroot().find("project").get("revision"),
            "refs/tags/android-17.0.0_r1",
        )

    @patch("tools.manifest_lib.resolve_ref")
    def test_aosp_projects_are_not_resolved(self, resolve_ref_mock) -> None:
        tree = ET.ElementTree(
            ET.fromstring(
                """<manifest>
                  <remote name="aosp" fetch="https://android.googlesource.com" />
                  <remote name="uwuAOSP" fetch="https://github.com/uwuAOSP" />
                  <default remote="aosp" revision="refs/tags/android-17.0.0_r1" />
                  <project name="platform/frameworks/base" />
                  <project name="platform_vendor_test" remote="uwuAOSP" revision="refs/heads/uwu-17.0" />
                </manifest>"""
            )
        )
        projects = normalize_tree(
            tree,
            manifest_url="https://github.com/uwuAOSP/platform_manifests.git",
            lineage_revision="refs/heads/lineage-24.0",
        )
        resolve_ref_mock.return_value = "b" * 40
        from tools.manifest_lib import resolve_projects

        resolve_projects(projects, jobs=1)
        self.assertEqual(resolve_ref_mock.call_count, 1)
        self.assertEqual(projects[0].project.get("revision"), "refs/tags/android-17.0.0_r1")
        self.assertEqual(projects[1].project.get("revision"), "b" * 40)

    @patch("tools.manifest_lib.sys.stdin.isatty", return_value=True)
    @patch("tools.manifest_lib.input", create=True)
    @patch("tools.manifest_lib.resolve_ref")
    def test_resolution_failures_are_summarized_before_declining_retry(
        self, resolve_ref_mock, input_mock, _isatty_mock
    ) -> None:
        tree = ET.ElementTree(
            ET.fromstring(
                """<manifest>
                  <remote name="uwuAOSP" fetch="https://github.com/uwuAOSP" />
                  <default remote="uwuAOSP" revision="refs/heads/uwu-17.0" />
                  <project name="platform_vendor_test" />
                </manifest>"""
            )
        )
        projects = normalize_tree(
            tree,
            manifest_url="https://github.com/uwuAOSP/platform_manifests.git",
            lineage_revision="refs/heads/lineage-24.0",
        )
        resolve_ref_mock.side_effect = RuntimeError("temporary failure")
        input_mock.return_value = "n"
        from tools.manifest_lib import resolve_projects

        with self.assertRaisesRegex(RuntimeError, "1 SHA1 resolution"):
            resolve_projects(projects, jobs=1)
        self.assertEqual(input_mock.call_count, 1)

    def test_artifact_is_immutable(self) -> None:
        tree = ET.ElementTree(
            ET.fromstring(
                '<manifest><project name="example" revision="' + "a" * 40 + '" /></manifest>'
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "artifact.xml"
            write_tree_immutable(tree, path)
            write_tree_immutable(tree, path)
            path.write_text(path.read_text(encoding="utf-8").replace("example", "changed"), encoding="utf-8")
            with self.assertRaises(FileExistsError):
                write_tree_immutable(tree, path)


if __name__ == "__main__":
    unittest.main()
