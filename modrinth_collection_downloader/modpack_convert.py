from __future__ import annotations

import json
import os
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from .download import DownloadOutcome, download_file, sanitize_filename
from .run_log import RunLog


OVERRIDE_PREFIXES = ("overrides/", "client-overrides/")
SKIPPED_OVERRIDE_PREFIXES = ("server-overrides/",)


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
    strict_metadata: bool = False,
    progress_callback: Callable[[str], None] | None = None,
    run_log: RunLog | None = None,
) -> ModpackConversionResult:
    source = Path(mrpack_path)
    destination = Path(output_zip_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
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
                )

            with tempfile.TemporaryDirectory() as temp_dir_name:
                temp_dir = Path(temp_dir_name)
                with zipfile.ZipFile(part_path, "w", compression=zipfile.ZIP_DEFLATED) as output_zip:
                    _copy_overrides(mrpack, output_zip, missing_files=missing_files, run_log=run_log)
                    _download_manifest_files(
                        manifest,
                        output_zip,
                        temp_dir=temp_dir,
                        downloader=downloader,
                        strict_metadata=strict_metadata,
                        missing_files=missing_files,
                        progress_callback=progress_callback,
                        run_log=run_log,
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
    run_log: RunLog | None,
) -> None:
    for info in mrpack.infolist():
        source_name = info.filename.replace("\\", "/")
        if info.is_dir() or source_name == "modrinth.index.json":
            continue
        if source_name.startswith(SKIPPED_OVERRIDE_PREFIXES):
            continue

        target_name = _override_target_path(source_name)
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


def _override_target_path(source_name: str) -> str | None:
    for prefix in OVERRIDE_PREFIXES:
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
    strict_metadata: bool,
    missing_files: list[MissingModpackFile],
    progress_callback: Callable[[str], None] | None,
    run_log: RunLog | None,
) -> None:
    files = manifest.get("files") or []
    included_files = [file_entry for file_entry in files if _include_manifest_file(file_entry)]
    total = len(included_files)

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


def _include_manifest_file(file_entry: dict[str, Any]) -> bool:
    env = file_entry.get("env")
    if not isinstance(env, dict):
        return True
    return str(env.get("client", "required")).lower() != "unsupported"


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
