from __future__ import annotations

import json
import os
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

from .download import DownloadOutcome, download_file, sanitize_filename
from .run_log import RunLog


CLIENT_OVERRIDE_PREFIXES = ("overrides/", "client-overrides/")
SERVER_OVERRIDE_PREFIXES = ("overrides/", "server-overrides/")
SERVER_REQUIRED_MARKER = "SERVER_REQUIRED_MODRINTH_PROJECT_FILTER.txt"


class ModpackConversionError(RuntimeError):
    pass


@dataclass(frozen=True)
class MissingModpackFile:
    path: str
    urls: list[str]
    error: str


@dataclass(frozen=True)
class ModpackConversionResult:
    warning: str = ""
    missing_files: list[MissingModpackFile] = field(default_factory=list)


def convert_mrpack_to_zip(
    mrpack_path: Path,
    output_zip_path: Path,
    *,
    downloader: Callable[..., DownloadOutcome] = download_file,
    project_metadata_resolver: Callable[[list[str]], list[dict[str, Any]]] | None = None,
    strict_metadata: bool = False,
    server_required_only: bool = False,
    progress_callback: Callable[[str], None] | None = None,
    run_log: RunLog | None = None,
) -> ModpackConversionResult:
    source = Path(mrpack_path)
    destination = Path(output_zip_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    _remove_stale_part_files(destination, run_log=run_log)
    part_path = destination.with_name(f"{destination.name}.part")
    missing_files: list[MissingModpackFile] = []

    try:
        with zipfile.ZipFile(source) as mrpack:
            manifest = _read_manifest(mrpack)
            if run_log:
                run_log.add(
                    "Modpack conversion started",
                    source=source,
                    destination=destination,
                    name=manifest.get("name"),
                    version_id=manifest.get("versionId"),
                    file_count=len(manifest.get("files") or []),
                    server_required_only=server_required_only,
                )

            with tempfile.TemporaryDirectory() as temp_dir_name:
                temp_dir = Path(temp_dir_name)
                with zipfile.ZipFile(part_path, "w", compression=zipfile.ZIP_DEFLATED) as output_zip:
                    _copy_overrides(
                        mrpack,
                        output_zip,
                        missing_files=missing_files,
                        server_required_only=server_required_only,
                        run_log=run_log,
                    )
                    _download_manifest_files(
                        manifest,
                        output_zip,
                        temp_dir=temp_dir,
                        downloader=downloader,
                        project_metadata_resolver=project_metadata_resolver,
                        strict_metadata=strict_metadata,
                        server_required_only=server_required_only,
                        missing_files=missing_files,
                        progress_callback=progress_callback,
                        run_log=run_log,
                    )
                    if server_required_only:
                        output_zip.writestr(
                            SERVER_REQUIRED_MARKER,
                            (
                                "This zip was converted in server-required mode using referenced "
                                "Modrinth project server-side metadata.\n"
                            ),
                        )
                    if missing_files:
                        output_zip.writestr("FAILED_DOWNLOADS.txt", _format_failed_downloads(missing_files))

        os.replace(part_path, destination)
    except Exception:
        if part_path.exists():
            part_path.unlink()
        raise

    warning = ""
    if missing_files:
        warning = (
            f"Converted modpack zip created with {len(missing_files)} missing files. "
            "See FAILED_DOWNLOADS.txt inside the zip."
        )
        if run_log:
            run_log.add(
                "Modpack conversion warning",
                destination=destination,
                missing_files=len(missing_files),
                warning=warning,
            )

    if run_log:
        run_log.add(
            "Modpack conversion finished",
            destination=destination,
            missing_files=len(missing_files),
            warning=warning or "(none)",
        )
    return ModpackConversionResult(warning=warning, missing_files=missing_files)


def _read_manifest(mrpack: zipfile.ZipFile) -> dict[str, Any]:
    try:
        raw_manifest = mrpack.read("modrinth.index.json")
    except KeyError as exc:
        raise ModpackConversionError("Invalid .mrpack: modrinth.index.json not found.") from exc

    try:
        manifest = json.loads(raw_manifest.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ModpackConversionError("Invalid .mrpack: modrinth.index.json is not valid JSON.") from exc

    if not isinstance(manifest, dict):
        raise ModpackConversionError("Invalid .mrpack: modrinth.index.json must be an object.")
    _require_manifest_value(manifest, "name", str)
    _require_manifest_value(manifest, "versionId", str)
    files = _require_manifest_value(manifest, "files", list)
    for index, file_entry in enumerate(files, start=1):
        _validate_manifest_file(file_entry, index)
    return manifest


def _require_manifest_value(data: dict[str, Any], key: str, expected_type: type) -> Any:
    value = data.get(key)
    if not isinstance(value, expected_type):
        raise ModpackConversionError(f"Invalid .mrpack manifest: {key} must be {expected_type.__name__}.")
    return value


def _validate_manifest_file(file_entry: Any, index: int) -> None:
    if not isinstance(file_entry, dict):
        raise ModpackConversionError(f"Invalid .mrpack manifest: file #{index} must be an object.")
    if not isinstance(file_entry.get("path"), str) or not file_entry["path"]:
        raise ModpackConversionError(f"Invalid .mrpack manifest: file #{index} has no path.")
    if not isinstance(file_entry.get("downloads"), list):
        raise ModpackConversionError(f"Invalid .mrpack manifest: file #{index} has no downloads list.")
    if not isinstance(file_entry.get("hashes"), dict):
        raise ModpackConversionError(f"Invalid .mrpack manifest: file #{index} has no hashes object.")
    if "fileSize" in file_entry and not isinstance(file_entry.get("fileSize"), int):
        raise ModpackConversionError(f"Invalid .mrpack manifest: file #{index} has invalid fileSize.")


def _copy_overrides(
    mrpack: zipfile.ZipFile,
    output_zip: zipfile.ZipFile,
    *,
    missing_files: list[MissingModpackFile],
    server_required_only: bool,
    run_log: RunLog | None,
) -> None:
    for info in mrpack.infolist():
        source_name = info.filename.replace("\\", "/")
        if info.is_dir() or source_name == "modrinth.index.json":
            continue

        target_name = _override_target_path(source_name, server_required_only=server_required_only)
        if target_name is None:
            continue
        if not is_safe_zip_path(target_name):
            missing_files.append(
                MissingModpackFile(target_name, [], f"Unsafe override path: {source_name}")
            )
            if run_log:
                run_log.add("Modpack referenced file failed", path=target_name, error="Unsafe override path")
            continue
        output_zip.writestr(target_name, mrpack.read(info))


def _override_target_path(source_name: str, *, server_required_only: bool) -> str | None:
    prefixes = SERVER_OVERRIDE_PREFIXES if server_required_only else CLIENT_OVERRIDE_PREFIXES
    for prefix in prefixes:
        if source_name.startswith(prefix):
            target = source_name[len(prefix) :]
            return target or None
    return None


def _download_manifest_files(
    manifest: dict[str, Any],
    output_zip: zipfile.ZipFile,
    *,
    temp_dir: Path,
    downloader: Callable[..., DownloadOutcome],
    project_metadata_resolver: Callable[[list[str]], list[dict[str, Any]]] | None,
    strict_metadata: bool,
    server_required_only: bool,
    missing_files: list[MissingModpackFile],
    progress_callback: Callable[[str], None] | None,
    run_log: RunLog | None,
) -> None:
    files = manifest.get("files") or []
    project_metadata = _resolve_manifest_project_metadata(
        files,
        project_metadata_resolver=project_metadata_resolver,
        server_required_only=server_required_only,
        run_log=run_log,
    )
    included_files = [
        file_entry
        for file_entry in files
        if _include_manifest_file(
            file_entry,
            server_required_only=server_required_only,
            project_metadata=project_metadata,
        )
    ]
    total = len(included_files)
    if run_log and server_required_only:
        run_log.add(
            "Modpack server-required file filter applied",
            total_files=len(files),
            included=total,
            excluded=len(files) - total,
            metadata_projects=len(project_metadata),
        )

    for index, file_entry in enumerate(included_files, start=1):
        path = str(file_entry.get("path") or "")
        if not is_safe_zip_path(path):
            missing_files.append(MissingModpackFile(path, list(_downloads(file_entry)), "Unsafe manifest path."))
            if run_log:
                run_log.add("Modpack referenced file failed", path=path, error="Unsafe manifest path.")
            continue

        message = f"modpack file {index}/{total}: {path}"
        if progress_callback:
            progress_callback(message)
        if run_log:
            run_log.add("Modpack referenced file started", path=path, index=index, total=total)

        try:
            temp_file = _download_referenced_file(
                file_entry,
                temp_dir=temp_dir,
                downloader=downloader,
                strict_metadata=strict_metadata,
            )
        except Exception as exc:
            missing_files.append(MissingModpackFile(path, list(_downloads(file_entry)), str(exc)))
            if run_log:
                run_log.add("Modpack referenced file failed", path=path, error=exc, index=index, total=total)
            continue

        output_zip.write(temp_file, path)
        if run_log:
            run_log.add("Modpack referenced file finished", path=path, index=index, total=total)


def _download_referenced_file(
    file_entry: dict[str, Any],
    *,
    temp_dir: Path,
    downloader: Callable[..., DownloadOutcome],
    strict_metadata: bool,
) -> Path:
    downloads = list(_downloads(file_entry))
    if not downloads:
        raise ModpackConversionError("No download URLs listed.")

    path = str(file_entry["path"])
    temp_name = sanitize_filename(path.replace("/", "_"))
    temp_path = temp_dir / temp_name
    errors: list[str] = []
    for url in downloads:
        if not isinstance(url, str) or not url:
            continue
        try:
            downloader(
                url,
                temp_path,
                hashes=file_entry.get("hashes") or {},
                size=file_entry.get("fileSize"),
                strict_metadata=strict_metadata,
            )
        except Exception as exc:
            errors.append(f"{url}: {exc}")
            if temp_path.exists():
                temp_path.unlink()
            continue
        return temp_path
    raise ModpackConversionError("; ".join(errors) if errors else "No usable download URLs listed.")


def _downloads(file_entry: dict[str, Any]) -> tuple[str, ...]:
    downloads = file_entry.get("downloads") or []
    return tuple(str(download) for download in downloads if download)


def _include_manifest_file(
    file_entry: dict[str, Any],
    *,
    server_required_only: bool = False,
    project_metadata: Mapping[str, dict[str, Any]] | None = None,
) -> bool:
    env = file_entry.get("env")
    if server_required_only:
        project_id = _modrinth_project_id(file_entry)
        if project_id:
            project = (project_metadata or {}).get(project_id)
            if project:
                return str(project.get("server_side", "")).lower() == "required"
            return False
        if not isinstance(env, dict):
            return False
        return str(env.get("server", "")).lower() == "required"

    if not isinstance(env, dict):
        return True
    return str(env.get("client", "required")).lower() != "unsupported"


def _resolve_manifest_project_metadata(
    files: list[Any],
    *,
    project_metadata_resolver: Callable[[list[str]], list[dict[str, Any]]] | None,
    server_required_only: bool,
    run_log: RunLog | None,
) -> dict[str, dict[str, Any]]:
    if not server_required_only or project_metadata_resolver is None:
        return {}

    project_ids = sorted(
        {
            project_id
            for file_entry in files
            if isinstance(file_entry, dict)
            for project_id in [_modrinth_project_id(file_entry)]
            if project_id
        }
    )
    if not project_ids:
        return {}

    try:
        projects = project_metadata_resolver(project_ids)
    except Exception as exc:
        if run_log:
            run_log.add(
                "Modpack project metadata lookup failed",
                project_count=len(project_ids),
                error=exc,
            )
        return {}

    metadata = {
        str(project.get("id")): project
        for project in projects
        if isinstance(project, dict) and project.get("id")
    }
    if run_log:
        run_log.add(
            "Modpack project metadata resolved",
            requested=len(project_ids),
            returned=len(metadata),
        )
    return metadata


def _modrinth_project_id(file_entry: dict[str, Any]) -> str | None:
    for download in _downloads(file_entry):
        parsed = urlparse(download)
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 4 and parts[0] == "data" and parts[2] == "versions":
            return parts[1]
    return None


def _remove_stale_part_files(destination: Path, *, run_log: RunLog | None) -> None:
    for part_path in destination.parent.glob("*.zip.part"):
        try:
            part_path.unlink()
        except OSError as exc:
            if run_log:
                run_log.add("Could not remove stale part file", path=part_path, error=exc)
            continue
        if run_log:
            run_log.add("Removed stale part file", path=part_path)


def is_safe_zip_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    if not normalized or normalized.startswith("/"):
        return False
    pure_path = PurePosixPath(normalized)
    if pure_path.is_absolute():
        return False
    if any(part in {"", ".", ".."} for part in pure_path.parts):
        return False
    first = pure_path.parts[0] if pure_path.parts else ""
    if ":" in first:
        return False
    return True


def _format_failed_downloads(missing_files: list[MissingModpackFile]) -> str:
    lines = [
        "The converted modpack zip was created, but these referenced files could not be included.",
        "",
    ]
    for missing in missing_files:
        lines.append(f"Path: {missing.path}")
        if missing.urls:
            lines.append("URLs:")
            lines.extend(f"  - {url}" for url in missing.urls)
        lines.append(f"Error: {missing.error}")
        lines.append("")
    return "\n".join(lines)
