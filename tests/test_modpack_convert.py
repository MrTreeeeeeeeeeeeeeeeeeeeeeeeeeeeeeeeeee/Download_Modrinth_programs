import json
import zipfile
from pathlib import Path

import pytest

from modrinth_collection_downloader.download import DownloadOutcome
from modrinth_collection_downloader.modpack_convert import (
    ModpackConversionError,
    convert_mrpack_to_zip,
)


def make_mrpack(path: Path, manifest: dict, entries: dict[str, bytes | str] | None = None) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("modrinth.index.json", json.dumps(manifest))
        for name, content in (entries or {}).items():
            data = content.encode("utf-8") if isinstance(content, str) else content
            archive.writestr(name, data)


def manifest(files: list[dict]) -> dict:
    return {
        "formatVersion": 1,
        "game": "minecraft",
        "versionId": "1.0.0",
        "name": "Example Pack",
        "files": files,
        "dependencies": {"minecraft": "1.20.1"},
    }


def file_entry(path: str, *urls: str, env: dict | None = None) -> dict:
    entry = {
        "path": path,
        "hashes": {},
        "downloads": list(urls),
        "fileSize": 4,
    }
    if env is not None:
        entry["env"] = env
    return entry


def fake_downloader(files: dict[str, bytes], failures: set[str] | None = None):
    failures = failures or set()

    def downloader(url, destination, **kwargs):
        if url in failures or url not in files:
            raise RuntimeError(f"failed {url}")
        Path(destination).write_bytes(files[url])
        return DownloadOutcome()

    return downloader


def zip_names(path: Path) -> set[str]:
    with zipfile.ZipFile(path) as archive:
        return set(archive.namelist())


def zip_content(path: Path, name: str) -> bytes:
    with zipfile.ZipFile(path) as archive:
        return archive.read(name)


def test_convert_mrpack_downloads_files_and_copies_client_overrides(tmp_path):
    mrpack = tmp_path / "pack.mrpack"
    output = tmp_path / "pack.zip"
    make_mrpack(
        mrpack,
        manifest([file_entry("mods/example.jar", "https://example.test/example.jar")]),
        {
            "overrides/config/a.toml": "config",
            "client-overrides/options.txt": "options",
        },
    )

    result = convert_mrpack_to_zip(
        mrpack,
        output,
        downloader=fake_downloader({"https://example.test/example.jar": b"mod!"}),
    )

    assert result.warning == ""
    assert zip_names(output) == {"config/a.toml", "options.txt", "mods/example.jar"}
    assert zip_content(output, "mods/example.jar") == b"mod!"


def test_convert_mrpack_skips_server_overrides(tmp_path):
    mrpack = tmp_path / "pack.mrpack"
    output = tmp_path / "pack.zip"
    make_mrpack(
        mrpack,
        manifest([]),
        {
            "server-overrides/server.properties": "server",
            "overrides/config/client.toml": "client",
        },
    )

    convert_mrpack_to_zip(mrpack, output, downloader=fake_downloader({}))

    assert zip_names(output) == {"config/client.toml"}


def test_convert_mrpack_filters_client_env(tmp_path):
    mrpack = tmp_path / "pack.mrpack"
    output = tmp_path / "pack.zip"
    make_mrpack(
        mrpack,
        manifest(
            [
                file_entry("mods/missing-env.jar", "https://example.test/missing"),
                file_entry("mods/required.jar", "https://example.test/required", env={"client": "required"}),
                file_entry("mods/optional.jar", "https://example.test/optional", env={"client": "optional"}),
                file_entry("mods/server.jar", "https://example.test/server", env={"client": "unsupported"}),
            ]
        ),
    )

    convert_mrpack_to_zip(
        mrpack,
        output,
        downloader=fake_downloader(
            {
                "https://example.test/missing": b"miss",
                "https://example.test/required": b"req!",
                "https://example.test/optional": b"opt!",
                "https://example.test/server": b"nope",
            }
        ),
    )

    assert zip_names(output) == {"mods/missing-env.jar", "mods/required.jar", "mods/optional.jar"}


def test_convert_mrpack_removes_stale_zip_part_files(tmp_path):
    mrpack = tmp_path / "pack.mrpack"
    output = tmp_path / "pack.zip"
    stale_part = tmp_path / "old.zip.part"
    current_part = tmp_path / "pack.zip.part"
    stale_part.write_bytes(b"stale")
    current_part.write_bytes(b"stale")
    make_mrpack(
        mrpack,
        manifest([file_entry("mods/example.jar", "https://example.test/example.jar")]),
    )

    convert_mrpack_to_zip(
        mrpack,
        output,
        downloader=fake_downloader({"https://example.test/example.jar": b"mod!"}),
    )

    assert output.exists()
    assert not stale_part.exists()
    assert not current_part.exists()


def test_convert_mrpack_tries_multiple_download_urls(tmp_path):
    mrpack = tmp_path / "pack.mrpack"
    output = tmp_path / "pack.zip"
    make_mrpack(
        mrpack,
        manifest([file_entry("mods/fallback.jar", "https://example.test/bad", "https://example.test/good")]),
    )

    convert_mrpack_to_zip(
        mrpack,
        output,
        downloader=fake_downloader({"https://example.test/good": b"good"}, failures={"https://example.test/bad"}),
    )

    assert zip_content(output, "mods/fallback.jar") == b"good"


def test_convert_mrpack_creates_partial_zip_with_failed_downloads(tmp_path):
    mrpack = tmp_path / "pack.mrpack"
    output = tmp_path / "pack.zip"
    make_mrpack(
        mrpack,
        manifest([file_entry("mods/missing.jar", "https://example.test/missing")]),
    )

    result = convert_mrpack_to_zip(mrpack, output, downloader=fake_downloader({}))

    assert output.exists()
    assert result.missing_files[0].path == "mods/missing.jar"
    assert "1 missing files" in result.warning
    failed = zip_content(output, "FAILED_DOWNLOADS.txt").decode("utf-8")
    assert "mods/missing.jar" in failed
    assert "https://example.test/missing" in failed


def test_convert_mrpack_rejects_missing_manifest(tmp_path):
    mrpack = tmp_path / "pack.mrpack"
    with zipfile.ZipFile(mrpack, "w") as archive:
        archive.writestr("overrides/config/a.toml", "config")

    with pytest.raises(ModpackConversionError, match="modrinth.index.json"):
        convert_mrpack_to_zip(mrpack, tmp_path / "pack.zip", downloader=fake_downloader({}))


def test_convert_mrpack_records_unsafe_paths(tmp_path):
    mrpack = tmp_path / "pack.mrpack"
    output = tmp_path / "pack.zip"
    make_mrpack(
        mrpack,
        manifest([file_entry("../bad.jar", "https://example.test/bad")]),
        {"overrides/../bad.txt": "bad"},
    )

    result = convert_mrpack_to_zip(mrpack, output, downloader=fake_downloader({}))

    assert len(result.missing_files) == 2
    failed = zip_content(output, "FAILED_DOWNLOADS.txt").decode("utf-8")
    assert "../bad.jar" in failed
    assert "../bad.txt" in failed
