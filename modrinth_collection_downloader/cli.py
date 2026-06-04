from __future__ import annotations

import argparse
import getpass
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from rich.console import Console
from rich.progress import BarColumn, DownloadColumn, Progress, TaskProgressColumn, TextColumn
from rich.prompt import Confirm, Prompt
from rich.table import Table

from .auth import mask_token, normalize_token, resolve_token
from .config import (
    AppConfig,
    forget_token,
    get_config_path,
    load_config,
    remember_download_dir,
    save_config,
    set_token,
)
from .download import (
    DestinationPlan,
    download_file,
    resolve_destination,
    select_version,
    select_version_file,
)
from .modrinth import ApiError, ModrinthClient, parse_collection_id
from .run_log import RunLog, resolve_log_path


MOD_LOADER_TYPES = {"mod", "modpack"}
SHADER_LOADER_TYPES = {"shader"}
PLUGIN_LOADER_TYPES = {"plugin"}
NO_LOADER_FILTER_TYPES = {"resourcepack", "datapack"}
DEFAULT_CHANNELS = ["release", "beta"]


@dataclass
class PlannedDownload:
    project: dict[str, Any]
    version: dict[str, Any]
    file: dict[str, Any]
    destination: DestinationPlan


@dataclass
class SkippedProject:
    project: dict[str, Any]
    reason: str


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="modrinth-collection-downloader",
        description="Download selected project types from a Modrinth collection.",
    )
    parser.add_argument("collection", nargs="?", help="Modrinth collection URL or collection ID.")
    parser.add_argument("-o", "--output", help="Folder to download into.")
    parser.add_argument("--types", help="Comma-separated project types to download.")
    parser.add_argument("--minecraft-version", help="Optional Minecraft version filter.")
    parser.add_argument(
        "--loaders",
        "--mod-loaders",
        dest="mod_loaders",
        help="Comma-separated mod/modpack loader filter, for example fabric,forge,neoforge,quilt.",
    )
    parser.add_argument(
        "--shader-loaders",
        help="Comma-separated shader loader filter, for example iris,optifine,canvas,vanilla.",
    )
    parser.add_argument(
        "--plugin-loaders",
        help="Comma-separated plugin platform filter, for example paper,spigot,purpur,folia,velocity.",
    )
    parser.add_argument(
        "--channels",
        help="Comma-separated release channels. Default: release,beta.",
    )
    parser.add_argument("--token", help="Modrinth Personal Access Token for this run.")
    parser.add_argument("--save-token", action="store_true", help="Save the provided or prompted token.")
    parser.add_argument("--set-token", action="store_true", help="Prompt for, validate, and save a token.")
    parser.add_argument("--forget-token", action="store_true", help="Remove the saved token.")
    parser.add_argument("--no-token", action="store_true", help="Ignore saved and environment tokens.")
    folder_group = parser.add_mutually_exclusive_group()
    folder_group.add_argument(
        "--group-by-type",
        action="store_true",
        help="Deprecated; type subfolders are now used by default.",
    )
    folder_group.add_argument(
        "--flat",
        action="store_true",
        help="Download all files directly into the output folder instead of type subfolders.",
    )
    parser.add_argument("--log-file", help="Log file path, or a folder for the default log filename.")
    parser.add_argument("--dry-run", action="store_true", help="Show planned downloads only.")
    parser.add_argument("--yes", action="store_true", help="Use defaults and do not prompt.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    console = Console()
    run_log = RunLog()
    config_path = get_config_path()
    selected_output_dir: Path | None = None
    type_subfolders = args.group_by_type or not args.flat

    run_log.add(
        "Run started",
        collection=args.collection or "(prompt)",
        output=args.output or "(prompt)",
        types=args.types or "(prompt/all)",
        minecraft_version=args.minecraft_version or "(any)",
        mod_loaders=args.mod_loaders or "(any)",
        shader_loaders=args.shader_loaders or "(any)",
        plugin_loaders=args.plugin_loaders or "(any)",
        channels=args.channels or f"(prompt/default {','.join(DEFAULT_CHANNELS)})",
        dry_run=args.dry_run,
        type_subfolders=type_subfolders,
        flat=args.flat,
        token_argument_provided=bool(args.token),
        save_token=args.save_token,
        set_token=args.set_token,
        forget_token=args.forget_token,
        no_token=args.no_token,
        config_path=config_path,
    )

    def finish(exit_code: int) -> int:
        run_log.add("Run finished", exit_code=exit_code)
        log_path = resolve_log_path(
            requested_log_file=args.log_file,
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
        last_download_dir=config.last_download_dir or "(none)",
        saved_token_present=bool(config.modrinth_token),
    )

    config_changed = False

    if args.forget_token:
        forget_token(config)
        config_changed = True
        console.print("[yellow]Saved Modrinth token removed.[/]")
        run_log.add("Saved token removed")
        if not args.collection and not args.set_token and not args.save_token:
            save_config(config)
            run_log.add("Config saved", reason="forget_token")
            return finish(0)

    if args.set_token:
        token = _get_token_for_saving(args, console)
        if not token:
            run_log.add("Token prompt returned no usable token")
            return finish(2)
        if not _validate_and_report_token(token, console):
            run_log.add("Token validation failed")
            return finish(1)
        if not _save_token_with_warning(config, token, console, yes=args.yes):
            run_log.add("Token save declined")
            return finish(1)
        config_changed = True
        run_log.add("Token validated and saved", token=mask_token(token))
        if not args.collection:
            save_config(config)
            run_log.add("Config saved", reason="set_token")
            return finish(0)

    if args.save_token and not args.set_token:
        token = _get_token_for_saving(args, console)
        if not token:
            run_log.add("Token prompt returned no usable token")
            return finish(2)
        if not _save_token_with_warning(config, token, console, yes=args.yes):
            run_log.add("Token save declined")
            return finish(1)
        config_changed = True
        run_log.add("Token saved", token=mask_token(token))
        if not args.collection:
            save_config(config)
            run_log.add("Config saved", reason="save_token")
            return finish(0)

    resolved_token = resolve_token(
        cli_token=args.token,
        saved_token=config.modrinth_token,
        no_token=args.no_token,
    )

    if config_changed:
        save_config(config)
        run_log.add("Config saved", reason="token changes")

    collection_input = args.collection
    if not collection_input:
        if args.yes:
            console.print("[red]A collection URL or ID is required when --yes is used.[/]")
            run_log.add("Missing collection in non-interactive mode")
            return finish(2)
        collection_input = Prompt.ask("[cyan]Modrinth collection URL or ID[/]")
        run_log.add("Collection entered interactively", collection=collection_input)

    try:
        collection_id = parse_collection_id(collection_input)
    except ValueError as exc:
        console.print(f"[red]Invalid collection:[/] {exc}")
        run_log.add("Collection parse failed", input=collection_input, error=exc)
        return finish(2)
    run_log.add("Collection parsed", collection_id=collection_id)

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
    try:
        selected_types = _select_types(args.types, type_counts, console, yes=args.yes)
    except ValueError as exc:
        console.print(f"[red]Invalid --types value:[/] {exc}")
        run_log.add("Type selection failed", error=exc)
        return finish(2)
    if not selected_types:
        console.print("[yellow]No item types selected.[/]")
        run_log.add("No item types selected")
        return finish(0)
    run_log.add("Item types selected", selected_types=sorted(selected_types))

    selected_projects = [
        project for project in ordered_projects if project.get("project_type", "unknown") in selected_types
    ]

    minecraft_versions = _optional_list(
        args.minecraft_version,
        prompt="Minecraft version filter, blank for any",
        console=console,
        yes=args.yes,
    )
    loader_filters = _get_loader_filters_for_selected_types(args, selected_types, console, yes=args.yes)
    channels = _get_channels(args.channels, console, yes=args.yes)
    run_log.add(
        "Version filters selected",
        minecraft_versions=minecraft_versions,
        mod_loaders=loader_filters.get("mod"),
        shader_loaders=loader_filters.get("shader"),
        plugin_loaders=loader_filters.get("plugin"),
        skipped_loader_types=sorted(NO_LOADER_FILTER_TYPES.intersection(selected_types)),
        channels=channels,
    )

    output_dir = _get_output_dir(args.output, config, console, yes=args.yes)
    if output_dir is None:
        run_log.add("Output folder selection failed")
        return finish(2)
    selected_output_dir = output_dir
    remember_download_dir(config, output_dir)
    save_config(config)
    run_log.add("Download folder selected and saved", output_dir=output_dir, type_subfolders=type_subfolders)
    if type_subfolders:
        console.print("[dim]Files will be placed in type subfolders such as mod, modpack, and resourcepack.[/]")
    else:
        console.print("[dim]Flat mode enabled: files will be placed directly in the output folder.[/]")

    if not args.dry_run:
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
        console=console,
        run_log=run_log,
    )

    _print_plan(console, planned, already_existing, skipped, dry_run=args.dry_run)
    run_log.add(
        "Download plan built",
        planned=len(planned),
        already_existing=len(already_existing),
        skipped=len(skipped),
        dry_run=args.dry_run,
    )
    if args.dry_run:
        console.print("[yellow]Dry run: no files downloaded.[/]")
        run_log.add("Dry run complete; no files downloaded")
        return finish(0)

    failures = _download_planned(console, planned, run_log=run_log)
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

        match = available_lookup.get(item.lower())
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


