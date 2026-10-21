# Modrinth Collection Downloader

Download projects from a Modrinth collection using a desktop window.

## Open the app

**Double-click `Start Downloader.vbs`.** Keep it in this folder with the other files.
You can also open `Downloader.pyw` directly if Python file associations are configured.

Python 3.10 or newer with Tkinter is required (included with the normal Windows
installer from python.org). On this computer Python is already installed.
The launcher automatically installs missing `requests` and `rich` packages on the
first run, with a setup window. Internet access is required for setup and downloads.
No terminal commands or command-line arguments are needed.

## Use the window

1. Paste a Modrinth collection URL or ID.
2. Choose the download folder using **Browse**.
3. Select project types and release channels. Optionally enter Minecraft versions
   and loaders. Leave a filter blank for any; separate multiple values with commas.
4. Click **Preview** to check matching files and skipped projects, or **Download**
   to save the files. The activity area shows results and errors.
5. Use **Open download folder** to view the files.

Settings are remembered between runs. Existing matching files are skipped;
conflicting filenames are renamed. Downloads run in the background so the window
stays responsive. Wait until the run finishes before closing the app.

Options include type subfolders, conversion of modpacks into ZIP files, and strict
file verification. Converted modpacks include their downloaded contents and are
placed in individual folders under `modpack`.

Public collections normally need no token. For a private collection, enter a
Modrinth token in the masked token field. A token is saved only when **Remember
token** is checked; saved tokens are plain text in the local configuration file.
Uncheck it and run Preview or Download to remove a previously saved token.
A blank field also allows the `MODRINTH_TOKEN` environment variable. Select
**Ignore all tokens for this run** to disable authentication.

Configuration is stored in `~/.modrinth_collection_downloader/config.json`.
Each run writes a log; previews store logs beside the configuration without
creating the download folder. Download logs are stored in the output folder.

## Development

`python -m modrinth_collection_downloader` opens the GUI. The original terminal
interface remains available through `python -m modrinth_collection_downloader.cli`
or the `modrinth-collection-downloader` installed command.

Run the checks with `python -m pytest -q`.
