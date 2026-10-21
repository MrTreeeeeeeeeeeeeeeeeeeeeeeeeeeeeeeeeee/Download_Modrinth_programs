"""Double-click this file, or use Start Downloader.vbs on Windows."""
import importlib.util
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))


def launch():
    from modrinth_collection_downloader.gui import main
    main()


if __name__ == '__main__':
    missing = [name for name in ('requests', 'rich') if importlib.util.find_spec(name) is None]
    if not missing:
        launch()
    else:
        root = tk.Tk()
        root.title('Setting up Modrinth Downloader')
        root.geometry('460x140')
        ttk.Label(root, text='Installing required packages…\nThis only happens on the first run.', padding=20).pack()
        bar = ttk.Progressbar(root, mode='indeterminate')
        bar.pack(fill='x', padx=20)
        bar.start()
        result = []
        def install():
            executable = Path(sys.executable).with_name('python.exe') if sys.platform == 'win32' else Path(sys.executable)
            try:
                process = subprocess.run([str(executable), '-m', 'pip', 'install', 'requests>=2.31', 'rich>=13.7'], capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
                result.append(None if process.returncode == 0 else process.stderr or process.stdout)
            except Exception as exc:
                result.append(str(exc))
        def poll():
            if not result:
                root.after(100, poll)
                return
            if result[0]:
                messagebox.showerror('Setup failed', 'Could not install the required packages. Check your internet connection and try again.\n\n' + result[0], parent=root)
                root.destroy()
            else:
                root.destroy()
                launch()
        threading.Thread(target=install, daemon=True).start()
        root.after(100, poll)
        root.mainloop()