def _get_loader_filters_for_selected_types(
    args: argparse.Namespace,
    selected_types: set[str],
    console: Console,
    *,
    yes: bool,
) -> dict[str, list[str]]:
    filters = {"mod": [], "shader": [], "plugin": []}

    if selected_types.intersection(MOD_LOADER_TYPES):
        filters["mod"] = _optional_list(
            args.mod_loaders,
            prompt="Mod/modpack loader filter, comma-separated, blank for any",
            console=console,
            yes=yes,
        )
    elif args.mod_loaders:
        console.print("[yellow]Ignoring --loaders because no mods or modpacks are selected.[/]")

    if selected_types.intersection(SHADER_LOADER_TYPES):
        filters["shader"] = _optional_list(
            args.shader_loaders,
            prompt="Shader loader filter, comma-separated, blank for any",
            console=console,
            yes=yes,
        )
    elif args.shader_loaders:
        console.print("[yellow]Ignoring --shader-loaders because no shaders are selected.[/]")

    if selected_types.intersection(PLUGIN_LOADER_TYPES):
        filters["plugin"] = _optional_list(
            args.plugin_loaders,
            prompt="Plugin platform filter, comma-separated, blank for any",
            console=console,
            yes=yes,
        )
    elif args.plugin_loaders:
        console.print("[yellow]Ignoring --plugin-loaders because no plugins are selected.[/]")

    skipped_types = sorted(NO_LOADER_FILTER_TYPES.intersection(selected_types))
    if skipped_types:
        console.print(
            "[dim]Resource pack/datapack versions are not filtered by loader: "
            f"{', '.join(skipped_types)}[/]"
        )

    return filters


