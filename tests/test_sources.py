import io
import json
import zipfile
from unittest.mock import Mock

import pytest
from rich.console import Console

from modrinth_collection_downloader.sources import convert_local, parse_modpack_link, plan_modpack_link, source_kind
from modrinth_collection_downloader.run_log import RunLog


def test_local_conversion_and_preview(tmp_path):
    source = tmp_path / 'Test.mrpack'
    with zipfile.ZipFile(source, 'w') as archive:
        archive.writestr('modrinth.index.json', json.dumps({'name': 'Test', 'versionId': '1', 'files': []}))
        archive.writestr('overrides/config/example.txt', 'test configuration')
    output = tmp_path / 'output'
    kwargs = dict(strict_metadata=True, console=Console(file=io.StringIO()), run_log=RunLog())
    assert 'Preview' in convert_local(source, output, preview=True, **kwargs)
    assert not output.exists()
    assert 'created' in convert_local(source, output, preview=False, **kwargs)
    with zipfile.ZipFile(output / 'Test.zip') as archive:
        assert archive.read('config/example.txt') == b'test configuration'
    convert_local(source, output, preview=False, **kwargs)
    assert (output / 'Test-copy.zip').exists()


@pytest.mark.parametrize('link, expected', [
    ('https://modrinth.com/modpack/test', ('test', None)),
    ('modrinth.com/modpack/test/version/abc?x=1', ('test', 'abc')),
    ('https://modrinth.com/modpack/test/versions', ('test', None)),
])
def test_modpack_links(link, expected):
    assert parse_modpack_link(link) == expected
    assert source_kind(link) == 'modpack'


def test_reject_other_host():
    with pytest.raises(ValueError):
        parse_modpack_link('https://example.com/modpack/test')


def test_link_plan_exact_version_and_mrpack_selection(tmp_path):
    client = Mock()
    client.get_json.return_value = {'id': 'project', 'slug': 'test', 'title': 'Test', 'project_type': 'modpack'}
    client.list_project_versions.return_value = [dict(id='abc', version_number='1.0', files=[
        {'filename': 'notes.txt', 'primary': True}, {'filename': 'test.mrpack', 'url': 'https://example.com/pack'}])]
    planned, existing, skipped = plan_modpack_link('https://modrinth.com/modpack/test/version/abc', client,
        output=tmp_path, minecraft_versions=['1.21'], loaders=['fabric'], channels=['release'],
        console=Console(file=io.StringIO()), run_log=RunLog())
    assert len(planned) == 1
    assert planned[0].convert_modpack_zip
    assert planned[0].file['filename'] == 'test.mrpack'
    assert planned[0].destination.path == tmp_path / 'modpack' / 'Test' / 'test.zip'
    assert not existing and not skipped
    client.list_project_versions.assert_called_once_with('project', minecraft_versions=None, loaders=None)
    assert not (tmp_path / 'modpack').exists()


def test_link_no_matching_version(tmp_path):
    client = Mock()
    client.get_json.return_value = {'id': 'project', 'project_type': 'modpack'}
    client.list_project_versions.return_value = []
    with pytest.raises(ValueError, match='No modpack version'):
        plan_modpack_link('https://modrinth.com/modpack/test', client, output=tmp_path,
            minecraft_versions=[], loaders=[], channels=['release'], console=Console(file=io.StringIO()), run_log=RunLog())
