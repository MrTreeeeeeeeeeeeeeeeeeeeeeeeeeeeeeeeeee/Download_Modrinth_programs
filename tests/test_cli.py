import pytest
from rich.console import Console

from modrinth_collection_downloader import cli as cli_module
from modrinth_collection_downloader.cli import (
    PlannedDownload,
    RuntimeOptions,
    _build_download_plan,
    _download_planned,
    _get_channels,
    _resolve_runtime_options,
    build_parser,
    loader_filter_for_project_type,
    modpack_folder_name,
    modpack_zip_filename,
    parse_channel_selection,
    parse_csv,
    parse_type_selection,
    type_folder,
)
from modrinth_collection_downloader.download import DestinationPlan
from modrinth_collection_downloader.download import DownloadOutcome


def test_parse_csv_trims_and_skips_empty_values():
    assert parse_csv("mod, shader, ,resourcepack") == ["mod", "shader", "resourcepack"]
    assert parse_csv(None) == []


def test_parse_type_selection_accepts_all_numbers_and_names():
    available = ["mod", "modpack", "resourcepack", "shader"]

    assert parse_type_selection("all", available) == set(available)
    assert parse_type_selection("1,4", available) == {"mod", "shader"}
    assert parse_type_selection("mod,shader", available) == {"mod", "shader"}
    assert parse_type_selection("mods,modpacks", available) == {"mod", "modpack"}
    assert parse_type_selection("resource-packs,shaders", available) == {"resourcepack", "shader"}


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


def test_parser_accepts_only_collection_and_yes():
    args = build_parser().parse_args(["abc123", "--yes"])

    assert args.collection == "abc123"
    assert args.yes is True


def test_parser_rejects_old_startup_option_flags():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["abc123", "--dry-run"])

    with pytest.raises(SystemExit):
        build_parser().parse_args(["abc123", "--loaders", "fabric"])


def test_runtime_options_prompt_for_flags_during_interactive_run(monkeypatch, tmp_path):
    console = Console(file=open(tmp_path / "console.txt", "w", encoding="utf-8"), force_terminal=False)
    prompts = []
    answers = iter([True, False, True])

    def fake_confirm(prompt, *, default=False):
        prompts.append((prompt, default))
        return next(answers)

    monkeypatch.setattr(cli_module.Confirm, "ask", staticmethod(fake_confirm))

    options = _resolve_runtime_options(
        {"mod", "modpack"},
        console,
        yes=False,
    )
    console.file.close()

    assert options == RuntimeOptions(
        type_subfolders=False,
        modpack_zip=True,
        strict_metadata=False,
        dry_run=True,
    )
    assert prompts == [
        ("Convert modpack .mrpack files into full .zip archives?", False),
        ("Organize downloads into project-type folders?", True),
        ("Show the download plan only?", False),
    ]


def test_runtime_options_offer_modpack_zip_mode_for_modpacks(monkeypatch, tmp_path):
    console = Console(file=open(tmp_path / "console.txt", "w", encoding="utf-8"), force_terminal=False)
    prompts = []
    answers = iter([False, True, True])

    def fake_confirm(prompt, *, default=False):
        prompts.append((prompt, default))
        return next(answers)

    monkeypatch.setattr(cli_module.Confirm, "ask", staticmethod(fake_confirm))

    options = _resolve_runtime_options(
        {"modpack"},
        console,
        yes=False,
    )
    console.file.close()

    assert options == RuntimeOptions(
        type_subfolders=True,
        modpack_zip=False,
        strict_metadata=False,
        dry_run=True,
    )
    assert prompts == [
        ("Convert modpack .mrpack files into full .zip archives?", False),
        ("Organize downloads into project-type folders?", True),
        ("Show the download plan only?", False),
    ]


def test_runtime_options_use_saved_defaults_for_prompts(monkeypatch, tmp_path):
    console = Console(file=open(tmp_path / "console.txt", "w", encoding="utf-8"), force_terminal=False)
    prompts = []

    def fake_confirm(prompt, *, default=False):
        prompts.append((prompt, default))
        return default

    monkeypatch.setattr(cli_module.Confirm, "ask", staticmethod(fake_confirm))
    options = _resolve_runtime_options(
        {"mod", "modpack"},
        console,
        yes=False,
        saved_options={
            "type_subfolders": False,
            "modpack_zip": True,
            "strict_metadata": True,
            "dry_run": False,
        },
    )
    console.file.close()

    assert options == RuntimeOptions(
        type_subfolders=False,
        modpack_zip=True,
        strict_metadata=True,
        dry_run=False,
    )
    assert prompts == [
        ("Convert modpack .mrpack files into full .zip archives?", True),
        ("Organize downloads into project-type folders?", False),
        ("Show the download plan only?", False),
        ("Use strict metadata verification?", True),
    ]