def _get_token_for_saving(args: argparse.Namespace, console: Console) -> str | None:
    raw_token = args.token
    if not raw_token:
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
    requested_types: str | None,
    type_counts: Counter[str],
    console: Console,
    *,
    yes: bool,
) -> set[str]:
    available = sorted(type_counts)
    if requested_types:
        return parse_type_selection(requested_types, available)

    if yes:
        return set(available)

    while True:
        raw = Prompt.ask("Select item types by number/name, or all", default="all")
        try:
            return parse_type_selection(raw, available)
        except ValueError as exc:
            console.print(f"[red]{exc}[/]")


def _optional_list(value: str | None, *, prompt: str, console: Console, yes: bool) -> list[str]:
    if value is not None:
        return parse_csv(value)
    if yes:
        return []
    return parse_csv(Prompt.ask(prompt, default=""))


def _get_channels(value: str | None, console: Console, *, yes: bool) -> list[str]:
    if value is not None:
        return parse_csv(value) or list(DEFAULT_CHANNELS)
    if yes:
        return list(DEFAULT_CHANNELS)
    raw_channels = Prompt.ask("Version channels, comma-separated", default=",".join(DEFAULT_CHANNELS))
    return parse_csv(raw_channels) or list(DEFAULT_CHANNELS)


def _get_output_dir(
    requested_output: str | None,
    config: AppConfig,
    console: Console,
    *,
    yes: bool,
) -> Path | None:
    if requested_output:
        return Path(requested_output).expanduser()

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


def _print_type_summary(console: Console, type_counts: Counter[str]) -> None:
    table = Table(title="Collection Item Types")
    table.add_column("#", justify="right")
    table.add_column("Type")
    table.add_column("Projects", justify="right")
    for index, project_type in enumerate(sorted(type_counts), start=1):
        table.add_row(str(index), project_type, str(type_counts[project_type]))
    console.print(table)


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

        target_dir = output_dir
        if group_by_type:
            target_dir = output_dir / type_folder(project.get("project_type", "unknown"))

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
                )
        else:
            planned.append(item)
            if run_log:
                run_log.add(
                    "File planned",
                    title=title,
                    version=version.get("version_number"),
                    filename=file.get("filename"),
                    destination=destination.path,
                    status=destination.status,
                    size=file.get("size"),
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
                download_file(
                    item.file["url"],
                    item.destination.path,
                    hashes=item.file.get("hashes") or {},
                    size=item.file.get("size"),
                    progress_callback=lambda amount, task_id=task_id: progress.update(
                        task_id,
                        advance=amount,
                    ),
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
                progress.console.print(f"[green]Downloaded {index}/{total}:[/] {project_name} -> {filename}")
                if run_log:
                    run_log.add(
                        "Download finished",
                        title=project_name,
                        filename=filename,
                        destination=item.destination.path,
                        index=index,
                        total=total,
                    )

    return failures


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
