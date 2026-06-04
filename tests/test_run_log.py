from datetime import datetime, timezone
from pathlib import Path

from modrinth_collection_downloader.run_log import RunLog, resolve_log_path


def test_resolve_log_path_prefers_requested_file(tmp_path):
    run_log = RunLog(started_at=datetime(2026, 6, 4, 12, 0, 0, tzinfo=timezone.utc))

    path = resolve_log_path(
        requested_log_file=str(tmp_path / "custom.log"),
        output_dir=tmp_path / "downloads",
        config_path=tmp_path / "config.json",
        run_log=run_log,
    )

    assert path == tmp_path / "custom.log"


def test_resolve_log_path_uses_output_dir_by_default(tmp_path):
    run_log = RunLog(started_at=datetime(2026, 6, 4, 12, 0, 0, tzinfo=timezone.utc))

    path = resolve_log_path(
        requested_log_file=None,
        output_dir=tmp_path / "downloads",
        config_path=tmp_path / "config.json",
        run_log=run_log,
    )

    assert path == tmp_path / "downloads" / "modrinth_collection_downloader_20260604_120000.log"


def test_run_log_writes_events(tmp_path):
    run_log = RunLog(started_at=datetime(2026, 6, 4, 12, 0, 0, tzinfo=timezone.utc))
    run_log.add("Something happened", project="Sodium", count=1)

    path = run_log.write(tmp_path / "run.log")

    text = Path(path).read_text(encoding="utf-8")
    assert "Modrinth Collection Downloader Run Log" in text
    assert "Something happened" in text
    assert "project=Sodium" in text
    assert "count=1" in text
