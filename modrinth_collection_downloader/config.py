from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


CONFIG_ENV_VAR = "MODRINTH_COLLECTION_DOWNLOADER_CONFIG"
DEFAULT_CONFIG_PATH = Path.home() / ".modrinth_collection_downloader" / "config.json"


@dataclass
class AppConfig:
    last_download_dir: str | None = None
    modrinth_token: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        extra = {
            key: value
            for key, value in data.items()
            if key not in {"last_download_dir", "modrinth_token"}
        }
        return cls(
            last_download_dir=data.get("last_download_dir") or None,
            modrinth_token=data.get("modrinth_token") or None,
            extra=extra,
        )

    def to_dict(self) -> dict[str, Any]:
        data = dict(self.extra)
        if self.last_download_dir:
            data["last_download_dir"] = self.last_download_dir
        if self.modrinth_token:
            data["modrinth_token"] = self.modrinth_token
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


def set_token(config: AppConfig, token: str) -> None:
    config.modrinth_token = token


def forget_token(config: AppConfig) -> None:
    config.modrinth_token = None
