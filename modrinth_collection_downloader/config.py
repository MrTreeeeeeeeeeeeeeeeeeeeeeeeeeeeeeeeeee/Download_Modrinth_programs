from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


CONFIG_ENV_VAR = "MODRINTH_COLLECTION_DOWNLOADER_CONFIG"
DEFAULT_CONFIG_PATH = Path.home() / ".modrinth_collection_downloader" / "config.json"
DEFAULT_DOWNLOAD_OPTIONS = {
    "server_required": False,
    "type_subfolders": True,
    "modpack_zip": False,
    "strict_metadata": False,
    "dry_run": False,
}
DOWNLOAD_INPUT_KEYS = {
    "start_action",
    "token_option",
    "types",
    "minecraft_version",
    "mod_loaders",
    "shader_loaders",
    "plugin_loaders",
    "channels",
    "log_file",
}


@dataclass
class AppConfig:
    last_collection: str | None = None
    last_download_dir: str | None = None
    modrinth_token: str | None = None
    last_download_inputs: dict[str, str] = field(default_factory=dict)
    last_download_options: dict[str, bool] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        extra = {
            key: value
            for key, value in data.items()
            if key not in {
                "last_collection",
                "last_download_dir",
                "modrinth_token",
                "last_download_inputs",
                "last_download_options",
            }
        }
        return cls(
            last_collection=data.get("last_collection") or None,
            last_download_dir=data.get("last_download_dir") or None,
            modrinth_token=data.get("modrinth_token") or None,
            last_download_inputs=_normalize_download_inputs(data.get("last_download_inputs")),
            last_download_options=_normalize_download_options(data.get("last_download_options")),
            extra=extra,
        )

    def to_dict(self) -> dict[str, Any]:
        data = dict(self.extra)
        if self.last_collection:
            data["last_collection"] = self.last_collection
        if self.last_download_dir:
            data["last_download_dir"] = self.last_download_dir
        if self.modrinth_token:
            data["modrinth_token"] = self.modrinth_token
        if self.last_download_inputs:
            data["last_download_inputs"] = _normalize_download_inputs(self.last_download_inputs)
        if self.last_download_options:
            data["last_download_options"] = _normalize_download_options(self.last_download_options)
        return data


def get_config_path() -> Path:
    override = os.environ.get(CONFIG_ENV_VAR)
    if override:
        return Path(override).expanduser()
    return DEFAULT_CONFIG_PATH


def load_config(path: Path | None = None) -> AppConfig:
    config_path = get_config_path() if path is None else path
    if not config_path.exists():
        return AppConfig()

    with config_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, dict):
        return AppConfig()
    return AppConfig.from_dict(data)


def save_config(config: AppConfig, path: Path | None = None) -> None:
    config_path = get_config_path() if path is None else path
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("w", encoding="utf-8") as handle:
        json.dump(config.to_dict(), handle, indent=2)
        handle.write("\n")

    try:
        os.chmod(config_path, 0o600)
    except OSError:
        pass


def remember_download_dir(config: AppConfig, directory: str | Path) -> None:
    config.last_download_dir = str(Path(directory).expanduser().resolve())


def remember_collection(config: AppConfig, collection: str) -> None:
    config.last_collection = collection.strip() or None


def remember_download_inputs(config: AppConfig, inputs: Mapping[str, str]) -> None:
    merged = dict(config.last_download_inputs)
    merged.update(_normalize_download_inputs(inputs))
    config.last_download_inputs = _normalize_download_inputs(merged)


def remember_download_options(config: AppConfig, options: Mapping[str, bool]) -> None:
    config.last_download_options = _normalize_download_options(options)


def set_token(config: AppConfig, token: str) -> None:
    config.modrinth_token = token


def forget_token(config: AppConfig) -> None:
    config.modrinth_token = None


def _normalize_download_options(value: Any) -> dict[str, bool]:
    if not isinstance(value, Mapping):
        return {}
    normalized: dict[str, bool] = {}
    for key in DEFAULT_DOWNLOAD_OPTIONS:
        option = value.get(key)
        if isinstance(option, bool):
            normalized[key] = option
    return normalized


def _normalize_download_inputs(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    normalized: dict[str, str] = {}
    for key in DOWNLOAD_INPUT_KEYS:
        option = value.get(key)
        if isinstance(option, str):
            normalized[key] = option
    return normalized
