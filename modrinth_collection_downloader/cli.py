from __future__ import annotations

import argparse
import getpass
import sys
import tempfile
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.progress import BarColumn, DownloadColumn, Progress, TaskProgressColumn, TextColumn
from rich.prompt import Confirm, Prompt
from rich.table import Table

from .auth import mask_token, normalize_token, resolve_token
from .config import (
    AppConfig,
    DEFAULT_DOWNLOAD_OPTIONS,
    forget_token,
    get_config_path,
    load_config,
    remember_collection,
    remember_download_dir,
    remember_download_inputs,
    remember_download_options,
    save_config,
    set_token,
)
from .download import (
    DestinationPlan,
    download_file,
    resolve_destination,
    sanitize_filename,
    select_version,
    select_version_file,
)
from .modrinth import ApiError, ModrinthClient, parse_collection_id
from .modpack_convert import convert_mrpack_to_zip
from .run_log import RunLog, resolve_log_path


MOD_LOADER_TYPES = {"mod", "modpack"}
SHADER_LOADER_TYPES = {"shader"}
PLUGIN_LOADER_TYPES = {"plugin"}
NO_LOADER_FILTER_TYPES = {"resourcepack", "datapack"}
ALL_CHANNELS = ["release", "beta", "alpha"]
DEFAULT_CHANNELS = ["release", "beta"]
TYPE_ALIASES = {
    "mods": "mod",
    "modpacks": "modpack",
    "resourcepacks": "resourcepack",
    "resource-packs": "resourcepack",
    "resource_pack": "resourcepack",
    "resource_packs": "resourcepack",
    "datapacks": "datapack",
    "data-packs": "datapack",
    "data_pack": "datapack",
    "data_packs": "datapack",
    "shaders": "shader",
    "plugins": "plugin",
}


@dataclass
class PlannedDownload:
    project: dict[str, Any]
    version: dict[str, Any]
    file: dict[str, Any]
    destination: DestinationPlan
    convert_modpack_zip: bool = False


@dataclass
class SkippedProject:
    project: dict[str, Any]
    reason: str


@dataclass
class RuntimeOptions:
    type_subfolders: bool
    modpack_zip: bool
    strict_metadata: bool
    dry_run: bool

    def to_config(self) -> dict[str, bool]:
        return {
            "type_subfolders": self.type_subfolders,
            "modpack_zip": self.modpack_zip,
            "strict_metadata": self.strict_metadata,
            "dry_run": self.dry_run,
        }


@dataclass
class TokenSelection:
    token: str | None = None
    no_token: bool = False
    config_changed: bool = False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="modrinth-collection-downloader",
        description="Download selected project types from a Modrinth collection.",
    )
    parser.add_argument("collection", nargs="?", help="Modrinth collection URL or collection ID.")
    parser.add_argument("--yes", action="store_true", help="Use saved/default options and do not prompt.")
    return parser


