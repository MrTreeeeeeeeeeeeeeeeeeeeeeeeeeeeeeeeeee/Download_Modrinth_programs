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

Non-interactive dry run:

```powershell
python -m modrinth_collection_downloader gRlE8phg -o "C:\Minecraft\mods" --types mod --minecraft-version 1.21.1 --loaders fabric --channels release --dry-run --yes
```

The app fetches the collection before asking filter questions, then shows the item types and counts in the collection. Loader prompts are only shown for selected item types that use them:

- Mods and modpacks use the mod loader prompt or `--loaders` / `--mod-loaders`.
- Shaders use a separate shader loader prompt or `--shader-loaders`.
- Plugins use a separate plugin platform prompt or `--plugin-loaders`.
- Resource packs and datapacks are never filtered by loader, even when a mod loader is specified.

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
- `--channels release,beta,alpha`: release channels; default is `release`.
- `--token TOKEN`: token for this run.
- `--save-token`: save the provided or prompted token.
- `--set-token`: prompt for, validate, and save a token.
- `--forget-token`: remove the saved token.
- `--no-token`: ignore saved and environment tokens.
- `--group-by-type`: download into project type subfolders.
- `--log-file PATH`: write the run log to a specific file, or to a folder with the default timestamped filename.
- `--dry-run`: show planned downloads without downloading files.
- `--yes`: use defaults and avoid prompts.

Token precedence is:

1. `--token`
2. `MODRINTH_TOKEN`
3. saved config token

`--no-token` disables all token sources for that run.