def test_runtime_options_use_defaults_for_yes_runs(monkeypatch, tmp_path):
    console = Console(file=open(tmp_path / "console.txt", "w", encoding="utf-8"), force_terminal=False)
    monkeypatch.setattr(
        cli_module.Confirm,
        "ask",
        staticmethod(lambda *args, **kwargs: pytest.fail("--yes should not prompt")),
    )

    options = _resolve_runtime_options(
        {"mod", "modpack"},
        console,
        yes=True,
    )
    console.file.close()

    assert options == RuntimeOptions(
        type_subfolders=True,
        modpack_zip=False,
        strict_metadata=False,
        dry_run=False,
    )


def test_runtime_options_use_saved_defaults_for_yes_runs(monkeypatch, tmp_path):
    console = Console(file=open(tmp_path / "console.txt", "w", encoding="utf-8"), force_terminal=False)
    monkeypatch.setattr(
        cli_module.Confirm,
        "ask",
        staticmethod(lambda *args, **kwargs: pytest.fail("--yes should not prompt")),
    )

    options = _resolve_runtime_options(
        {"mod", "modpack"},
        console,
        yes=True,
        saved_options={
            "type_subfolders": False,
            "modpack_zip": True,
            "strict_metadata": True,
            "dry_run": True,
        },
    )
    console.file.close()

    assert options == RuntimeOptions(
        type_subfolders=False,
        modpack_zip=True,
        strict_metadata=True,
        dry_run=True,
    )


def test_runtime_options_saved_defaults_include_first_download_options(monkeypatch, tmp_path):
    console = Console(file=open(tmp_path / "console.txt", "w", encoding="utf-8"), force_terminal=False)
    prompts = []

    def fake_confirm(prompt, *, default=False):
        prompts.append((prompt, default))
        return default

    monkeypatch.setattr(cli_module.Confirm, "ask", staticmethod(fake_confirm))
    options = _resolve_runtime_options(
        {"modpack"},
        console,
        yes=False,
        saved_options={
            "modpack_zip": True,
        },
    )
    console.file.close()

    assert options.modpack_zip is True
    assert prompts[:1] == [("Convert modpack .mrpack files into full .zip archives?", True)]


def test_default_channels_include_beta_for_noninteractive_runs(tmp_path):
    console = Console(file=open(tmp_path / "console.txt", "w", encoding="utf-8"), force_terminal=False)

    channels = _get_channels(console, yes=True)
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
            filename = f"{project_id}.mrpack" if project_id == "modpack-id" else f"{project_id}.jar"
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
                            "filename": filename,
                            "url": f"https://example.test/{filename}",
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
            "modpack-id": ["fabric"],
            "resourcepack-id": ["minecraft"],
            "datapack-id": ["datapack"],
            "shader-id": ["iris"],
            "plugin-id": ["paper"],
        }[project_id]

    projects = [
        {"id": "mod-id", "slug": "mod-slug", "title": "Mod", "project_type": "mod"},
        {"id": "modpack-id", "slug": "modpack-slug", "title": "Modpack", "project_type": "modpack"},
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
        ("modpack-id", ["fabric"]),
        ("resourcepack-id", []),
        ("datapack-id", []),
        ("shader-id", ["iris"]),
        ("plugin-id", ["paper"]),
    ]
    assert len(planned) == 6
    assert tmp_path / "modpack-id.mrpack" in [item.destination.path for item in planned]
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


def test_modpack_zip_helpers_use_safe_names():
    project = {"title": "Bad: Pack", "slug": "bad-pack", "id": "abc"}
    version = {"version_number": "1.0.0", "id": "version-id"}
    file = {"filename": "Bad Pack 1.0.mrpack"}

    assert modpack_folder_name(project) == "Bad_ Pack"
    assert modpack_zip_filename(file, project, version) == "Bad Pack 1.0.zip"


