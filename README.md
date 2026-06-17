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

The program asks for the collection, item types, version filters, download folder, and run options while it is running. You can choose server-required mods and modpacks, type subfolders versus flat output, modpack ZIP conversion, dry run, and strict verification from the prompts instead of adding startup flags.

Direct collection URL:

```powershell
python -m modrinth_collection_downloader "https://modrinth.com/collection/gRlE8phg/mods"
```

Repeat the last saved run without prompts:

```powershell
python -m modrinth_collection_downloader --yes
```

Repeat the last saved options with a different collection:

```powershell
python -m modrinth_collection_downloader gRlE8phg --yes
```

The app fetches the collection before asking filter questions, then shows the item types and counts in the collection. Loader and option prompts are only shown when they apply to the selected item types:

- Mods and modpacks use the mod loader prompt.
- Shaders use a separate shader loader prompt.
- Plugins use a separate plugin platform prompt.
- Resource packs and datapacks are never filtered by loader, even when a mod loader is specified.
- Server-required mode is offered when mods or modpacks are selected.
- Modpack ZIP conversion is offered when modpacks are selected.

Interactive runs also ask which release channels to include. The default is `release,beta` because some common collection items, including resource packs, publish compatible versions as beta. Enter `all` to include `release,beta,alpha`. Enter `release` when you want release-only downloads.

Minecraft version matching handles versions that list several compatible game versions, and also treats minor-series entries like `1.20` or `1.20.x` as compatible with patch versions such as `1.20.1`.

Choose server-required mode during an interactive run to download only Modrinth projects whose type is `mod` or `modpack` and whose server-side environment is `required`. This includes server-only items and items required on both client and server, and excludes client-only items plus items that are only optional on the server.

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

Choose flat output during an interactive run to put all downloaded files directly in the output folder.

Choose modpack ZIP conversion during an interactive run to convert Modrinth modpack `.mrpack` files into full `.zip` archives. A converted modpack is always written to its own folder under `modpack`, even when flat output is selected:

```text
output-folder/
  modpack/
    Pack Name/
      Pack Name Version.zip
```

The converter reads `modrinth.index.json` from the `.mrpack`, copies `overrides/` and `client-overrides/`, downloads the referenced files into their manifest paths, and writes the final zip. In server-required mode, converted modpack zips use a `-server.zip` filename, look up each referenced Modrinth project, include files whose project server-side environment is `required`, and copy `overrides/` plus `server-overrides/` instead of client overrides. If some referenced files cannot be downloaded, the zip is still created with `FAILED_DOWNLOADS.txt` inside it, and the console plus run log show a warning.

Every run writes a plain-text log file when it finishes. By default, the log is saved in the selected download folder using a timestamped filename like:

```text
modrinth_collection_downloader_20260604_123000.log
```

For token-only actions or early exits before a download folder is known, the log is written beside the app config file. During an interactive run, you can choose a custom log file or log folder, or leave it blank for the default behavior.

The log records collection details, selected filters, token source with the token masked, each planned/skipped/downloaded item, failures, and the final summary.

During actual downloads, the terminal prints a permanent `Downloading x/y` and `Downloaded x/y` line for each file. This keeps large collections visible in normal PowerShell scrollback even though only the current file uses a live progress bar.

Downloads are retried when verification fails. If Modrinth's recorded size or hashes disagree with the CDN response, the app accepts the file only when the CDN transfer completed and the downloaded `.zip`, `.jar`, or `.mrpack` passes archive validation. The run log records this as a warning. Choose strict verification during an interactive run to fail instead.

## Saved Choices

The app saves the collection, start/token prompt choices, download folder, selected item types, version filters, loader filters, channel selection, log-file choice, and download options after each run setup. The next interactive run uses those saved values as prompt defaults, and `--yes` uses the saved values without prompting.

## Personal Access Tokens

Most public downloads do not need a token. Private or otherwise restricted collections may require a Modrinth Personal Access Token.

Save a token:

```powershell
python -m modrinth_collection_downloader
```

Then choose `Save or replace Modrinth token`.

Use a token for one download, save a token for downloads, or continue without a token:

```powershell
python -m modrinth_collection_downloader
```

Then choose `Download a collection` and select the token option you want.

Forget the saved token:

```powershell
python -m modrinth_collection_downloader
```

Then choose `Forget saved Modrinth token`.

The saved token is stored in plain text at:

```text
~/.modrinth_collection_downloader/config.json
```

The app masks tokens in terminal output, but the config file itself contains the full token.

## Options

Startup options are intentionally limited:

- `collection`: optional Modrinth collection URL or ID. If omitted, the program prompts and defaults to the last saved collection.
- `--yes`: use saved/default choices and avoid prompts.

All other choices are made inside the program and saved for the next run.

Token precedence is:

1. token entered for this run
2. `MODRINTH_TOKEN`
3. saved config token

Choosing `Continue without a token` disables all token sources for that run.
