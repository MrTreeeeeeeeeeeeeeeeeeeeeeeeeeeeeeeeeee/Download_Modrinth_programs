import hashlib
import io
import zipfile

from modrinth_collection_downloader.download import (
    DownloadError,
    FileDownloadPlan,
    download_file,
    file_matches,
    perform_downloads,
    resolve_destination,
    sanitize_filename,
    select_version,
    select_version_file,
)


class FakeDownloadResponse:
    def __init__(self, content: bytes, status_code=200):
        self.content = content
        self.status_code = status_code
        self.headers = {"Content-Length": str(len(content))}

    def iter_content(self, chunk_size=1024):
        for index in range(0, len(self.content), chunk_size):
            yield self.content[index : index + chunk_size]

    def close(self):
        pass


class FakeDownloadSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        return self.responses.pop(0)


def make_zip_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("pack.mcmeta", "{}")
    return buffer.getvalue()


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


def test_select_version_matches_requested_version_inside_multi_version_list():
    versions = [
        {
            "id": "fresh-animations",
            "status": "listed",
            "version_type": "beta",
            "date_published": "2026-01-01T00:00:00Z",
            "game_versions": ["1.20", "1.20.1", "1.20.2", "1.21"],
            "loaders": ["minecraft"],
        }
    ]

    selected = select_version(
        versions,
        channels=["release", "beta"],
        minecraft_versions=["1.20.1"],
        loaders=[],
    )

    assert selected["id"] == "fresh-animations"


def test_select_version_matches_minor_series_version():
    versions = [
        {
            "id": "minor-series",
            "status": "listed",
            "version_type": "release",
            "date_published": "2026-01-01T00:00:00Z",
            "game_versions": ["1.20"],
            "loaders": ["minecraft"],
        }
    ]

    selected = select_version(
        versions,
        channels=["release"],
        minecraft_versions=["1.20.1"],
        loaders=[],
    )

    assert selected["id"] == "minor-series"


def test_select_version_matches_wildcard_series_version():
    versions = [
        {
            "id": "wildcard-series",
            "status": "listed",
            "version_type": "release",
            "date_published": "2026-01-01T00:00:00Z",
            "game_versions": ["1.20.x"],
            "loaders": ["minecraft"],
        }
    ]

    selected = select_version(
        versions,
        channels=["release"],
        minecraft_versions=["1.20.1"],
        loaders=[],
    )

    assert selected["id"] == "wildcard-series"


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


def test_download_accepts_valid_archive_when_modrinth_metadata_is_stale(tmp_path):
    content = make_zip_bytes()
    session = FakeDownloadSession(FakeDownloadResponse(content), FakeDownloadResponse(content))
    resets = []
    target = tmp_path / "resourcepack.zip"

    outcome = download_file(
        "https://example.test/resourcepack.zip",
        target,
        hashes={"sha1": "bad"},
        size=len(content) + 10,
        session=session,
        progress_reset_callback=lambda: resets.append(True),
        retries=1,
    )

    assert target.read_bytes() == content
    assert session.calls == 2
    assert resets == [True]
    assert outcome.attempts == 2
    assert "metadata did not match" in outcome.warning


def test_download_strict_metadata_rejects_metadata_mismatch(tmp_path):
    content = make_zip_bytes()
    session = FakeDownloadSession(FakeDownloadResponse(content))

    try:
        download_file(
            "https://example.test/resourcepack.zip",
            tmp_path / "resourcepack.zip",
            hashes={"sha1": "bad"},
            size=len(content) + 10,
            session=session,
            strict_metadata=True,
            retries=0,
        )
    except DownloadError as exc:
        assert "Downloaded size mismatch" in str(exc)
    else:
        raise AssertionError("Expected metadata mismatch to fail in strict mode.")


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