def main(argv: list[str] | None = None) -> int:
    raw_argv = sys.argv[1:] if argv is None else argv
    args = build_parser().parse_args(raw_argv)
    console = Console()
    run_log = RunLog()
    config_path = get_config_path()
    selected_output_dir: Path | None = None
    selected_log_file: str | None = None

    run_log.add(
        "Run started",
        collection=args.collection or "(prompt/saved)",
        yes=args.yes,
        config_path=config_path,
    )

    def finish(exit_code: int) -> int:
        run_log.add("Run finished", exit_code=exit_code)
        log_path = resolve_log_path(
            requested_log_file=selected_log_file,
            output_dir=selected_output_dir,
            config_path=config_path,
            run_log=run_log,
        )
        try:
            written_log = run_log.write(log_path)
        except Exception as exc:
            console.print(f"[red]Could not write log file:[/] {exc}")
            return 1 if exit_code == 0 else exit_code

        console.print(f"[dim]Log written: {written_log}[/]")
        return exit_code

    try:
        config = load_config()
    except Exception as exc:
        console.print(f"[red]Could not load config:[/] {exc}")
        run_log.add("Config load failed", error=exc)
        return finish(1)

    run_log.add(
        "Config loaded",
        last_collection=config.last_collection or "(none)",
        last_download_dir=config.last_download_dir or "(none)",
        last_download_inputs=config.last_download_inputs or "(none)",
        last_download_options=config.last_download_options or "(none)",
        saved_token_present=bool(config.modrinth_token),
    )

    action = _choose_start_action(config, console, yes=args.yes)
    if action == "forget_token":
        forget_token(config)
        console.print("[yellow]Saved Modrinth token removed.[/]")
        run_log.add("Saved token removed")
        save_config(config)
        run_log.add("Config saved", reason="forget_token")
        return finish(0)

    if action == "save_token":
        token = _get_token_for_saving(console)
        if not token:
            run_log.add("Token prompt returned no usable token")
            return finish(2)
        if not _validate_and_report_token(token, console):
            run_log.add("Token validation failed")
            return finish(1)
        if not _save_token_with_warning(config, token, console, yes=args.yes):
            run_log.add("Token save declined")
            return finish(1)
        run_log.add("Token validated and saved", token=mask_token(token))
        save_config(config)
        run_log.add("Config saved", reason="save_token")
        return finish(0)

    token_selection = _get_download_token_selection(config, console, yes=args.yes)
    if token_selection is None:
        run_log.add("Token selection failed")
        return finish(2)
    if token_selection.config_changed:
        save_config(config)
        run_log.add("Config saved", reason="download token selection")

    resolved_token = resolve_token(
        cli_token=token_selection.token,
        saved_token=config.modrinth_token,
        no_token=token_selection.no_token,
    )

    collection_input = _get_collection_input(args.collection, config, console, yes=args.yes)
    if not collection_input:
        console.print("[red]A collection URL or ID is required when --yes is used and no saved collection exists.[/]")
        run_log.add("Missing collection in non-interactive mode")
        return finish(2)

    try:
        collection_id = parse_collection_id(collection_input)
    except ValueError as exc:
        console.print(f"[red]Invalid collection:[/] {exc}")
        run_log.add("Collection parse failed", input=collection_input, error=exc)
        return finish(2)
    run_log.add("Collection parsed", collection_id=collection_id)
    remember_collection(config, collection_input)
    save_config(config)
    run_log.add("Config saved", reason="collection")

    client = ModrinthClient(token=resolved_token.token)
    if resolved_token.token:
        console.print(f"[dim]Using Modrinth token from {resolved_token.source}: {mask_token(resolved_token.token)}[/]")
    run_log.add(
        "Token resolved",
        source=resolved_token.source,
        token=mask_token(resolved_token.token) if resolved_token.token else "(none)",
    )

    try:
        collection = client.get_collection(collection_id)
    except ApiError as exc:
        _print_api_error(console, exc)
        run_log.add("Collection fetch failed", collection_id=collection_id, status=exc.status_code, error=exc.message)
        return finish(1)

    project_ids = list(collection.get("projects") or [])
    console.print(f"[cyan]Collection:[/] {collection.get('name', collection_id)}")
    console.print(f"[cyan]Projects:[/] {len(project_ids)}")
    run_log.add(
        "Collection fetched",
        collection_id=collection_id,
        name=collection.get("name", collection_id),
        status=collection.get("status"),
        project_count=len(project_ids),
    )

    if not project_ids:
        console.print("[yellow]This collection has no projects.[/]")
        run_log.add("Collection has no projects")
        return finish(0)

    try:
        projects = client.get_projects(project_ids)
    except ApiError as exc:
        _print_api_error(console, exc)
        run_log.add("Project metadata fetch failed", status=exc.status_code, error=exc.message)
        return finish(1)

    ordered_projects = _order_projects(project_ids, projects)
    type_counts = Counter(project.get("project_type", "unknown") for project in ordered_projects)
    run_log.add("Project metadata fetched", returned_project_count=len(ordered_projects), type_counts=dict(type_counts))
    _print_type_summary(console, type_counts)
    selected_types = _select_types(
        type_counts,
        console,
        yes=args.yes,
        saved_default=config.last_download_inputs.get("types"),
    )
    if not selected_types:
        console.print("[yellow]No item types selected.[/]")
        run_log.add("No item types selected")
        return finish(0)
    run_log.add("Item types selected", selected_types=sorted(selected_types))

    runtime_options = _resolve_runtime_options(
        selected_types,
        console,
        yes=args.yes,
        saved_options=config.last_download_options,
    )
    type_subfolders = runtime_options.type_subfolders
    remember_download_options(config, runtime_options.to_config())
    save_config(config)
    run_log.add("Config saved", reason="download options")
    run_log.add(
        "Download options selected",
        dry_run=runtime_options.dry_run,
        modpack_zip=runtime_options.modpack_zip,
        strict_metadata=runtime_options.strict_metadata,
        type_subfolders=runtime_options.type_subfolders,
        flat=not runtime_options.type_subfolders,
    )

    selected_projects = [
        project for project in ordered_projects if project.get("project_type", "unknown") in selected_types
    ]

    minecraft_versions = _optional_list(
        prompt="Minecraft version filter, blank for any",
        console=console,
        yes=args.yes,
        saved_default=config.last_download_inputs.get("minecraft_version", ""),
    )
    loader_filters = _get_loader_filters_for_selected_types(
        selected_types,
        console,
        yes=args.yes,
        saved_inputs=config.last_download_inputs,
    )
    channels = _get_channels(
        console,
        yes=args.yes,
        saved_default=config.last_download_inputs.get("channels"),
    )
    run_log.add(
        "Version filters selected",
        minecraft_versions=minecraft_versions,
        mod_loaders=loader_filters.get("mod"),
        shader_loaders=loader_filters.get("shader"),
        plugin_loaders=loader_filters.get("plugin"),
        skipped_loader_types=sorted(NO_LOADER_FILTER_TYPES.intersection(selected_types)),
        channels=channels,
    )

    output_dir = _get_output_dir(config, console, yes=args.yes)
    if output_dir is None:
        run_log.add("Output folder selection failed")
        return finish(2)
    selected_output_dir = output_dir
    selected_log_file = _get_log_file(config, console, yes=args.yes)
    remember_download_dir(config, output_dir)
    remember_download_inputs(
        config,
        {
            "types": _format_type_selection(selected_types, type_counts),
            "minecraft_version": ",".join(minecraft_versions),
            "mod_loaders": ",".join(loader_filters.get("mod", [])),
            "shader_loaders": ",".join(loader_filters.get("shader", [])),
            "plugin_loaders": ",".join(loader_filters.get("plugin", [])),
            "channels": ",".join(channels),
            "log_file": selected_log_file or "",
        },
    )
    save_config(config)
    run_log.add(
        "Download inputs selected and saved",
        output_dir=output_dir,
        log_file=selected_log_file or "(automatic)",
        type_subfolders=type_subfolders,
    )
    if type_subfolders:
        console.print("[dim]Files will be placed in type subfolders such as mod, modpack, and resourcepack.[/]")
    else:
        console.print("[dim]Flat mode enabled: files will be placed directly in the output folder.[/]")

    if not runtime_options.dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)
        run_log.add("Download folder ensured", output_dir=output_dir)

    planned, already_existing, skipped = _build_download_plan(
        client=client,
        projects=selected_projects,
        output_dir=output_dir,
        minecraft_versions=minecraft_versions,
        loader_filters=loader_filters,
        channels=channels,
        group_by_type=type_subfolders,
        modpack_zip=runtime_options.modpack_zip,
        console=console,
        run_log=run_log,
    )

    _print_plan(console, planned, already_existing, skipped, dry_run=runtime_options.dry_run)
    run_log.add(
        "Download plan built",
        planned=len(planned),
        already_existing=len(already_existing),
        skipped=len(skipped),
        dry_run=runtime_options.dry_run,
    )
    if runtime_options.dry_run:
        console.print("[yellow]Dry run: no files downloaded.[/]")
        run_log.add("Dry run complete; no files downloaded")
        return finish(0)

    failures = _download_planned(
        console,
        planned,
        strict_metadata=runtime_options.strict_metadata,
        run_log=run_log,
    )
    _print_summary(console, planned, already_existing, skipped, failures)
    run_log.add(
        "Summary",
        downloaded=len(planned) - len(failures),
        already_existing=len(already_existing),
        skipped=len(skipped),
        failed=len(failures),
    )
    return finish(1 if failures else 0)


