from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import requests

from .modrinth import DEFAULT_USER_AGENT


SKIPPED_FILE_TYPES = {"sources-jar", "dev-jar", "javadoc-jar", "signature"}
MINECRAFT_VERSION_RE = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+|x|\*))?$", re.IGNORECASE)
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "COM5",
    "COM6",
    "COM7",
    "COM8",
    "COM9",
    "LPT1",
    "LPT2",
    "LPT3",
    "LPT4",
    "LPT5",
    "LPT6",
    "LPT7",
    "LPT8",
    "LPT9",
}


class DownloadError(RuntimeError):
    pass


@dataclass(frozen=True)
class DestinationPlan:
    path: Path
    status: str
    reason: str = ""


@dataclass(frozen=True)
class FileDownloadPlan:
    url: str
    path: Path
    hashes: dict[str, str]
    size: int | None = None


@dataclass(frozen=True)
class FileDownloadResult:
    status: str
    path: Path
    message: str = ""


def select_version(
    versions: Iterable[dict[str, Any]],
    *,
    channels: Iterable[str],
    minecraft_versions: Iterable[str] | None = None,
    loaders: Iterable[str] | None = None,
) -> dict[str, Any] | None:
    allowed_channels = {channel.strip().lower() for channel in channels if channel.strip()}
    wanted_versions = {version.strip() for version in minecraft_versions or [] if version.strip()}
    wanted_loaders = {loader.strip().lower() for loader in loaders or [] if loader.strip()}

    matches: list[dict[str, Any]] = []
    for version in versions:
        if str(version.get("status", "")).lower() != "listed":
            continue

        version_type = str(version.get("version_type", "")).lower()
        if allowed_channels and version_type not in allowed_channels:
            continue

        if wanted_versions:
            actual_versions = [str(value) for value in version.get("game_versions", [])]
            if not minecraft_versions_overlap(wanted_versions, actual_versions):
                continue

        if wanted_loaders:
            actual_loaders = {str(value).lower() for value in version.get("loaders", [])}
            if not wanted_loaders.intersection(actual_loaders):
                continue

        matches.append(version)

    matches.sort(key=lambda item: _parse_modrinth_date(item.get("date_published")), reverse=True)
    return matches[0] if matches else None


def minecraft_versions_overlap(
    wanted_versions: Iterable[str],
    actual_versions: Iterable[str],
) -> bool:
    wanted = [version.strip() for version in wanted_versions if version.strip()]
    actual = [version.strip() for version in actual_versions if version.strip()]
    if not wanted:
        return True
    return any(
        _minecraft_version_matches(wanted_version, actual_version)
        for wanted_version in wanted
        for actual_version in actual
    )


def _minecraft_version_matches(wanted_version: str, actual_version: str) -> bool:
    wanted = wanted_version.strip().lower()
    actual = actual_version.strip().lower()
    if wanted == actual:
        return True

    wanted_parts = _parse_minecraft_version(wanted)
    actual_parts = _parse_minecraft_version(actual)
    if wanted_parts is None or actual_parts is None:
        return False

    wanted_major, wanted_minor, wanted_patch = wanted_parts
    actual_major, actual_minor, actual_patch = actual_parts
    if wanted_major != actual_major or wanted_minor != actual_minor:
        return False

    return (
        wanted_patch is None
        or actual_patch is None
        or wanted_patch in {"x", "*"}
        or actual_patch in {"x", "*"}
    )


def _parse_minecraft_version(version: str) -> tuple[int, int, str | None] | None:
    match = MINECRAFT_VERSION_RE.fullmatch(version)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), match.group(3)


def select_version_file(version: dict[str, Any]) -> dict[str, Any] | None:
    files = version.get("files") or []
    if not files:
        return None

    normal_files = [file for file in files if file.get("file_type") not in SKIPPED_FILE_TYPES]

    for file in normal_files:
        if file.get("primary"):
            return file

    for file in files:
        if file.get("primary"):
            return file

    if normal_files:
        return normal_files[0]
    return files[0]


def sanitize_filename(filename: str) -> str:
    name = Path(filename.replace("\\", "/")).name
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = name.strip().strip(".")
    if not name:
        name = "download"

    stem = Path(name).stem.upper()
    if stem in WINDOWS_RESERVED_NAMES:
        name = f"_{name}"
    return name


