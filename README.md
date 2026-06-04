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
- `--loaders fabric,forge,neoforge,quilt,minecraft`: optional loader filter.
- `--channels release,beta,alpha`: release channels; default is `release`.
- `--token TOKEN`: token for this run.
- `--save-token`: save the provided or prompted token.
- `--set-token`: prompt for, validate, and save a token.
- `--forget-token`: remove the saved token.
- `--no-token`: ignore saved and environment tokens.
- `--group-by-type`: download into project type subfolders.
- `--dry-run`: show planned downloads without downloading files.
- `--yes`: use defaults and avoid prompts.

Token precedence is:

1. `--token`
2. `MODRINTH_TOKEN`
3. saved config token

`--no-token` disables all token sources for that run.
