import pytest
from rich.console import Console

from modrinth_collection_downloader import cli as cli_module
from modrinth_collection_downloader.cli import (
    PlannedDownload,
    _download_planned,
    parse_csv,
    parse_type_selection,
    type_folder,
)
from modrinth_collection_downloader.download import DestinationPlan


def test_parse_csv_trims_and_skips_empty_values():
    assert parse_csv("mod, shader, ,resourcepack") == ["mod", "shader", "resourcepack"]
    assert parse_csv(None) == []


def test_parse_type_selection_accepts_all_numbers_and_names():
    available = ["mod", "resourcepack", "shader"]

    assert parse_type_selection("all", available) == set(available)
    assert parse_type_selection("1,3", available) == {"mod", "shader"}
    assert parse_type_selection("mod,shader", available) == {"mod", "shader"}


def test_parse_type_selection_rejects_invalid_values():
    with pytest.raises(ValueError):
        parse_type_selection("4", ["mod"])
    with pytest.raises(ValueError):
        parse_type_selection("plugin", ["mod"])


def test_type_folder_uses_known_plural_names():
    assert type_folder("mod") == "mods"
    assert type_folder("minecraft_java_server") == "minecraft_java_servers"
    assert type_folder("unknown") == "unknown"


def test_download_planned_prints_every_download_to_scrollback(monkeypatch, tmp_path):
    output_file = tmp_path / "console.txt"
    console = Console(file=output_file.open("w", encoding="utf-8"), width=160, force_terminal=False)
    planned = [
        PlannedDownload(
            {"title": "First Mod"},
            {"version_number": "1.0.0"},
            {"filename": "first.jar", "url": "https://example.test/first.jar", "hashes": {}, "size": 1},
            DestinationPlan(tmp_path / "first.jar", "new"),
        ),
        PlannedDownload(
            {"title": "Second Mod"},
            {"version_number": "1.0.0"},
            {"filename": "second.jar", "url": "https://example.test/second.jar", "hashes": {}, "size": 1},
            DestinationPlan(tmp_path / "second.jar", "new"),
        ),
    ]

    monkeypatch.setattr(cli_module, "download_file", lambda *args, **kwargs: None)

    failures = _download_planned(console, planned)
    console.file.close()
    text = output_file.read_text(encoding="utf-8")

    assert failures == []
    assert "Downloading 1/2: First Mod -> first.jar" in text
    assert "Downloaded 1/2: First Mod -> first.jar" in text
    assert "Downloading 2/2: Second Mod -> second.jar" in text
    assert "Downloaded 2/2: Second Mod -> second.jar" in text