def parse_csv(value: str | None) -> list[str]:
    if value is None:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _choose_start_action(config: AppConfig, console: Console, *, yes: bool) -> str:
    if yes:
        return "download"

    default = config.last_download_inputs.get("start_action", "1")
    if default not in {"1", "2"}:
        default = "1"
    table = Table(title="Start")
    table.add_column("#", justify="right")
    table.add_column("Action")
    table.add_row("1", "Download a collection")
    table.add_row("2", "Save or replace Modrinth token")
    table.add_row("3", "Forget saved Modrinth token")
    console.print(table)
    choice = Prompt.ask("Choose an action", choices=["1", "2", "3"], default=default)
    if choice in {"1", "2"}:
        remember_download_inputs(config, {"start_action": choice})
        save_config(config)
    return {"1": "download", "2": "save_token", "3": "forget_token"}[choice]


def _get_collection_input(
    requested_collection: str | None,
    config: AppConfig,
    console: Console,
    *,
    yes: bool,
) -> str | None:
    if requested_collection:
        return requested_collection
    if yes:
        return config.last_collection
    while True:
        raw = Prompt.ask("[cyan]Modrinth collection URL or ID[/]", default=config.last_collection or "")
        if raw.strip():
            return raw
        console.print("[red]Collection cannot be blank.[/]")


