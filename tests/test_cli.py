import pytest
from rich.console import Console

from modrinth_collection_downloader import cli as cli_module
from modrinth_collection_downloader.cli import (
    PlannedDownload,
    _build_download_plan,
    _download_planned,
    _get_channels,
    build_parser,
    loader_filter_for_project_type,
    parse_channel_selection,
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


def test_type_folder_uses_exact_project_type_names():
    assert type_folder("mod") == "mod"
    assert type_folder("minecraft_java_server") == "minecraft_java_server"
    assert type_folder("unknown") == "unknown"


def test_loader_filter_for_project_type_uses_type_specific_filters():
    filters = {"mod": ["fabric"], "shader": ["iris"], "plugin": ["paper"]}

    assert loader_filter_for_project_type("mod", filters) == ["fabric"]
    assert loader_filter_for_project_type("modpack", filters) == ["fabric"]
    assert loader_filter_for_project_type("shader", filters) == ["iris"]
    assert loader_filter_for_project_type("plugin", filters) == ["paper"]
    assert loader_filter_for_project_type("resourcepack", filters) == []
    assert loader_filter_for_project_type("datapack", filters) == []


def test_parser_keeps_loaders_as_mod_loader_filter():
    args = build_parser().parse_args(["abc123", "--loaders", "fabric", "--shader-loaders", "iris"])

    assert args.mod_loaders == "fabric"
    assert args.shader_loaders == "iris"


def test_parser_supports_flat_mode():
    args = build_parser().parse_args(["abc123", "--flat"])

    assert args.flat is True
    assert args.group_by_type is False


def test_default_channels_include_beta_for_noninteractive_runs(tmp_path):
    console = Console(file=open(tmp_path / "console.txt", "w", encoding="utf-8"), force_terminal=False)

    channels = _get_channels(None, console, yes=True)
    console.file.close()

    assert channels == ["release", "beta"]


def test_channel_selection_accepts_all():
    assert parse_channel_selection("all") == ["release", "beta", "alpha"]
    assert parse_channel_selection("release,all") == ["release", "beta", "alpha"]


def test_build_download_plan_routes_loader_filters_by_project_type(tmp_path):
    class FakeClient:
        def __init__(self):
            self.calls = []

        def list_project_versions(self, project_id, *, minecraft_versions=None, loaders=None):
            self.calls.append((project_id, list(loaders or [])))
            return [
                {
                    "id": f"{project_id}-version",
                    "status": "listed",
                    "version_type": "release",
                    "date_published": "2026-01-01T00:00:00Z",
                    "game_versions": ["1.20.1"],
                    "loaders": _version_loaders(project_id),
                    "version_number": "1.0.0",
                    "files": [
                        {
                            "filename": f"{project_id}.jar",
                            "url": f"https://example.test/{project_id}.jar",
                            "hashes": {},
                            "primary": True,
                            "size": 1,
                            "file_type": None,
                        }
                    ],
                }
            ]

    def _version_loaders(project_id):
        return {
            "mod-id": ["fabric"],
            "resourcepack-id": ["minecraft"],
            "datapack-id": ["datapack"],
            "shader-id": ["iris"],
            "plugin-id": ["paper"],
        }[project_id]

    projects = [
        {"id": "mod-id", "slug": "mod-slug", "title": "Mod", "project_type": "mod"},
        {
            "id": "resourcepack-id",
            "slug": "resourcepack-slug",
            "title": "Resource Pack",
            "project_type": "resourcepack",
        },
        {"id": "datapack-id", "slug": "datapack-slug", "title": "Data Pack", "project_type": "datapack"},
        {"id": "shader-id", "slug": "shader-slug", "title": "Shader", "project_type": "shader"},
        {"id": "plugin-id", "slug": "plugin-slug", "title": "Plugin", "project_type": "plugin"},
    ]
    client = FakeClient()
    console = Console(file=open(tmp_path / "console.txt", "w", encoding="utf-8"), force_terminal=False)

    planned, already_existing, skipped = _build_download_plan(
        client=client,
        projects=projects,
        output_dir=tmp_path,
        minecraft_versions=["1.20.1"],
        loader_filters={"mod": ["fabric"], "shader": ["iris"], "plugin": ["paper"]},
        channels=["release"],
        group_by_type=False,
        console=console,
    )
    console.file.close()

    assert [(project_id, loaders) for project_id, loaders in client.calls] == [
        ("mod-id", ["fabric"]),
        ("resourcepack-id", []),
        ("datapack-id", []),
        ("shader-id", ["iris"]),
        ("plugin-id", ["paper"]),
    ]
    assert len(planned) == 5
    assert already_existing == []
    assert skipped == []


def test_build_download_plan_uses_exact_type_subfolders(tmp_path):
    class FakeClient:
        def list_project_versions(self, project_id, *, minecraft_versions=None, loaders=None):
            return [
                {
                    "id": f"{project_id}-version",
                    "status": "listed",
                    "version_type": "release",
                    "date_published": "2026-01-01T00:00:00Z",
                    "game_versions": ["1.20.1"],
                    "loaders": ["fabric"],
                    "version_number": "1.0.0",
                    "files": [
                        {
                            "filename": f"{project_id}.jar",
                            "url": f"https://example.test/{project_id}.jar",
                            "hashes": {},
                            "primary": True,
                            "size": 1,
                            "file_type": None,
                        }
                    ],
                }
            ]

    projects = [
        {"id": "mod-id", "slug": "mod-slug", "title": "Mod", "project_type": "mod"},
        {"id": "modpack-id", "slug": "modpack-slug", "title": "Modpack", "project_type": "modpack"},
    ]
    console = Console(file=open(tmp_path / "console.txt", "w", encoding="utf-8"), force_terminal=False)

    planned, already_existing, skipped = _build_download_plan(
        client=FakeClient(),
        projects=projects,
        output_dir=tmp_path,
        minecraft_versions=["1.20.1"],
        loader_filters={"mod": ["fabric"], "shader": [], "plugin": []},
        channels=["release"],
        group_by_type=True,
        console=console,
    )
    console.file.close()

    assert [item.destination.path for item in planned] == [
        tmp_path / "mod" / "mod-id.jar",
        tmp_path / "modpack" / "modpack-id.jar",
    ]
    assert already_existing == []
    assert skipped == []


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
