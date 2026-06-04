import hashlib

from modrinth_collection_downloader.download import (
    FileDownloadPlan,
    file_matches,
    perform_downloads,
    resolve_destination,
    sanitize_filename,
    select_version,
    select_version_file,
)


def test_select_version_uses_newest_matching_release():
    versions = [
        {
            "id": "old",
            "status": "listed",
            "version_type": "release",
            "date_published": "2024-01-01T00:00:00Z",
            "game_versions": ["1.21.1"],
            "loaders": ["fabric"],
        },
        {
            "id": "beta",
            "status": "listed",
            "version_type": "beta",
            "date_published": "2026-01-01T00:00:00Z",
            "game_versions": ["1.21.1"],
            "loaders": ["fabric"],
        },
        {
            "id": "new",
            "status": "listed",
            "version_type": "release",
            "date_published": "2025-01-01T00:00:00Z",
            "game_versions": ["1.21.1"],
            "loaders": ["fabric"],
        },
    ]

    selected = select_version(
        versions,
        channels=["release"],
        minecraft_versions=["1.21.1"],
        loaders=["fabric"],
    )

    assert selected["id"] == "new"


def test_select_version_returns_none_when_filters_do_not_match():
    versions = [
        {
            "id": "forge",
            "status": "listed",
            "version_type": "release",
            "date_published": "2025-01-01T00:00:00Z",
            "game_versions": ["1.21.1"],
            "loaders": ["forge"],
        }
    ]

    assert (
        select_version(
            versions,
            channels=["release"],
            minecraft_versions=["1.21.1"],
            loaders=["fabric"],
        )
        is None
    )


def test_select_version_file_prefers_primary_normal_file():
    version = {
        "files": [
            {"filename": "sources.jar", "primary": True, "file_type": "sources-jar"},
            {"filename": "main.jar", "primary": True, "file_type": None},
            {"filename": "extra.jar", "primary": False, "file_type": None},
        ]
    }

    assert select_version_file(version)["filename"] == "main.jar"


def test_sanitize_filename_removes_path_and_windows_invalid_characters():
    assert sanitize_filename("../bad:name.jar") == "bad_name.jar"
    assert sanitize_filename("CON") == "_CON"


def test_existing_matching_file_is_skipped(tmp_path):
    content = b"hello"
    digest = hashlib.sha1(content).hexdigest()
    target = tmp_path / "mod.jar"
    target.write_bytes(content)

    plan = resolve_destination(
        tmp_path,
        "mod.jar",
        hashes={"sha1": digest},
        size=len(content),
    )

    assert plan.status == "already_exists"
    assert plan.path == target
    assert file_matches(target, hashes={"sha1": digest}, size=len(content))


def test_conflicting_filename_gets_project_and_version_suffix(tmp_path):
    existing = tmp_path / "mod.jar"
    existing.write_bytes(b"old")
    new_digest = hashlib.sha1(b"new").hexdigest()

    plan = resolve_destination(
        tmp_path,
        "mod.jar",
        project_slug="sodium",
        version_id="abc123",
        hashes={"sha1": new_digest},
        size=3,
    )

    assert plan.status == "renamed"
    assert plan.path.name == "mod-sodium-abc123.jar"


def test_dry_run_perform_downloads_does_not_call_downloader(tmp_path):
    calls = []
    plans = [FileDownloadPlan("https://example.test/file.jar", tmp_path / "file.jar", {}, None)]

    results = perform_downloads(
        plans,
        dry_run=True,
        downloader=lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    assert calls == []
    assert results[0].status == "dry_run"
