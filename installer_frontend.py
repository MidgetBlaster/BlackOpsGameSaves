"""One Windows installer for the Game Save mod and manager."""

from __future__ import annotations

import ctypes
from io import BytesIO
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
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
        expected.update(f"ui textures/{name}" for name in
                        (*game_save_installer.MAP_PREVIEWS, *game_save_installer.MENU_BACKGROUND))
        expected.update(("Game Save.iwd", "installer/game_mod.zip"))
        missing = sorted(expected - members)
        if missing:
            raise FileNotFoundError("The installer package is missing: " + ", ".join(missing))
        damaged = archive.testzip()
        if damaged:
            raise ValueError(f"The installer package contains a damaged file: {damaged}")
        pngs = [f"png/{name}" for name in game_save_installer.MAP_THUMBNAILS]
        pngs.extend(game_save_installer.MAP_PREVIEWS)
        pngs.extend(name for name in game_save_installer.MENU_BACKGROUND if name.endswith(".png"))
        for name in pngs:
            artwork = archive.read(f"ui textures/{name}")
            if not artwork.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError(f"The installer contains invalid map artwork: {name}")
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
        self.geometry("780x470")
        self.minsize(720, 430)
        self.resizable(True, True)
        self.configure(bg="#141414")
        self.installing = False
        self.page = ""
        self.installed_app: Path | None = None
        self.shortcut_done = False
        found = game_save_installer.find_game()
        self.executable_path = tk.StringVar(value=str(found / "BlackOps.exe") if found else "")
        self.shortcut = tk.BooleanVar(value=True)
        self.current_item = tk.StringVar(value="Preparing installation…")
        self.progress_value = tk.DoubleVar(value=0)
        self.events = queue.SimpleQueue()
        self.protocol("WM_DELETE_WINDOW", self.close)
        try:
            self.iconbitmap(str(resource("BlackOpsGameSaves.ico")))
        except tk.TclError:
            pass
        self.show_welcome()

    def _page(self, title: str, description: str):
        for child in self.winfo_children():
            child.destroy()
        footer = tk.Frame(self, bg="#141414")
        footer.pack(side="bottom", fill="x", padx=32, pady=24)
        body = tk.Frame(self, bg="#141414")
        body.pack(fill="both", expand=True, padx=32, pady=(34, 0))
        tk.Label(body, text=title, bg="#141414", fg="#f4f4f4",
                 font=("Segoe UI", 20, "bold")).pack(anchor="w", pady=(0, 12))
        tk.Label(body, text=description, bg="#141414", fg="#bcbcbc",
                 font=("Segoe UI", 11), wraplength=690, justify="left").pack(anchor="w")
        return body, footer

    @staticmethod
    def _button(parent, text, command, *, primary=False):
        return tk.Button(parent, text=text, command=command, relief="flat",
                         bg="#e8e8e8" if primary else "#353535",
                         fg="#111111" if primary else "#eeeeee",
                         activebackground="#ffffff" if primary else "#505050",
                         padx=20, pady=10, font=("Segoe UI", 10, "bold"))

    def show_welcome(self):
        self.page = "welcome"
        body, footer = self._page("BLACK OPS GAME SAVES",
                                  "Install the Game Save mod, game_mod loader, save manager, and Zombies map images from this one installer.")
        tk.Label(body, text="The next page lets you choose your BlackOps.exe file.",
                 bg="#141414", fg="#aaaaaa", font=("Segoe UI", 10)).pack(
                     anchor="w", pady=(32, 0))
        self.start_button = self._button(footer, "Install Game Save", self.show_location,
                                         primary=True)
        self.start_button.pack(side="left")
        self.cancel_button = self._button(footer, "Cancel", self.close)
        self.cancel_button.pack(side="right")

    def show_location(self):
        self.page = "location"
        body, footer = self._page("Choose BlackOps.exe",
                                  "Select the executable for the Black Ops installation you want to use. The installer puts the mod beside that game.")
        tk.Label(body, text="BlackOps.exe", bg="#141414", fg="#eeeeee",
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(32, 8))
        row = tk.Frame(body, bg="#141414")
        row.pack(fill="x")
        tk.Entry(row, textvariable=self.executable_path, bg="#242424", fg="#eeeeee",
                 insertbackground="#eeeeee", relief="flat", font=("Segoe UI", 10)).pack(
                     side="left", fill="x", expand=True, ipady=9)
        self.browse_button = self._button(row, "Browse for BlackOps.exe…", self.browse)
        self.browse_button.pack(side="right", padx=(10, 0))
        tk.Label(body, text="Example: D:\\Program Files (x86)\\Steam\\steamapps\\common\\Call of Duty Black Ops\\BlackOps.exe",
                 bg="#141414", fg="#999999", font=("Segoe UI", 9),
                 wraplength=690, justify="left").pack(anchor="w", pady=(14, 0))
        tk.Label(body, text="Selecting the file identifies the game build. Untested memory layouts are checked when the game runs; selection alone cannot determine new addresses.",
                 bg="#141414", fg="#aaaaaa", font=("Segoe UI", 9),
                 wraplength=690, justify="left").pack(anchor="w", pady=(8, 0))
        tk.Label(body, text="Installs to mods\\Game Save, bin, main, and zone\\Common. Existing saves are kept.",
                 bg="#141414", fg="#999999", font=("Segoe UI", 9)).pack(
                     anchor="w", pady=(8, 0))
        self.install_button = self._button(footer, "Install", self.begin, primary=True)
        self.install_button.pack(side="left")
        self.cancel_button = self._button(footer, "Cancel", self.close)
        self.cancel_button.pack(side="right")

    def show_progress(self):
        self.page = "progress"
        body, footer = self._page("Installing Game Save",
                                  "Copying the mod, game_mod loader, save manager, and map images.")
        self.bar = ttk.Progressbar(body, mode="determinate", maximum=100,
                                   variable=self.progress_value)
        self.bar.pack(fill="x", pady=(28, 12))
        tk.Label(body, textvariable=self.current_item, bg="#141414", fg="#eeeeee",
                 font=("Segoe UI", 10), wraplength=690, justify="left").pack(anchor="w")
        self.items = tk.Text(body, height=8, bg="#202020", fg="#bbbbbb",
                             relief="flat", font=("Consolas", 9), state="disabled")
        self.items.pack(fill="both", expand=True, pady=(16, 8))
        tk.Label(footer, text="Please wait until installation finishes.",
                 bg="#141414", fg="#999999", font=("Segoe UI", 9)).pack(side="left")

    def report(self, item: str, fraction: float):
        self.events.put(("progress", item, fraction))

    def drain_events(self):
        while not self.events.empty():
            event = self.events.get_nowait()
            if event[0] == "progress":
                self._report_ui(event[1], event[2])
            elif event[0] == "complete":
                self.finish(event[1])
            elif event[0] == "error":
                self.failed(event[1])
        if self.installing:
            self.after(40, self.drain_events)

    def _report_ui(self, item: str, fraction: float):
        if self.page != "progress":
            return
        self.progress_value.set(min(100, max(0, fraction * 100)))
        self.current_item.set(item)
        self.items.configure(state="normal")
        self.items.insert("end", item + "\n")
        self.items.see("end")
        self.items.configure(state="disabled")

    def close(self):
        if self.installing:
            messagebox.showinfo("Installation in progress", "Wait for installation to finish before closing.",
                                parent=self)
            return
        if self.page == "complete":
            self.apply_shortcut()
        self.destroy()

    def browse(self):
        current = Path(self.executable_path.get().strip().strip('"')).expanduser()
        chosen = filedialog.askopenfilename(
            parent=self, title="Choose BlackOps.exe",
            initialdir=str(current.parent) if current.is_file() else None,
            initialfile="BlackOps.exe",
            filetypes=[("Black Ops executable", "BlackOps.exe"), ("Executable files", "*.exe")])
        if chosen:
            self.executable_path.set(chosen)

    def begin(self):
        executable = Path(self.executable_path.get().strip().strip('"')).expanduser()
        if executable.name.casefold() != "blackops.exe" or not executable.is_file():
            messagebox.showerror("Choose Black Ops", "Select the BlackOps.exe file for your game.", parent=self)
            return
        game = executable.parent
        self.installing = True
        self.installed_app = None
        self.progress_value.set(0)
        self.show_progress()
        self.after(40, self.drain_events)

        def work():
            try:
                self.report("Checking files embedded in the installer…", 0.02)
                payload, manager, icon = verify_bundle()
                staging_parent = game / "mods"
                staging_parent.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(prefix=".game-save-install-",
                                                 dir=staging_parent) as directory:
                    source = Path(directory)
                    self.report("Extracting the mod and map images…", 0.06)
                    with zipfile.ZipFile(payload) as archive:
                        archive.extractall(source)
                    self.report("Installing files into Black Ops…", 0.1)
                    result = game_save_installer.install_all(
                        source, game, manager, icon,
                        progress=lambda item, fraction: self.report(item, 0.1 + 0.9 * fraction))
                self.events.put(("complete", result))
            except Exception as error:
                self.events.put(("error", str(error)))
        threading.Thread(target=work, daemon=False).start()

    def finish(self, result: dict):
        self.installing = False
        self.installed_app = result["target"] / "BlackOpsGameSaves.exe"
        self.progress_value.set(100)
        self.show_complete(result)

    def show_complete(self, result: dict):
        self.page = "complete"
        self.geometry("780x540")
        self.minsize(720, 520)
        description = ("The mod, game_mod loader, save manager, and map images were installed."
                       if result.get("compatibility") == "unverified" else
                       "Game Save is ready. The mod, game_mod loader, save manager, and map images were installed.")
        body, footer = self._page("Installation complete", description)
        tk.Label(body, text=str(result["target"]), bg="#141414", fg="#dddddd",
                 font=("Segoe UI", 10), wraplength=690, justify="left").pack(
                     anchor="w", pady=(26, 8))
        tk.Label(body, text=f"{result['thumbnails']} map thumbnails installed",
                 bg="#141414", fg="#aaaaaa", font=("Segoe UI", 10)).pack(anchor="w")
        profile_status = result.get("profile_status", "verified_file")
        profile_label = {"verified_file": "Memory profile: verified for this executable",
                         "candidate": "Memory profile: candidate; live check required",
                         "unavailable": "Memory profile: unavailable for this executable"}[profile_status]
        tk.Label(body, text=profile_label, bg="#141414",
                 fg="#d5d5d5" if profile_status == "verified_file" else "#e5b96a",
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(8, 0))
        if result.get("compatibility") == "unverified":
            warning = ("A candidate address profile was saved. The manager will verify the running game's checkpoint structures before memory writes."
                       if profile_status == "candidate" else
                       "The selected executable did not provide a usable address candidate. Memory saves need a supported build profile.")
            tk.Label(body,
                     text=warning,
                     bg="#141414", fg="#e5b96a", font=("Segoe UI", 10),
                     wraplength=690, justify="left").pack(anchor="w", pady=(12, 0))
            details = (f"BlackOps.exe SHA-256: {result['executable_sha256']}\n"
                       f"Size: {result['executable_size']:,} bytes")
            tk.Label(body, text=details, bg="#141414", fg="#cccccc",
                     font=("Consolas", 9), wraplength=690,
                     justify="left").pack(anchor="w", pady=(8, 0))
            def copy_build_details():
                self.clipboard_clear()
                self.clipboard_append(details)
            self._button(body, "Copy game build details", copy_build_details).pack(
                anchor="w", pady=(8, 0))
        tk.Checkbutton(body, text="Create a Desktop icon", variable=self.shortcut,
                       bg="#141414", fg="#eeeeee", selectcolor="#242424",
                       activebackground="#141414", activeforeground="#eeeeee",
                       font=("Segoe UI", 11)).pack(anchor="w", pady=(32, 0))
        self.run_button = self._button(footer, "Run Black Ops Game Saves", self.run_installed,
                                        primary=True)
        self.run_button.pack(side="left")
        self.finish_button = self._button(footer, "Finish", self.close)
        self.finish_button.pack(side="right")

    def apply_shortcut(self):
        if not self.shortcut.get() or self.shortcut_done or self.installed_app is None:
            return
        try:
            create_desktop_shortcut(self.installed_app,
                                    self.installed_app.parent / "BlackOpsGameSaves.ico")
            self.shortcut_done = True
        except OSError as error:
            messagebox.showwarning("Desktop icon", f"The app installed, but its Desktop icon could not be created: {error}",
                                   parent=self)

    def run_installed(self):
        if self.installed_app is None or not self.installed_app.is_file():
            messagebox.showerror("Run now", "Install the save manager first.", parent=self)
            return
        self.apply_shortcut()
        try:
            subprocess.Popen([str(self.installed_app)], cwd=self.installed_app.parent)
        except OSError as error:
            messagebox.showerror("Run now", str(error), parent=self)
            return
        self.page = "launched"
        self.destroy()

    def failed(self, message: str):
        self.installing = False
        self.show_location()
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
        if (app.start_button.winfo_rooty() + app.start_button.winfo_height() >
                app.winfo_rooty() + app.winfo_height()):
            raise RuntimeError("The first Install button is below the installer window")
        app.show_location()
        app.update()
        if (app.install_button.winfo_rooty() + app.install_button.winfo_height() >
                app.winfo_rooty() + app.winfo_height()):
            raise RuntimeError("The folder page Install button is below the installer window")
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
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive",
                             "-WindowStyle", "Hidden", "-Command", script],
                            env=environment, capture_output=True, text=True, timeout=20,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise OSError(result.stderr.strip() or "Could not create the Desktop shortcut")