def _get_download_token_selection(
    config: AppConfig,
    console: Console,
    *,
    yes: bool,
) -> TokenSelection | None:
    if yes:
        return TokenSelection()

    default = config.last_download_inputs.get("token_option", "1")
    if default not in {"1", "2", "3", "4"}:
        default = "1"
    table = Table(title="Token")
    table.add_column("#", justify="right")
    table.add_column("Option")
    table.add_row("1", "Use saved or environment token")
    table.add_row("2", "Enter token for this run")
    table.add_row("3", "Enter and save token")
    table.add_row("4", "Continue without a token")
    console.print(table)
    choice = Prompt.ask("Choose token option", choices=["1", "2", "3", "4"], default=default)
    remember_download_inputs(config, {"token_option": choice})
    save_config(config)

    if choice == "1":
        return TokenSelection()
    if choice == "4":
        return TokenSelection(no_token=True)

    token = _get_token_for_saving(console)
    if not token:
        return None
    if choice == "2":
        return TokenSelection(token=token)

    if not _validate_and_report_token(token, console):
        return None
    if not _save_token_with_warning(config, token, console, yes=yes):
        return None
    return TokenSelection(token=token, config_changed=True)


def parse_type_selection(value: str, available_types: Iterable[str]) -> set[str]:
    available = list(available_types)
    available_lookup = {item.lower(): item for item in available}
    text = value.strip()
    if not text or text.lower() == "all":
        return set(available)

    selected: set[str] = set()
    for item in parse_csv(text):
        if item.isdigit():
            index = int(item) - 1
            if index < 0 or index >= len(available):
                raise ValueError(f"Type number {item} is out of range.")
            selected.add(available[index])
            continue

        requested = item.lower()
        match = available_lookup.get(requested)
        if not match:
            alias = TYPE_ALIASES.get(requested)
            if alias:
                match = available_lookup.get(alias)
        if not match:
            raise ValueError(f"Unknown type: {item}")
        selected.add(match)
    return selected


def type_folder(project_type: str) -> str:
    return project_type or "unknown"


def loader_filter_for_project_type(project_type: str, loader_filters: dict[str, list[str]]) -> list[str]:
    if project_type in MOD_LOADER_TYPES:
        return loader_filters.get("mod", [])
    if project_type in SHADER_LOADER_TYPES:
        return loader_filters.get("shader", [])
    if project_type in PLUGIN_LOADER_TYPES:
        return loader_filters.get("plugin", [])
    return []


def _resolve_runtime_options(
    selected_types: set[str],
    console: Console,
    *,
    yes: bool,
    saved_options: dict[str, bool] | None = None,
) -> RuntimeOptions:
    type_subfolders = _saved_download_option(saved_options, "type_subfolders")
    modpack_zip = _saved_download_option(saved_options, "modpack_zip")
    strict_metadata = _saved_download_option(saved_options, "strict_metadata")
    dry_run = _saved_download_option(saved_options, "dry_run")

    if yes:
        return RuntimeOptions(
            type_subfolders=type_subfolders,
            modpack_zip=modpack_zip,
            strict_metadata=strict_metadata,
            dry_run=dry_run,
        )

    prompted = False

    def ask(prompt: str, *, default: bool = False) -> bool:
        nonlocal prompted
        if not prompted:
            console.print("[cyan]Download options[/]")
            prompted = True
        return Confirm.ask(prompt, default=default)

    if "modpack" in selected_types:
        modpack_zip = ask("Convert modpack .mrpack files into full .zip archives?", default=modpack_zip)

    type_subfolders = ask("Organize downloads into project-type folders?", default=type_subfolders)

    dry_run = ask("Show the download plan only?", default=dry_run)

    if not dry_run:
        strict_metadata = ask("Use strict metadata verification?", default=strict_metadata)

    return RuntimeOptions(
        type_subfolders=type_subfolders,
        modpack_zip=modpack_zip,
        strict_metadata=strict_metadata,
        dry_run=dry_run,
    )


def _saved_download_option(saved_options: dict[str, bool] | None, name: str) -> bool:
    if saved_options:
        value = saved_options.get(name)
        if isinstance(value, bool):
            return value
    return DEFAULT_DOWNLOAD_OPTIONS[name]


def _get_loader_filters_for_selected_types(
    selected_types: set[str],
    console: Console,
    *,
    yes: bool,
    saved_inputs: dict[str, str] | None = None,
) -> dict[str, list[str]]:
    filters = {"mod": [], "shader": [], "plugin": []}
    saved_inputs = saved_inputs or {}

    if selected_types.intersection(MOD_LOADER_TYPES):
        filters["mod"] = _optional_list(
            prompt="Mod/modpack loader filter, comma-separated, blank for any",
            console=console,
            yes=yes,
            saved_default=saved_inputs.get("mod_loaders", ""),
        )

    if selected_types.intersection(SHADER_LOADER_TYPES):
        filters["shader"] = _optional_list(
            prompt="Shader loader filter, comma-separated, blank for any",
            console=console,
            yes=yes,
            saved_default=saved_inputs.get("shader_loaders", ""),
        )

    if selected_types.intersection(PLUGIN_LOADER_TYPES):
        filters["plugin"] = _optional_list(
            prompt="Plugin platform filter, comma-separated, blank for any",
            console=console,
            yes=yes,
            saved_default=saved_inputs.get("plugin_loaders", ""),
        )

    skipped_types = sorted(NO_LOADER_FILTER_TYPES.intersection(selected_types))
    if skipped_types:
        console.print(
            "[dim]Resource pack/datapack versions are not filtered by loader: "
            f"{', '.join(skipped_types)}[/]"
        )

    return filters