def resolve_destination(
    directory: str | Path,
    filename: str,
    *,
    project_slug: str | None = None,
    version_id: str | None = None,
    hashes: dict[str, str] | None = None,
    size: int | None = None,
) -> DestinationPlan:
    target_dir = Path(directory)
    safe_name = sanitize_filename(filename)
    candidate = target_dir / safe_name

    if not candidate.exists():
        return DestinationPlan(candidate, "new")

    if file_matches(candidate, hashes=hashes, size=size):
        return DestinationPlan(candidate, "already_exists", "Existing file matches.")

    suffix = Path(safe_name).suffix
    stem = Path(safe_name).stem
    suffix_parts = [project_slug, version_id]
    suffix_text = "-".join(sanitize_filename(part) for part in suffix_parts if part)
    if not suffix_text:
        suffix_text = "copy"

    base_name = f"{stem}-{suffix_text}"
    candidate = target_dir / f"{base_name}{suffix}"
    counter = 2
    while candidate.exists():
        if file_matches(candidate, hashes=hashes, size=size):
            return DestinationPlan(candidate, "already_exists", "Existing renamed file matches.")
        candidate = target_dir / f"{base_name}-{counter}{suffix}"
        counter += 1

    return DestinationPlan(candidate, "renamed", "Filename already existed with different contents.")


def file_matches(path: str | Path, *, hashes: dict[str, str] | None = None, size: int | None = None) -> bool:
    target = Path(path)
    if not target.exists() or not target.is_file():
        return False

    if size is not None and target.stat().st_size != size:
        return False

    expected_hash = _best_expected_hash(hashes or {})
    if expected_hash is None:
        return size is not None

    algorithm, expected = expected_hash
    return hash_file(target, algorithm).lower() == expected.lower()


def hash_file(path: str | Path, algorithm: str) -> str:
    hasher = hashlib.new(algorithm)
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def download_file(
    url: str,
    destination: str | Path,
    *,
    hashes: dict[str, str] | None = None,
    size: int | None = None,
    session: requests.Session | None = None,
    timeout: int = 60,
    chunk_size: int = 1024 * 1024,
    progress_callback: Callable[[int], None] | None = None,
    user_agent: str = DEFAULT_USER_AGENT,
) -> None:
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    part_path = target.with_name(f"{target.name}.part")
    active_session = requests.Session() if session is None else session
    response = None

    try:
        response = active_session.get(
            url,
            stream=True,
            timeout=timeout,
            headers={"User-Agent": user_agent},
        )
        if response.status_code >= 400:
            raise DownloadError(f"Download failed with HTTP {response.status_code}.")

        hashers = {
            algorithm: hashlib.new(algorithm)
            for algorithm in ("sha512", "sha1")
            if hashes and hashes.get(algorithm)
        }

        bytes_written = 0
        with part_path.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if not chunk:
                    continue
                handle.write(chunk)
                bytes_written += len(chunk)
                for hasher in hashers.values():
                    hasher.update(chunk)
                if progress_callback:
                    progress_callback(len(chunk))

        if size is not None and bytes_written != size:
            raise DownloadError(
                f"Downloaded size mismatch: expected {size} bytes, got {bytes_written} bytes."
            )

        for algorithm, hasher in hashers.items():
            expected = (hashes or {}).get(algorithm)
            if expected and hasher.hexdigest().lower() != expected.lower():
                raise DownloadError(f"{algorithm} hash mismatch for {target.name}.")

        os.replace(part_path, target)
    except Exception:
        if part_path.exists():
            part_path.unlink()
        raise
    finally:
        if response is not None:
            response.close()


def perform_downloads(
    plans: Iterable[FileDownloadPlan],
    *,
    dry_run: bool = False,
    downloader: Callable[..., None] = download_file,
) -> list[FileDownloadResult]:
    results: list[FileDownloadResult] = []
    for plan in plans:
        if dry_run:
            results.append(FileDownloadResult("dry_run", plan.path, "Dry run; no file written."))
            continue

        try:
            downloader(plan.url, plan.path, hashes=plan.hashes, size=plan.size)
        except Exception as exc:
            results.append(FileDownloadResult("failed", plan.path, str(exc)))
        else:
            results.append(FileDownloadResult("downloaded", plan.path))
    return results


def _best_expected_hash(hashes: dict[str, str]) -> tuple[str, str] | None:
    for algorithm in ("sha512", "sha1"):
        expected = hashes.get(algorithm)
        if expected:
            return algorithm, expected
    return None


def _parse_modrinth_date(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
