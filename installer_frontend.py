"""Small standalone Windows installers for the Game Save mod and manager."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import shutil
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
    def __init__(self, kind: str):
        super().__init__()
        self.kind = kind
        self.title("Install Game Save mod" if kind == "mod" else "Install Black Ops Game Saves")
        self.geometry("625x285")
        self.resizable(False, False)
        self.configure(bg="#141414")
        try:
            self.iconbitmap(str(resource("BlackOpsGameSaves.ico")))
        except tk.TclError:
            pass
        label = "GAME SAVE MOD" if kind == "mod" else "BLACK OPS GAME SAVES"
        tk.Label(self, text=label, bg="#141414", fg="#eeeeee",
                 font=("Segoe UI", 17, "bold")).pack(anchor="w", padx=24, pady=(24, 4))
        detail = ("Installs the Zombies checkpoint mod and required loader files." if kind == "mod" else
                  "Installs the save manager into your Game Save mod folder.")
        tk.Label(self, text=detail, bg="#141414", fg="#aaaaaa",
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
        self.status = tk.StringVar(value="Ready to install." if found else
                                   "Choose the folder containing BlackOps.exe.")
        tk.Label(self, textvariable=self.status, bg="#141414", fg="#aaaaaa",
                 font=("Segoe UI", 9), wraplength=570, justify="left").pack(
                     anchor="w", padx=24, pady=(15, 0))
        self.shortcut = tk.BooleanVar(value=True)
        if kind == "app":
            tk.Checkbutton(self, text="Create a Desktop shortcut", variable=self.shortcut,
                           bg="#141414", fg="#eeeeee", selectcolor="#242424",
                           activebackground="#141414", activeforeground="#eeeeee",
                           font=("Segoe UI", 10)).pack(anchor="w", padx=24, pady=(8, 0))
        row = tk.Frame(self, bg="#141414")
        row.pack(side="bottom", fill="x", padx=24, pady=20)
        self.install_button = tk.Button(row, text="Install", command=self.begin,
                                        bg="#dddddd", fg="#111111", relief="flat",
                                        padx=20, pady=8, font=("Segoe UI", 10, "bold"))
        self.install_button.pack(side="right")
        tk.Button(row, text="Close", command=self.destroy, bg="#333333", fg="#eeeeee",
                  relief="flat", padx=18, pady=8).pack(side="right", padx=(0, 8))

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
        if self.kind == "app" and not (game / "mods" / "Game Save" / "mod.ff").is_file():
            messagebox.showerror("Install the mod first",
                                 "Install Game Save Mod first, then install the save manager.", parent=self)
            return
        self.install_button.configure(state="disabled")
        self.status.set("Installing…")
        create_shortcut = self.shortcut.get()

        def work():
            try:
                if self.kind == "mod":
                    payload = resource("game_save_mod_payload.zip")
                    with tempfile.TemporaryDirectory(prefix="bo1-game-save-") as directory:
                        source = Path(directory)
                        with zipfile.ZipFile(payload) as archive:
                            archive.extractall(source)
                        result = game_save_installer.install(source, game)
                    destination = result["target"]
                    message = f"Game Save mod installed in {destination}."
                else:
                    destination = game / "mods" / "Game Save"
                    destination.mkdir(parents=True, exist_ok=True)
                    for name in ("BlackOpsGameSaves.exe", "BlackOpsGameSaves.ico"):
                        source = resource(name)
                        target = destination / name
                        if not target.is_file() or source.read_bytes() != target.read_bytes():
                            shutil.copy2(source, target)
                    if create_shortcut:
                        create_desktop_shortcut(destination / "BlackOpsGameSaves.exe",
                                                destination / "BlackOpsGameSaves.ico")
                    message = f"Black Ops Game Saves installed in {destination}."
                self.after(0, lambda: self.finish(message))
            except Exception as error:
                self.after(0, lambda error=error: self.failed(str(error)))
        threading.Thread(target=work, daemon=True).start()

    def finish(self, message: str):
        self.install_button.configure(state="normal")
        self.status.set(message)
        messagebox.showinfo("Installation complete", message, parent=self)

    def failed(self, message: str):
        self.install_button.configure(state="normal")
        self.status.set("Installation failed.")
        messagebox.showerror("Installation failed", message, parent=self)


def main(kind: str):
    if "--smoke" not in sys.argv and "--elevated" not in sys.argv and elevate():
        return
    app = Installer(kind)
    if "--smoke" in sys.argv:
        app.withdraw()
        app.update()
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
