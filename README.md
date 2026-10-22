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

## Convert a modpack to ZIP

- **Local file:** click **Choose .mrpack…**, select a file, choose your output
  folder, and click **Download**. The ZIP contains the pack's referenced downloads
  and client overrides. Local file conversion uses the versions in the pack;
  project-type, Minecraft-version, loader, and channel filters do not apply.
- **Modrinth link:** paste a `https://modrinth.com/modpack/...` link in the source
  field and click **Download**. Main-page links select the latest matching version
  using your Minecraft, mod/modpack loader, and release-channel filters. A specific
  `/version/...` link uses that exact version instead. ZIP conversion is automatic
  for standalone modpack links, regardless of the collection conversion checkbox.
- **Preview** checks the source and shows the destination without downloading.
  Local files create ZIPs directly in the selected folder; linked modpacks use
  `modpack/<pack name>/`. Existing local ZIPs are preserved with a renamed output.

Internet access is needed to fetch files referenced by a `.mrpack`. If some files
cannot be downloaded, the activity log reports a warning and the ZIP contains
`FAILED_DOWNLOADS.txt` with the missing files. These ZIPs contain client pack files,
not a Minecraft launcher or a Minecraft installation.
