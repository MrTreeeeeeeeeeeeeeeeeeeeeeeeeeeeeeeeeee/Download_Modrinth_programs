from pathlib import Path
from unittest.mock import Mock

import pytest

from modrinth_collection_downloader import gui
from modrinth_collection_downloader.config import AppConfig


@pytest.mark.parametrize('preview', [True, False])
def test_gui_run_uses_filters_and_reports_completion(tmp_path, monkeypatch, preview):
    monkeypatch.setenv('MODRINTH_COLLECTION_DOWNLOADER_CONFIG', str(tmp_path / 'config.json'))
    client = Mock()
    client.get_collection.return_value = {'name': 'Test collection', 'projects': ['abc']}
    client.get_projects.return_value = [{'id': 'abc', 'project_type': 'mod'}]
    monkeypatch.setattr(gui, 'ModrinthClient', Mock(return_value=client))
    plan = Mock(return_value=([], [], []))
    download = Mock(return_value=[])
    monkeypatch.setattr(gui.cli, '_build_download_plan', plan)
    monkeypatch.setattr(gui.cli, '_download_planned', download)
    app = gui.DownloaderApp.__new__(gui.DownloaderApp)
    app.config = AppConfig()
    app.events = gui.queue.Queue()
    output = tmp_path / 'downloads'
    app.run(dict(values={'Collection URL or ID': 'abc', 'Download folder': str(output),
                         'Minecraft versions': '1.21', 'Mod / modpack loaders': 'fabric',
                         'Shader loaders': '', 'Plugin loaders': ''},
                 types={'mod'}, channels=['release'], options={'type_subfolders': True,
                 'modpack_zip': False, 'strict_metadata': True}, token='', remember=False,
                 no_token=True, preview=preview))
    assert plan.call_args.kwargs['minecraft_versions'] == ['1.21']
    assert plan.call_args.kwargs['loader_filters']['mod'] == ['fabric']
    assert download.call_count == (0 if preview else 1)
    assert app.config.last_collection == 'abc'
    client.session.close.assert_called_once()
    events = list(app.events.queue)
    assert events[-1][0] == 'done'
    assert 'failed —' not in events[-1][1]
    if preview:
        assert not output.exists()


def test_gui_network_error_still_finishes(tmp_path, monkeypatch):
    monkeypatch.setenv('MODRINTH_COLLECTION_DOWNLOADER_CONFIG', str(tmp_path / 'config.json'))
    client = Mock()
    client.get_collection.side_effect = RuntimeError('Connection unavailable')
    monkeypatch.setattr(gui, 'ModrinthClient', Mock(return_value=client))
    app = gui.DownloaderApp.__new__(gui.DownloaderApp)
    app.config = AppConfig()
    app.events = gui.queue.Queue()
    app.run(dict(values={'Collection URL or ID': 'abc', 'Download folder': str(tmp_path),
                         'Minecraft versions': '', 'Mod / modpack loaders': '',
                         'Shader loaders': '', 'Plugin loaders': ''}, types={'mod'},
                 channels=['release'], options={}, token='', remember=False, no_token=True, preview=True))
    assert list(app.events.queue)[-1] == ('done', 'Run failed — see the activity log.')