def _get_token_for_saving(console: Console) -> str | None:
    raw_token = getpass.getpass("Modrinth Personal Access Token: ")
    token = normalize_token(raw_token)
    if not token:
        console.print("[red]Token cannot be blank.[/]")
        return None
    return token


def _validate_and_report_token(token: str, console: Console) -> bool:
    client = ModrinthClient(token=token)
    try:
        user = client.get_current_user()
    except ApiError as exc:
        _print_api_error(console, exc)
        return False
    username = user.get("username") or user.get("name") or "current user"
    console.print(f"[green]Token validated for {username}.[/]")
    return True


def _save_token_with_warning(config: AppConfig, token: str, console: Console, *, yes: bool) -> bool:
    console.print("[yellow]Warning: the token will be saved in plain text in the app config file.[/]")
    console.print(f"[dim]Config path: {get_config_path()}[/]")
    if not yes and not Confirm.ask("Save token anyway?", default=False):
        console.print("[yellow]Token was not saved.[/]")
        return False
    set_token(config, token)
    console.print(f"[green]Saved token:[/] {mask_token(token)}")
    return True


def _print_api_error(console: Console, exc: ApiError) -> None:
    if exc.status_code:
        console.print(f"[red]Modrinth API error {exc.status_code}:[/] {exc.message}")
    else:
        console.print(f"[red]Modrinth API error:[/] {exc.message}")


