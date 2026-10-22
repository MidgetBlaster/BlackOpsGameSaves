"""One Windows installer for the Game Save mod and manager."""

from __future__ import annotations

import ctypes
from io import BytesIO
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
import zipfile

import game_save_installer


def resource(name: str) -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / name


def verify_bundle() -> tuple[Path, Path, Path]:
    """Check the embedded manager, mod, loader, and map artwork."""
    payload = resource("game_save_mod_payload.zip")
    manager = resource("BlackOpsGameSaves.exe")
    icon = resource("BlackOpsGameSaves.ico")
    for path in (payload, manager, icon):
        if not path.is_file():
            raise FileNotFoundError(f"The installer is missing {path.name}")
    with zipfile.ZipFile(payload) as archive:
        members = set(archive.namelist())
        expected = set(game_save_installer.MOD_FILES)
        expected.update(f"ui textures/png/{name}" for name in game_save_installer.MAP_THUMBNAILS)
        expected.update(("Game Save.iwd", "installer/game_mod.zip"))
        missing = sorted(expected - members)
        if missing:
            raise FileNotFoundError("The installer package is missing: " + ", ".join(missing))
        damaged = archive.testzip()
        if damaged:
            raise ValueError(f"The installer package contains a damaged file: {damaged}")
        for name in game_save_installer.MAP_THUMBNAILS:
            artwork = archive.read(f"ui textures/png/{name}")
            if not artwork.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError(f"The installer contains an invalid map thumbnail: {name}")
        with zipfile.ZipFile(BytesIO(archive.read("installer/game_mod.zip"))) as loader:
            missing_loader = sorted(set(game_save_installer.PACKAGE_FILES) - set(loader.namelist()))
            if missing_loader:
                raise FileNotFoundError("The bundled game_mod loader is missing: " +
                                        ", ".join(missing_loader))
            damaged_loader = loader.testzip()
            if damaged_loader:
                raise ValueError(f"The bundled game_mod loader is damaged: {damaged_loader}")
    return payload, manager, icon


def elevate() -> bool:
    if sys.platform != "win32" or ctypes.windll.shell32.IsUserAnAdmin():
        return False
    args = subprocess.list2cmdline([*sys.argv[1:], "--elevated"])
    result = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable,
                                                 args, None, 1)
    if result <= 32:
        raise OSError("Administrator access is needed to install into the Black Ops folder")
    return True


