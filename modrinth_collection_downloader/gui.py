from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from rich.console import Console
from . import cli
from .auth import resolve_token
from .config import load_config, save_config, DEFAULT_DOWNLOAD_OPTIONS, get_config_path
from .modrinth import ModrinthClient, parse_collection_id
from .run_log import RunLog, resolve_log_path

TYPES = ('mod', 'modpack', 'resourcepack', 'datapack', 'shader', 'plugin')


class QueueWriter:
    def __init__(self, events):
        self.events = events

    def write(self, text):
        if text:
            self.events.put(('text', text))
        return len(text)

    def flush(self):
        pass


class DownloaderApp:
    def __init__(self, root):
        self.root = root
        self.busy = False
        self.events = queue.Queue()
        self.config = load_config()
        root.title('Modrinth Collection Downloader')
        root.geometry('920x800')
        root.minsize(760, 720)
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('TButton', padding=7)
        style.configure('TLabel', padding=(0, 3))
        outer = ttk.Frame(root, padding=20)
        outer.pack(fill='both', expand=True)
        outer.columnconfigure(1, weight=1)
        ttk.Label(outer, text='Modrinth Collection Downloader', font=('Segoe UI', 19, 'bold')).grid(row=0, column=0, columnspan=3, sticky='w')
        ttk.Label(outer, text='Paste a collection, choose your filters, then preview or download.').grid(row=1, column=0, columnspan=3, sticky='w', pady=(0, 12))
        self.fields = {}
        saved = self.config.last_download_inputs
        defaults = {
            'Collection URL or ID': self.config.last_collection or '',
            'Download folder': self.config.last_download_dir or str(Path.home() / 'Downloads' / 'Modrinth'),
            'Minecraft versions': saved.get('minecraft_version', ''),
            'Mod / modpack loaders': saved.get('mod_loaders', ''),
            'Shader loaders': saved.get('shader_loaders', ''),
            'Plugin loaders': saved.get('plugin_loaders', ''),
        }
        for row, (label, default) in enumerate(defaults.items(), 2):
            ttk.Label(outer, text=label).grid(row=row, column=0, sticky='w', padx=(0, 12))
            variable = tk.StringVar(value=default)
            self.fields[label] = variable
            ttk.Entry(outer, textvariable=variable).grid(row=row, column=1, columnspan=1 if row == 3 else 2, sticky='ew', pady=3)
        ttk.Button(outer, text='Browse…', command=self.browse).grid(row=3, column=2, padx=(8, 0))
        ttk.Label(outer, text='Leave filters blank for any. Separate values with commas (for example: 1.21, 1.20.1 or fabric, forge).').grid(row=8, column=0, columnspan=3, sticky='w')
        types_frame = ttk.LabelFrame(outer, text='Project types', padding=8)
        types_frame.grid(row=9, column=0, columnspan=3, sticky='ew', pady=8)
        selected = cli.parse_type_selection(saved.get('types', 'all'), TYPES)
        self.types = {}
        for column, kind in enumerate(TYPES):
            self.types[kind] = tk.BooleanVar(value=kind in selected)
            ttk.Checkbutton(types_frame, text=kind.capitalize(), variable=self.types[kind]).grid(row=0, column=column, padx=6)
        options = ttk.Frame(outer)
        options.grid(row=10, column=0, columnspan=3, sticky='ew')
        self.channels = {}
        for channel in cli.ALL_CHANNELS:
            self.channels[channel] = tk.BooleanVar(value=channel in cli.parse_channel_selection(saved.get('channels')))
            ttk.Checkbutton(options, text=channel.capitalize(), variable=self.channels[channel]).pack(side='left', padx=(0, 14))
        self.options = {}
        for key, label in [('type_subfolders', 'Use type subfolders'), ('modpack_zip', 'Convert modpacks to ZIP'), ('strict_metadata', 'Strict file verification')]:
            self.options[key] = tk.BooleanVar(value=self.config.last_download_options.get(key, DEFAULT_DOWNLOAD_OPTIONS[key]))
            ttk.Checkbutton(options, text=label, variable=self.options[key]).pack(side='left')
        token_frame = ttk.LabelFrame(outer, text='Private collections (optional)', padding=8)
        token_frame.grid(row=11, column=0, columnspan=3, sticky='ew', pady=10)
        token_frame.columnconfigure(1, weight=1)
        ttk.Label(token_frame, text='Modrinth token').grid(row=0, column=0, padx=(0, 10))
        self.token = tk.StringVar(value=self.config.modrinth_token or '')
        ttk.Entry(token_frame, textvariable=self.token, show='•').grid(row=0, column=1, sticky='ew')
        self.remember = tk.BooleanVar(value=bool(self.config.modrinth_token))
        ttk.Checkbutton(token_frame, text='Remember token (stored locally as plain text)', variable=self.remember).grid(row=1, column=0, columnspan=2, sticky='w')
        self.no_token = tk.BooleanVar()
        ttk.Checkbutton(token_frame, text='Ignore all tokens for this run', variable=self.no_token).grid(row=2, column=0, columnspan=2, sticky='w')
        actions = ttk.Frame(outer)
        actions.grid(row=12, column=0, columnspan=3, sticky='ew')
        self.buttons = []
        for label, command in [('Preview', lambda: self.start(True)), ('Download', lambda: self.start(False))]:
            button = ttk.Button(actions, text=label, command=command)
            button.pack(side='left', padx=(0, 8))
            self.buttons.append(button)
        ttk.Button(actions, text='Open download folder', command=self.open_folder).pack(side='right')
        self.status = tk.StringVar(value='Ready')
        ttk.Label(outer, textvariable=self.status).grid(row=13, column=0, columnspan=3, sticky='w')
        self.progress = ttk.Progressbar(outer, mode='indeterminate')
        self.progress.grid(row=14, column=0, columnspan=3, sticky='ew', pady=(0, 8))
        self.log = ScrolledText(outer, height=12, wrap='word', font=('Consolas', 10), state='disabled')
        self.log.grid(row=15, column=0, columnspan=3, sticky='nsew')
        outer.rowconfigure(15, weight=1)
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(80, self.poll)

    def browse(self):
        folder = filedialog.askdirectory(initialdir=self.fields['Download folder'].get())
        if folder:
            self.fields['Download folder'].set(folder)

    def open_folder(self):
        path = Path(self.fields['Download folder'].get()).expanduser()
        if path.is_dir():
            os.startfile(path)
        else:
            messagebox.showinfo('Download folder', 'The folder will be created when you download.')

    def close(self):
        if self.busy:
            messagebox.showinfo('Download in progress', 'Please wait for this run to finish before closing the window.')
        else:
            self.root.destroy()

    def start(self, preview):
        if self.busy:
            return
        values = {key: value.get().strip() for key, value in self.fields.items()}
        try:
            parse_collection_id(values['Collection URL or ID'])
            if not values['Download folder']:
                raise ValueError('Choose a download folder.')
            types = {key for key, value in self.types.items() if value.get()}
            channels = [key for key, value in self.channels.items() if value.get()]
            if not types or not channels:
                raise ValueError('Select at least one project type and release channel.')
        except ValueError as exc:
            messagebox.showerror('Check your settings', str(exc))
            return
        settings = dict(values=values, types=types, channels=channels,
                        options={key: value.get() for key, value in self.options.items()},
                        token=self.token.get(), remember=self.remember.get(), no_token=self.no_token.get(), preview=preview)
        self.busy = True
        for button in self.buttons:
            button.state(['disabled'])
        self.log.configure(state='normal')
        self.log.delete('1.0', 'end')
        self.log.configure(state='disabled')
        self.status.set('Previewing collection…' if preview else 'Downloading collection…')
        self.progress.start(12)
        threading.Thread(target=self.run, args=(settings,), daemon=True).start()

    def run(self, settings):
        console = Console(file=QueueWriter(self.events), force_terminal=False, width=110, markup=True, highlight=False)
        log = RunLog()
        output = Path(settings['values']['Download folder']).expanduser().resolve()
        summary = 'Run failed'
        client = None
        try:
            values = settings['values']
            config = self.config
            config.last_collection = values['Collection URL or ID']
            config.last_download_dir = str(output)
            config.modrinth_token = settings['token'].strip() if settings['remember'] else None
            inputs = dict(types=','.join(sorted(settings['types'])), channels=','.join(settings['channels']))
            for key, label in [('minecraft_version', 'Minecraft versions'), ('mod_loaders', 'Mod / modpack loaders'), ('shader_loaders', 'Shader loaders'), ('plugin_loaders', 'Plugin loaders')]:
                inputs[key] = values[label]
            config.last_download_inputs.update(inputs)
            config.last_download_options.update(settings['options'])
            save_config(config)
            token = resolve_token(cli_token=settings['token'], no_token=settings['no_token']).token
            client = ModrinthClient(token=token)
            collection = client.get_collection(parse_collection_id(config.last_collection))
            console.print('Collection: ' + str(collection.get('name', config.last_collection)), markup=False)
            ids = list(collection.get('projects') or [])
            projects = cli._order_projects(ids, client.get_projects(ids)) if ids else []
            projects = [project for project in projects if project.get('project_type') in settings['types']]
            console.print(f'{len(projects)} projects match your selected types.')
            planned, existing, skipped = cli._build_download_plan(
                client=client, projects=projects, output_dir=output,
                minecraft_versions=cli.parse_csv(inputs['minecraft_version']),
                loader_filters={kind: cli.parse_csv(inputs[key]) for kind, key in [('mod', 'mod_loaders'), ('shader', 'shader_loaders'), ('plugin', 'plugin_loaders')]},
                channels=settings['channels'], group_by_type=settings['options']['type_subfolders'],
                modpack_zip=settings['options']['modpack_zip'], console=console, run_log=log)
            cli._print_plan(console, planned, existing, skipped, dry_run=settings['preview'])
            failures = []
            if not settings['preview']:
                failures = cli._download_planned(console, planned, strict_metadata=settings['options']['strict_metadata'], run_log=log)
            summary = (f'Preview: {len(planned)} to download' if settings['preview'] else f'Finished: {len(planned) - len(failures)} downloaded, {len(failures)} failed') + f', {len(existing)} existing, {len(skipped)} skipped.'
            console.print(summary, markup=False)
            log.add('Summary', result=summary)
        except Exception as exc:
            console.print('Error: ' + str(exc), markup=False)
            log.add('Run failed', error=exc)
            summary = 'Run failed — see the activity log.'
        finally:
            if client is not None:
                client.session.close()
            try:
                path = resolve_log_path(requested_log_file=None, output_dir=None if settings['preview'] else output, config_path=get_config_path(), run_log=log)
                console.print('Log saved: ' + str(log.write(path)), markup=False)
            except Exception as exc:
                console.print('Could not save log: ' + str(exc), markup=False)
            self.events.put(('done', summary))

    def poll(self):
        for _ in range(200):
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'done':
                self.busy = False
                self.progress.stop()
                self.status.set(value)
                for button in self.buttons:
                    button.state(['!disabled'])
            else:
                self.log.configure(state='normal')
                self.log.insert('end', value)
                self.log.see('end')
                self.log.configure(state='disabled')
        self.root.after(80, self.poll)


def main():
    root = tk.Tk()
    try:
        DownloaderApp(root)
    except Exception as exc:
        messagebox.showerror('Unable to open downloader', str(exc), parent=root)
        root.destroy()
        return 1
    root.mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
