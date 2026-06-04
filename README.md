# Modrinth Collection Downloader

A command-line app for downloading selected project types from a Modrinth collection.

## Install

From this folder:

```powershell
python -m pip install -e .
```

## Basic Usage

Interactive mode:

```powershell
python -m modrinth_collection_downloader
```

Direct collection URL:

```powershell
python -m modrinth_collection_downloader "https://modrinth.com/collection/gRlE8phg/mods"
```

Non-interactive dry run with release-only versions:

```powershell
python -m modrinth_collection_downloader gRlE8phg -o "C:\Minecraft\mods" --types mod --minecraft-version 1.21.1 --loaders fabric --channels release --dry-run --yes
```

The app fetches the collection before asking filter questions, then shows the item types and counts in the collection. Loader prompts are only shown for selected item types that use them:

- Mods and modpacks use the mod loader prompt or `--loaders` / `--mod-loaders`.
- Shaders use a separate shader loader prompt or `--shader-loaders`.
- Plugins use a separate plugin platform prompt or `--plugin-loaders`.
- Resource packs and datapacks are never filtered by loader, even when a mod loader is specified.

Interactive runs also ask which version channels to use. The default is `release,beta` because some common collection items, including resource packs, publish compatible versions as beta. Enter `all` or pass `--channels all` to include `release,beta,alpha`. Pass `--channels release` when you want release-only downloads.

Minecraft version matching handles versions that list several compatible game versions, and also treats minor-series entries like `1.20` or `1.20.x` as compatible with patch versions such as `1.20.1`.

By default, every downloaded file is placed in a subfolder named for its Modrinth project type:

```text
output-folder/
  mod/
  modpack/
  resourcepack/
  shader/
  plugin/
  datapack/
```

Use `--flat` to put all downloaded files directly in the output folder.

Use `--modpack-zip` to convert Modrinth modpack `.mrpack` files into full `.zip` archives. A converted modpack is always written to its own folder under `modpack`, even when `--flat` is used:

```text
output-folder/
  modpack/
    Pack Name/
      Pack Name Version.zip
```

The converter reads `modrinth.index.json` from the `.mrpack`, copies `overrides/` and `client-overrides/`, downloads the referenced files into their manifest paths, and writes the final zip. If some referenced files cannot be downloaded, the zip is still created with `FAILED_DOWNLOADS.txt` inside it, and the console plus run log show a warning.

Every run writes a plain-text log file when it finishes. By default, the log is saved in the selected download folder using a timestamped filename like:

```text
modrinth_collection_downloader_20260604_123000.log
```

For token-only commands or early exits before a download folder is known, the log is written beside the app config file. You can choose a custom log file or log folder:

```powershell
python -m modrinth_collection_downloader gRlE8phg -o "C:\Minecraft\mods" --log-file "C:\Logs\modrinth-run.log"
python -m modrinth_collection_downloader gRlE8phg -o "C:\Minecraft\mods" --log-file "C:\Logs"
```

The log records collection details, selected filters, token source with the token masked, each planned/skipped/downloaded item, failures, and the final summary.

During actual downloads, the terminal prints a permanent `Downloading x/y` and `Downloaded x/y` line for each file. This keeps large collections visible in normal PowerShell scrollback even though only the current file uses a live progress bar.

Downloads are retried when verification fails. If Modrinth's recorded size or hashes disagree with the CDN response, the app accepts the file only when the CDN transfer completed and the downloaded `.zip`, `.jar`, or `.mrpack` passes archive validation. The run log records this as a warning. Use `--strict-metadata` to fail instead.

## Personal Access Tokens

Most public downloads do not need a token. Private or otherwise restricted collections may require a Modrinth Personal Access Token.

Save a token:

```powershell
python -m modrinth_collection_downloader --set-token
```

Use and save a token from the command line:

```powershell
python -m modrinth_collection_downloader --token "mrp_..." --save-token
```

Forget the saved token:

```powershell
python -m modrinth_collection_downloader --forget-token
```

The saved token is stored in plain text at:

```text
~/.modrinth_collection_downloader/config.json
```

The app masks tokens in terminal output, but the config file itself contains the full token.

## Options

- `collection`: Modrinth collection URL or ID.
- `-o, --output PATH`: folder to download into.
- `--types mod,shader,...`: selected project types.
- `--minecraft-version VERSION`: optional Minecraft version filter.
- `--loaders fabric,forge,neoforge,quilt`: optional mod/modpack loader filter. `--mod-loaders` is also accepted.
- `--shader-loaders iris,optifine,canvas,vanilla`: optional shader loader filter.
- `--plugin-loaders paper,spigot,purpur,folia,velocity`: optional plugin platform filter.
- `--channels release,beta,alpha`: version channels; default is `release,beta`. `all` expands to `release,beta,alpha`.
- `--token TOKEN`: token for this run.
- `--save-token`: save the provided or prompted token.
- `--set-token`: prompt for, validate, and save a token.
- `--forget-token`: remove the saved token.
- `--no-token`: ignore saved and environment tokens.
- `--flat`: download all files directly into the output folder instead of type subfolders.
- `--group-by-type`: accepted for old scripts; type subfolders are now the default.
- `--log-file PATH`: write the run log to a specific file, or to a folder with the default timestamped filename.
- `--modpack-zip`: convert modpack `.mrpack` downloads into full `.zip` archives.
- `--strict-metadata`: fail when file size or hashes differ from Modrinth metadata.
- `--dry-run`: show planned downloads without downloading files.
- `--yes`: use defaults and avoid prompts.

Token precedence is:

1. `--token`
2. `MODRINTH_TOKEN`
3. saved config token

`--no-token` disables all token sources for that run.