class Installer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Install Black Ops Game Saves")
        self.geometry("780x400")
        self.minsize(720, 380)
        self.resizable(True, True)
        self.configure(bg="#141414")
        self.installing = False
        self.installed_app: Path | None = None
        self.protocol("WM_DELETE_WINDOW", self.close)
        try:
            self.iconbitmap(str(resource("BlackOpsGameSaves.ico")))
        except tk.TclError:
            pass
        tk.Label(self, text="BLACK OPS GAME SAVES", bg="#141414", fg="#eeeeee",
                 font=("Segoe UI", 17, "bold")).pack(anchor="w", padx=24, pady=(24, 4))
        tk.Label(self, text="One installer for the Game Save mod, game_mod loader, save manager, and map images.",
                 bg="#141414", fg="#aaaaaa",
                 font=("Segoe UI", 10)).pack(anchor="w", padx=24)
        tk.Label(self, text="Black Ops game folder", bg="#141414", fg="#eeeeee",
                 font=("Segoe UI", 10)).pack(anchor="w", padx=24, pady=(22, 5))
        row = tk.Frame(self, bg="#141414")
        row.pack(fill="x", padx=24)
        found = game_save_installer.find_game()
        self.folder = tk.StringVar(value=str(found) if found else "")
        tk.Entry(row, textvariable=self.folder, bg="#242424", fg="#eeeeee",
                 insertbackground="#eeeeee", relief="flat", font=("Segoe UI", 10)).pack(
                     side="left", fill="x", expand=True, ipady=7)
        tk.Button(row, text="Browse…", command=self.browse, bg="#333333", fg="#eeeeee",
                  relief="flat", padx=12, pady=7).pack(side="right", padx=(8, 0))
        tk.Label(self, text="Install locations:  mods\\Game Save  •  bin  •  main  •  zone\\Common",
                 bg="#141414", fg="#aaaaaa", font=("Segoe UI", 9)).pack(
                     anchor="w", padx=24, pady=(8, 0))
        self.status = tk.StringVar(value="Ready to install." if found else
                                   "Choose the folder containing BlackOps.exe.")
        tk.Label(self, textvariable=self.status, bg="#141414", fg="#aaaaaa",
                 font=("Segoe UI", 9), wraplength=570, justify="left").pack(
                     anchor="w", padx=24, pady=(15, 0))
        self.shortcut = tk.BooleanVar(value=True)
        tk.Checkbutton(self, text="Create a Desktop shortcut", variable=self.shortcut,
                       bg="#141414", fg="#eeeeee", selectcolor="#242424",
                       activebackground="#141414", activeforeground="#eeeeee",
                       font=("Segoe UI", 10)).pack(anchor="w", padx=24, pady=(8, 0))
        row = tk.Frame(self, bg="#141414")
        row.pack(fill="x", padx=24, pady=(28, 20))
        self.install_button = tk.Button(row, text="Install Game Save", command=self.begin,
                                        bg="#dddddd", fg="#111111", relief="flat",
                                        padx=22, pady=10, font=("Segoe UI", 11, "bold"))
        self.install_button.pack(side="left")
        self.run_button = tk.Button(row, text="Run now", command=self.run_installed,
                                    bg="#333333", fg="#eeeeee", relief="flat",
                                    padx=18, pady=10, state="disabled")
        self.run_button.pack(side="left", padx=(12, 0))
        self.close_button = tk.Button(row, text="Close", command=self.close,
                                      bg="#333333", fg="#eeeeee", relief="flat",
                                      padx=18, pady=8)
        self.close_button.pack(side="right")

    def close(self):
        if self.installing:
            messagebox.showinfo("Installation in progress", "Wait for installation to finish before closing.",
                                parent=self)
            return
        self.destroy()

    def browse(self):
        chosen = filedialog.askdirectory(parent=self, title="Choose Black Ops game folder",
                                          initialdir=self.folder.get() or None)
        if chosen:
            self.folder.set(chosen)

    def begin(self):
        game = Path(self.folder.get().strip())
        if not (game / "BlackOps.exe").is_file():
            messagebox.showerror("Choose Black Ops", "Select the folder containing BlackOps.exe.", parent=self)
            return
        self.installing = True
        self.installed_app = None
        self.install_button.configure(state="disabled")
        self.run_button.configure(state="disabled")
        self.close_button.configure(state="disabled")
        self.status.set("Installing…")
        create_shortcut = self.shortcut.get()

        def work():
            try:
                payload, manager, icon = verify_bundle()
                with tempfile.TemporaryDirectory(prefix="bo1-game-save-") as directory:
                    source = Path(directory)
                    with zipfile.ZipFile(payload) as archive:
                        archive.extractall(source)
                    result = game_save_installer.install_all(source, game, manager, icon)
                destination = result["target"]
                message = (f"Game Save mod and manager installed in {destination}. "
                           f"Included {result['thumbnails']} map thumbnails.")
                if create_shortcut:
                    try:
                        create_desktop_shortcut(destination / "BlackOpsGameSaves.exe",
                                                destination / "BlackOpsGameSaves.ico")
                        message += " Desktop shortcut created."
                    except OSError as error:
                        message += f" Desktop shortcut could not be created: {error}"
                self.after(0, lambda: self.finish(message, destination / "BlackOpsGameSaves.exe"))
            except Exception as error:
                self.after(0, lambda error=error: self.failed(str(error)))
        threading.Thread(target=work, daemon=False).start()

    def finish(self, message: str, installed_app: Path):
        self.installing = False
        self.installed_app = installed_app
        self.install_button.configure(state="normal")
        self.run_button.configure(state="normal")
        self.close_button.configure(state="normal")
        self.status.set("Installed successfully. " + message + " Click Run now to open the save manager.")

    def run_installed(self):
        if self.installed_app is None or not self.installed_app.is_file():
            messagebox.showerror("Run now", "Install the save manager first.", parent=self)
            return
        try:
            subprocess.Popen([str(self.installed_app)], cwd=self.installed_app.parent)
        except OSError as error:
            messagebox.showerror("Run now", str(error), parent=self)
            return
        self.destroy()

    def failed(self, message: str):
        self.installing = False
        self.install_button.configure(state="normal")
        self.close_button.configure(state="normal")
        self.status.set("Installation failed.")
        messagebox.showerror("Installation failed", message, parent=self)


def main():
    if "--verify-bundle" in sys.argv:
        verify_bundle()
        return
    if "--smoke" not in sys.argv and "--elevated" not in sys.argv and elevate():
        return
    app = Installer()
    if "--smoke" in sys.argv:
        app.update()
        if (app.install_button.winfo_rooty() + app.install_button.winfo_height() >
                app.winfo_rooty() + app.winfo_height()):
            raise RuntimeError("The Install button is below the installer window")
        app.destroy()
    else:
        app.mainloop()


def create_desktop_shortcut(executable: Path, icon: Path):
    """Use the user's actual Desktop location, including redirected Desktops."""
    script = ("$desktop = [Environment]::GetFolderPath('DesktopDirectory'); "
              "$link = (New-Object -ComObject WScript.Shell).CreateShortcut("
              "(Join-Path $desktop 'Black Ops Game Saves.lnk')); "
              "$link.TargetPath = $env:BO1_SAVE_APP; "
              "$link.WorkingDirectory = $env:BO1_SAVE_FOLDER; "
              "$link.IconLocation = $env:BO1_SAVE_ICON; "
              "$link.Description = 'Black Ops Zombies Game Saves'; "
              "$link.Save()")
    environment = os.environ.copy()
    environment.update(BO1_SAVE_APP=str(executable), BO1_SAVE_FOLDER=str(executable.parent),
                       BO1_SAVE_ICON=str(icon))
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                            env=environment, capture_output=True, text=True, timeout=20)
    if result.returncode:
        raise OSError(result.stderr.strip() or "Could not create the Desktop shortcut")
