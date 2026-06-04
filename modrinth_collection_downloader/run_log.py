from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class RunLog:
    started_at: datetime = field(default_factory=lambda: datetime.now().astimezone())
    events: list[str] = field(default_factory=list)

    def add(self, message: str, **fields: Any) -> None:
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        details = _format_fields(fields)
        if details:
            self.events.append(f"[{timestamp}] {message} | {details}")
        else:
            self.events.append(f"[{timestamp}] {message}")

    def default_filename(self) -> str:
        stamp = self.started_at.strftime("%Y%m%d_%H%M%S")
        return f"modrinth_collection_downloader_{stamp}.log"

    def write(self, path: str | Path) -> Path:
        target = Path(path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            handle.write("Modrinth Collection Downloader Run Log\n")
            handle.write(f"Started: {self.started_at.isoformat(timespec='seconds')}\n")
            handle.write("\n")
            for event in self.events:
                handle.write(event)
                handle.write("\n")
        return target


def resolve_log_path(
    *,
    requested_log_file: str | None,
    output_dir: str | Path | None,
    config_path: str | Path,
    run_log: RunLog,
) -> Path:
    if requested_log_file:
        requested = Path(requested_log_file).expanduser()
        if requested.suffix:
            return requested
        return requested / run_log.default_filename()

    if output_dir is not None:
        return Path(output_dir).expanduser() / run_log.default_filename()

    return Path(config_path).expanduser().parent / run_log.default_filename()


def _format_fields(fields: dict[str, Any]) -> str:
    parts: list[str] = []
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)):
            rendered = ",".join(str(item) for item in value) if value else "(none)"
        else:
            rendered = str(value)
        parts.append(f"{key}={rendered}")
    return "; ".join(parts)
