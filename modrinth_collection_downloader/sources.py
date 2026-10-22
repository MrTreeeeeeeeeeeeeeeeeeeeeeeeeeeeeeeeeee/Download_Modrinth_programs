"""Standalone modpack sources for the desktop downloader."""
from pathlib import Path
from urllib.parse import urlparse, quote
import zipfile

from . import cli
from .download import resolve_destination
from .modpack_convert import _read_manifest, convert_mrpack_to_zip
from .modrinth import BASE_V2


def source_kind(source):
    if source.lower().endswith('.mrpack') and not source.startswith(('https://', 'http://')):
        return 'file'
    if '/modpack/' in source:
        parse_modpack_link(source)
        return 'modpack'
    return 'collection'


def parse_modpack_link(source):
    parsed = urlparse(source if '://' in source else 'https://' + source)
    parts = [part for part in parsed.path.split('/') if part]
    if parsed.scheme not in ('https', 'http') or parsed.hostname not in ('modrinth.com', 'www.modrinth.com') or len(parts) < 2 or parts[0] != 'modpack':
        raise ValueError('Paste a Modrinth modpack link, such as https://modrinth.com/modpack/fabulously-optimized.')
    version = None
    if len(parts) > 2:
        if parts[2] in ('version', 'versions') and len(parts) == 4:
            version = parts[3]
        elif len(parts) != 3 or parts[2] not in ('versions', 'gallery', 'changelog'):
            raise ValueError('Use the modpack main page or a specific version link.')
    return parts[1], version


def convert_local(source, output, *, preview, strict_metadata, console, run_log):
    source = Path(source).expanduser()
    with zipfile.ZipFile(source) as archive:
        manifest = _read_manifest(archive)
    destination = resolve_destination(output, source.stem + '.zip').path
    console.print(f"Modpack: {manifest['name']} ({manifest['versionId']})", markup=False)
    console.print(f"{len(manifest['files'])} referenced files; ZIP: {destination}", markup=False)
    if preview:
        return 'Preview complete: local modpack ready to convert. No files downloaded.'
    result = convert_mrpack_to_zip(source, destination, strict_metadata=strict_metadata,
                                  progress_callback=lambda text: console.print(text, markup=False), run_log=run_log)
    console.print(f'ZIP saved: {destination}', markup=False)
    if result.warning:
        console.print(result.warning, markup=False)
    return f'ZIP created with {len(result.missing_files)} missing files.' if result.missing_files else 'Finished: modpack ZIP created.'


def plan_modpack_link(source, client, *, output, minecraft_versions, loaders, channels, console, run_log):
    slug, pinned = parse_modpack_link(source)
    project = client.get_json(f'{BASE_V2}/project/{quote(slug, safe="")}')
    if project.get('project_type') != 'modpack':
        raise ValueError('This link does not point to a modpack.')
    versions = client.list_project_versions(project['id'], minecraft_versions=None if pinned else minecraft_versions, loaders=None if pinned else loaders)
    if pinned:
        version = next((item for item in versions if pinned in (item.get('id'), item.get('version_number'))), None)
        if version is None:
            raise ValueError('The linked modpack version was not found.')
        console.print('Using the exact linked version; version filters and channels apply only to main-page links.')
    else:
        version = cli.select_version(versions, channels=channels, minecraft_versions=minecraft_versions, loaders=loaders)
        if version is None:
            raise ValueError('No modpack version matches the selected filters and channels.')
    files = [file for file in version.get('files', []) if str(file.get('filename', '')).lower().endswith('.mrpack')]
    file = next((file for file in files if file.get('primary')), files[0] if files else None)
    if file is None:
        raise ValueError('The selected version has no .mrpack file to convert.')
    destination = cli.resolve_modpack_zip_destination(output / 'modpack' / cli.modpack_folder_name(project),
        cli.modpack_zip_filename(file, project, version), project_slug=project.get('slug'), version_id=version.get('id'))
    item = cli.PlannedDownload(project, version, file, destination, convert_modpack_zip=True)
    run_log.add('Modpack link resolved', source=source, version=version.get('id'), destination=destination.path)
    return ([], [item], []) if destination.status == 'already_exists' else ([item], [], [])