def _order_projects(project_ids: list[str], projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {project.get("id"): project for project in projects}
    return [by_id[project_id] for project_id in project_ids if project_id in by_id]


def _select_types(
    type_counts: Counter[str],
    console: Console,
    *,
    yes: bool,
    saved_default: str | None = None,
) -> set[str]:
    available = sorted(type_counts)
    default = _type_selection_default(saved_default, available)

    if yes:
        return parse_type_selection(default, available)

    while True:
        raw = Prompt.ask("Select item types by number/name, or all", default=default)
        try:
            return parse_type_selection(raw, available)
        except ValueError as exc:
            console.print(f"[red]{exc}[/]")


def _type_selection_default(saved_default: str | None, available: list[str]) -> str:
    if saved_default:
        try:
            parse_type_selection(saved_default, available)
        except ValueError:
            pass
        else:
            return saved_default
    return "all"


def _format_type_selection(selected_types: set[str], type_counts: Counter[str]) -> str:
    available = set(type_counts)
    if selected_types == available:
        return "all"
    return ",".join(sorted(selected_types))


def _optional_list(
    *,
    prompt: str,
    console: Console,
    yes: bool,
    saved_default: str = "",
) -> list[str]:
    if yes:
        return parse_csv(saved_default)
    return parse_csv(Prompt.ask(prompt, default=saved_default))


def _get_channels(
    console: Console,
    *,
    yes: bool,
    saved_default: str | None = None,
) -> list[str]:
    default = saved_default or ",".join(DEFAULT_CHANNELS)
    if yes:
        return parse_channel_selection(default)
    raw_channels = Prompt.ask("Release channels to include (release,beta,alpha, or all)", default=default)
    return parse_channel_selection(raw_channels)


def parse_channel_selection(value: str | None) -> list[str]:
    channels = parse_csv(value)
    if not channels:
        return list(DEFAULT_CHANNELS)
    if any(channel.lower() == "all" for channel in channels):
        return list(ALL_CHANNELS)
    return channels


def _get_output_dir(
    config: AppConfig,
    console: Console,
    *,
    yes: bool,
) -> Path | None:
    if yes:
        if config.last_download_dir:
            return Path(config.last_download_dir).expanduser()
        console.print("[red]An output folder is required when --yes is used and no saved folder exists.[/]")
        return None

    default = config.last_download_dir or ""
    prompt = "Download folder"
    while True:
        raw = Prompt.ask(prompt, default=default)
        if raw.strip():
            return Path(raw).expanduser()
        console.print("[red]Download folder cannot be blank.[/]")


def _get_log_file(config: AppConfig, console: Console, *, yes: bool) -> str | None:
    default = config.last_download_inputs.get("log_file", "")
    if yes:
        return default or None
    raw = Prompt.ask("Log file or folder, blank for automatic", default=default)
    return raw.strip() or None


def _print_type_summary(console: Console, type_counts: Counter[str]) -> None:
    table = Table(title="Collection Item Types")
    table.add_column("#", justify="right")
    table.add_column("Type")
    table.add_column("Projects", justify="right")
    for index, project_type in enumerate(sorted(type_counts), start=1):
        table.add_row(str(index), project_type, str(type_counts[project_type]))
    console.print(table)


def modpack_folder_name(project: dict[str, Any]) -> str:
    return sanitize_filename(str(project.get("title") or project.get("slug") or project.get("id") or "modpack"))


def modpack_zip_filename(
    file: dict[str, Any],
    project: dict[str, Any],
    version: dict[str, Any],
) -> str:
    fallback = f"{project.get('slug') or project.get('id') or 'modpack'}-{version.get('version_number') or version.get('id') or 'version'}.mrpack"
    filename = sanitize_filename(str(file.get("filename") or fallback))
    path = Path(filename)
    if path.suffix.lower() == ".mrpack":
        zip_name = f"{path.stem}.zip"
    elif path.suffix.lower() == ".zip":
        zip_name = filename
    else:
        zip_name = f"{filename}.zip"

    return zip_name


def resolve_modpack_zip_destination(
    pack_dir: Path,
    filename: str,
    *,
    project_slug: str | None,
    version_id: str | None,
) -> DestinationPlan:
    candidate = pack_dir / sanitize_filename(filename)
    if candidate.exists() and _is_valid_zip_file(candidate):
        return DestinationPlan(candidate, "already_exists", "Existing converted zip is valid.")
    return resolve_destination(
        pack_dir,
        filename,
        project_slug=project_slug,
        version_id=version_id,
        hashes={},
        size=None,
    )


def _is_valid_zip_file(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            return bool(archive.infolist()) and archive.testzip() is None
    except (OSError, zipfile.BadZipFile):
        return False


def _build_download_plan(
    *,
    client: ModrinthClient,
    projects: list[dict[str, Any]],
    output_dir: Path,
    minecraft_versions: list[str],
    loader_filters: dict[str, list[str]],
    channels: list[str],
    group_by_type: bool,
    console: Console,
    modpack_zip: bool = False,
    run_log: RunLog | None = None,
) -> tuple[list[PlannedDownload], list[PlannedDownload], list[SkippedProject]]:
    planned: list[PlannedDownload] = []
    already_existing: list[PlannedDownload] = []
    skipped: list[SkippedProject] = []

    for index, project in enumerate(projects, start=1):
        title = project.get("title") or project.get("slug") or project.get("id")
        console.print(f"[dim]Resolving {index}/{len(projects)}: {title}[/]")
        if run_log:
            run_log.add(
                "Resolving project",
                index=index,
                total=len(projects),
                project_id=project.get("id"),
                slug=project.get("slug"),
                title=title,
                project_type=project.get("project_type"),
            )
        try:
            project_loaders = loader_filter_for_project_type(
                project.get("project_type", "unknown"),
                loader_filters,
            )
            versions = client.list_project_versions(
                project["id"],
                minecraft_versions=minecraft_versions,
                loaders=project_loaders,
            )
        except ApiError as exc:
            skipped.append(SkippedProject(project, exc.message))
            if run_log:
                run_log.add("Project skipped", title=title, reason=exc.message)
            continue

        version = select_version(
            versions,
            channels=channels,
            minecraft_versions=minecraft_versions,
            loaders=project_loaders,
        )
        if version is None:
            skipped.append(SkippedProject(project, "No matching listed version."))
            if run_log:
                run_log.add("Project skipped", title=title, reason="No matching listed version.")
            continue

        file = select_version_file(version)
        if file is None:
            skipped.append(SkippedProject(project, "Matching version has no downloadable files."))
            if run_log:
                run_log.add("Project skipped", title=title, reason="Matching version has no downloadable files.")
            continue

        project_type = project.get("project_type", "unknown")
        if modpack_zip and project_type == "modpack":
            pack_dir = output_dir / "modpack" / modpack_folder_name(project)
            destination = resolve_modpack_zip_destination(
                pack_dir,
                modpack_zip_filename(file, project, version),
                project_slug=project.get("slug"),
                version_id=version.get("id"),
            )
            item = PlannedDownload(
                project,
                version,
                file,
                destination,
                convert_modpack_zip=True,
            )
        else:
            target_dir = output_dir
            if group_by_type:
                target_dir = output_dir / type_folder(project_type)

            destination = resolve_destination(
                target_dir,
                file.get("filename") or f"{project.get('slug', project['id'])}.jar",
                project_slug=project.get("slug"),
                version_id=version.get("id"),
                hashes=file.get("hashes") or {},
                size=file.get("size"),
            )
            item = PlannedDownload(project, version, file, destination)
        if destination.status == "already_exists":
            already_existing.append(item)
            if run_log:
                run_log.add(
                    "File already exists",
                    title=title,
                    version=version.get("version_number"),
                    filename=file.get("filename"),
                    destination=destination.path,
                    reason=destination.reason,
                    converted_modpack=item.convert_modpack_zip,
                )
        else:
            planned.append(item)
            if run_log:
                run_log.add(
                    "Converted modpack planned" if item.convert_modpack_zip else "File planned",
                    title=title,
                    version=version.get("version_number"),
                    filename=file.get("filename"),
                    destination=destination.path,
                    status=destination.status,
                    size=file.get("size"),
                    pack_folder=destination.path.parent if item.convert_modpack_zip else "(none)",
                    converted_modpack=item.convert_modpack_zip,
                )

    return planned, already_existing, skipped


def _print_plan(
    console: Console,
    planned: list[PlannedDownload],
    already_existing: list[PlannedDownload],
    skipped: list[SkippedProject],
    *,
    dry_run: bool,
) -> None:
    table = Table(title="Download Plan" if dry_run else "Ready To Download")
    table.add_column("Project")
    table.add_column("Type")
    table.add_column("Version")
    table.add_column("Status")
    table.add_column("File")

    for item in planned:
        table.add_row(
            item.project.get("title") or item.project.get("slug") or item.project.get("id"),
            item.project.get("project_type", ""),
            item.version.get("version_number", item.version.get("id", "")),
            item.destination.status,
            str(item.destination.path),
        )
    for item in already_existing:
        table.add_row(
            item.project.get("title") or item.project.get("slug") or item.project.get("id"),
            item.project.get("project_type", ""),
            item.version.get("version_number", item.version.get("id", "")),
            "already exists",
            str(item.destination.path),
        )
    console.print(table)

    if skipped:
        skip_table = Table(title="Skipped Projects")
        skip_table.add_column("Project")
        skip_table.add_column("Reason")
        for item in skipped:
            skip_table.add_row(
                item.project.get("title") or item.project.get("slug") or item.project.get("id"),
                item.reason,
            )
        console.print(skip_table)


def _download_planned(
    console: Console,
    planned: list[PlannedDownload],
    *,
    strict_metadata: bool = False,
    run_log: RunLog | None = None,
) -> list[tuple[PlannedDownload, str]]:
    failures: list[tuple[PlannedDownload, str]] = []
    if not planned:
        console.print("[yellow]No new files to download.[/]")
        if run_log:
            run_log.add("No new files to download")
        return failures

    progress = Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        DownloadColumn(),
        console=console,
        transient=True,
    )
    with progress:
        total = len(planned)
        for index, item in enumerate(planned, start=1):
            filename = item.file.get("filename") or item.destination.path.name
            project_name = item.project.get("title") or item.project.get("slug") or item.project.get("id")
            if item.convert_modpack_zip:
                error = _download_converted_modpack(
                    progress,
                    item,
                    project_name=project_name,
                    source_filename=filename,
                    index=index,
                    total=total,
                    strict_metadata=strict_metadata,
                    run_log=run_log,
                )
                if error:
                    failures.append((item, error))
                continue

            progress.console.print(f"[cyan]Downloading {index}/{total}:[/] {project_name} -> {filename}")
            task_id = progress.add_task(filename, total=item.file.get("size"))
            if run_log:
                run_log.add(
                    "Download started",
                    title=project_name,
                    filename=filename,
                    destination=item.destination.path,
                    size=item.file.get("size"),
                    index=index,
                    total=total,
                )
            try:
                outcome = download_file(
                    item.file["url"],
                    item.destination.path,
                    hashes=item.file.get("hashes") or {},
                    size=item.file.get("size"),
                    progress_callback=lambda amount, task_id=task_id: progress.update(
                        task_id,
                        advance=amount,
                    ),
                    progress_reset_callback=lambda task_id=task_id: progress.update(task_id, completed=0),
                    strict_metadata=strict_metadata,
                )
            except Exception as exc:
                failures.append((item, str(exc)))
                progress.update(task_id, description=f"{filename} failed")
                progress.remove_task(task_id)
                progress.console.print(f"[red]Failed {index}/{total}:[/] {project_name} -> {filename}: {exc}")
                if run_log:
                    run_log.add(
                        "Download failed",
                        title=project_name,
                        filename=filename,
                        destination=item.destination.path,
                        error=exc,
                        index=index,
                        total=total,
                    )
            else:
                progress.update(task_id, completed=item.file.get("size") or 1)
                progress.remove_task(task_id)
                warning = getattr(outcome, "warning", "")
                attempts = getattr(outcome, "attempts", 1)
                if warning:
                    progress.console.print(
                        f"[yellow]Downloaded {index}/{total} with warning:[/] {project_name} -> {filename}"
                    )
                    progress.console.print(f"[yellow]{warning}[/]")
                else:
                    progress.console.print(f"[green]Downloaded {index}/{total}:[/] {project_name} -> {filename}")
                if run_log:
                    run_log.add(
                        "Download finished",
                        title=project_name,
                        filename=filename,
                        destination=item.destination.path,
                        warning=warning or "(none)",
                        attempts=attempts,
                        index=index,
                        total=total,
                    )

    return failures


def _download_converted_modpack(
    progress: Progress,
    item: PlannedDownload,
    *,
    project_name: str,
    source_filename: str,
    index: int,
    total: int,
    strict_metadata: bool,
    run_log: RunLog | None,
) -> str | None:
    progress.console.print(f"[cyan]Downloading {index}/{total}:[/] {project_name} -> {source_filename}")
    task_id = progress.add_task(source_filename, total=item.file.get("size"))
    task_removed = False
    try:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            source_path = temp_dir / sanitize_filename(source_filename)
            if run_log:
                run_log.add(
                    "Modpack source download started",
                    title=project_name,
                    filename=source_filename,
                    source=source_path,
                    destination=item.destination.path,
                    size=item.file.get("size"),
                    index=index,
                    total=total,
                )
            source_outcome = download_file(
                item.file["url"],
                source_path,
                hashes=item.file.get("hashes") or {},
                size=item.file.get("size"),
                progress_callback=lambda amount, task_id=task_id: progress.update(task_id, advance=amount),
                progress_reset_callback=lambda task_id=task_id: progress.update(task_id, completed=0),
                strict_metadata=strict_metadata,
            )
            progress.update(task_id, completed=item.file.get("size") or 1)
            progress.remove_task(task_id)
            task_removed = True
            if run_log:
                run_log.add(
                    "Modpack source download finished",
                    title=project_name,
                    filename=source_filename,
                    source=source_path,
                    destination=item.destination.path,
                    warning=source_outcome.warning or "(none)",
                    attempts=source_outcome.attempts,
                    index=index,
                    total=total,
                )

            progress.console.print(
                f"[cyan]Converting {index}/{total}:[/] {project_name} -> {item.destination.path.name}"
            )
            result = convert_mrpack_to_zip(
                source_path,
                item.destination.path,
                strict_metadata=strict_metadata,
                progress_callback=lambda message: progress.console.print(f"[dim]  {message}[/]"),
                run_log=run_log,
            )
    except Exception as exc:
        if not task_removed:
            progress.remove_task(task_id)
        progress.console.print(
            f"[red]Failed {index}/{total}:[/] {project_name} -> {item.destination.path.name}: {exc}"
        )
        if run_log:
            run_log.add(
                "Download failed",
                title=project_name,
                filename=item.destination.path.name,
                destination=item.destination.path,
                error=exc,
                converted_modpack=True,
                index=index,
                total=total,
            )
        return str(exc)

    warning_parts = [warning for warning in (source_outcome.warning, result.warning) if warning]
    warning = " ".join(warning_parts)
    if warning:
        progress.console.print(
            f"[yellow]Downloaded {index}/{total} with warning:[/] {project_name} -> {item.destination.path.name}"
        )
        progress.console.print(f"[yellow]{warning}[/]")
    else:
        progress.console.print(
            f"[green]Downloaded {index}/{total}:[/] {project_name} -> {item.destination.path.name}"
        )
    if run_log:
        run_log.add(
            "Download finished",
            title=project_name,
            filename=item.destination.path.name,
            destination=item.destination.path,
            warning=warning or "(none)",
            attempts=getattr(source_outcome, "attempts", 1),
            converted_modpack=True,
            missing_files=len(result.missing_files),
            index=index,
            total=total,
        )
    return None


def _print_summary(
    console: Console,
    planned: list[PlannedDownload],
    already_existing: list[PlannedDownload],
    skipped: list[SkippedProject],
    failures: list[tuple[PlannedDownload, str]],
) -> None:
    downloaded = len(planned) - len(failures)
    summary = Table(title="Summary")
    summary.add_column("Result")
    summary.add_column("Count", justify="right")
    summary.add_row("Downloaded", str(downloaded))
    summary.add_row("Already existed", str(len(already_existing)))
    summary.add_row("Skipped", str(len(skipped)))
    summary.add_row("Failed", str(len(failures)))
    console.print(summary)

    if failures:
        failed = Table(title="Failures")
        failed.add_column("Project")
        failed.add_column("Reason")
        for item, reason in failures:
            failed.add_row(item.project.get("title") or item.project.get("id"), reason)
        console.print(failed)


if __name__ == "__main__":
    raise SystemExit(main())