def test_build_download_plan_converts_modpack_destination_to_pack_folder(tmp_path):
    class FakeClient:
        def list_project_versions(self, project_id, *, minecraft_versions=None, loaders=None):
            return [
                {
                    "id": "version-id",
                    "status": "listed",
                    "version_type": "release",
                    "date_published": "2026-01-01T00:00:00Z",
                    "game_versions": ["1.20.1"],
                    "loaders": ["fabric"],
                    "version_number": "1.0.0",
                    "files": [
                        {
                            "filename": "Modpack File.mrpack",
                            "url": "https://example.test/modpack.mrpack",
                            "hashes": {},
                            "primary": True,
                            "size": 1,
                            "file_type": None,
                        }
                    ],
                }
            ]

    console = Console(file=open(tmp_path / "console.txt", "w", encoding="utf-8"), force_terminal=False)

    planned, already_existing, skipped = _build_download_plan(
        client=FakeClient(),
        projects=[{"id": "modpack-id", "slug": "modpack-slug", "title": "Modpack Name", "project_type": "modpack"}],
        output_dir=tmp_path,
        minecraft_versions=["1.20.1"],
        loader_filters={"mod": ["fabric"], "shader": [], "plugin": []},
        channels=["release"],
        group_by_type=False,
        modpack_zip=True,
        console=console,
    )
    console.file.close()

    assert already_existing == []
    assert skipped == []
    assert planned[0].convert_modpack_zip is True
    assert planned[0].destination.path == tmp_path / "modpack" / "Modpack Name" / "Modpack File.zip"


def test_build_download_plan_skips_existing_valid_converted_zip(tmp_path):
    class FakeClient:
        def list_project_versions(self, project_id, *, minecraft_versions=None, loaders=None):
            return [
                {
                    "id": "version-id",
                    "status": "listed",
                    "version_type": "release",
                    "date_published": "2026-01-01T00:00:00Z",
                    "game_versions": ["1.20.1"],
                    "loaders": ["fabric"],
                    "version_number": "1.0.0",
                    "files": [
                        {
                            "filename": "Pack.mrpack",
                            "url": "https://example.test/pack.mrpack",
                            "hashes": {},
                            "primary": True,
                            "size": 1,
                            "file_type": None,
                        }
                    ],
                }
            ]

    destination = tmp_path / "modpack" / "Pack Title" / "Pack.zip"
    destination.parent.mkdir(parents=True)
    import zipfile

    with zipfile.ZipFile(destination, "w") as archive:
        archive.writestr("mods/example.jar", b"mod")

    console = Console(file=open(tmp_path / "console.txt", "w", encoding="utf-8"), force_terminal=False)
    planned, already_existing, skipped = _build_download_plan(
        client=FakeClient(),
        projects=[{"id": "modpack-id", "slug": "pack-title", "title": "Pack Title", "project_type": "modpack"}],
        output_dir=tmp_path,
        minecraft_versions=["1.20.1"],
        loader_filters={"mod": ["fabric"], "shader": [], "plugin": []},
        channels=["release"],
        group_by_type=True,
        modpack_zip=True,
        console=console,
    )
    console.file.close()

    assert planned == []
    assert skipped == []
    assert already_existing[0].destination.path == destination


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


def test_download_planned_converts_modpacks(monkeypatch, tmp_path):
    output_file = tmp_path / "console.txt"
    console = Console(file=output_file.open("w", encoding="utf-8"), width=160, force_terminal=False)
    planned = [
        PlannedDownload(
            {"title": "Pack"},
            {"version_number": "1.0.0"},
            {"filename": "pack.mrpack", "url": "https://example.test/pack.mrpack", "hashes": {}, "size": 1},
            DestinationPlan(tmp_path / "modpack" / "Pack" / "pack.zip", "new"),
            convert_modpack_zip=True,
        )
    ]
    conversions = []

    def fake_download(url, destination, **kwargs):
        destination.write_bytes(b"mrpack")
        return DownloadOutcome()

    def fake_convert(source, destination, **kwargs):
        conversions.append((source, destination))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"zip")

        class Result:
            warning = "partial"
            missing_files = [object()]

        return Result()

    monkeypatch.setattr(cli_module, "download_file", fake_download)
    monkeypatch.setattr(cli_module, "convert_mrpack_to_zip", fake_convert)

    failures = _download_planned(console, planned)
    console.file.close()
    text = output_file.read_text(encoding="utf-8")

    assert failures == []
    assert conversions[0][1] == tmp_path / "modpack" / "Pack" / "pack.zip"
    assert "Converting 1/1: Pack -> pack.zip" in text
    assert "Downloaded 1/1 with warning: Pack -> pack.zip" in text

