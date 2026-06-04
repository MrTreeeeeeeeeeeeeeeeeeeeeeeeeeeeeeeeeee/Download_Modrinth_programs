import pytest

from modrinth_collection_downloader.cli import parse_csv, parse_type_selection, type_folder


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
