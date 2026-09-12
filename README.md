# uwuAOSP Versions

This repository owns the canonical uwuAOSP version fields and immutable release
manifests. It does not contain product implementation code.

The version is stored as integer fields in `version.mk`:

```make
UWU_VERSION_MAJOR := 17
UWU_VERSION_QPR := 0
UWU_VERSION_REVISION := 1
```

To freeze the current development manifest without syncing the Android source
tree, use an existing checkout:

```bash
python3 tools/freeze_manifest.py \
    --revision 001 \
    --version-file version.mk \
    --repo-root ../.. \
    --output /tmp/17.0.001.xml
```

The command can instead initialize `platform_manifests` in a temporary
directory. It runs `repo init` and `repo manifest`, but never `repo sync`.

`normalize_manifest.py` is available separately when only effective branch and
tag revisions need to be materialized. Existing output files are immutable:
the tools accept an identical retry and reject different content.

AOSP projects (`remote="aosp"`) intentionally retain their effective tag or
branch revision and are not SHA-resolved. All other remotes are SHA-pinned in
the frozen manifest.

Please note that generating sha1 from local source tree is NEVER allowed.

## GitHub Actions

Run the `Release Snapshot` workflow manually and enter a revision greater than
the revision currently stored in `version.mk`, such as `081` when the current
revision is `080`. The workflow initializes `platform_manifests` in a
temporary directory, never runs `repo sync`, freezes the manifest with 32
workers, creates archive refs for controlled repositories, updates `version.mk`
to the requested revision, and commits the result.

By default, archive refs are created only for projects using the `uwuAOSP`
remote. Other organizations must be explicitly selected with
`--controlled-remote` if they are also controlled by uwuAOSP.
