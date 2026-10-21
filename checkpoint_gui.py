"""Desktop save manager for the Black Ops Zombies checkpoint companion."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import zipfile
from tkinter import filedialog, messagebox, simpledialog, ttk

import checkpoint_memory as core
import display_mode
import fov_keeper
import game_launcher
import game_save_installer
from save_library import SaveLibrary
import steam_identity


BG = "#0d0d0d"
SURFACE = "#181818"
PANEL = "#242424"
BORDER = "#3a3a3a"
TEXT = "#f0f0f0"
MUTED = "#a6a6a6"
ACCENT = "#d5d5d5"
MAP_ART = {
    "zombie_theater": ("Kino der Toten", "zombie_theater"),
    "zombie_pentagon": ("Five", "zombie_pentagon"),
    "zombietron": ("Dead Ops Arcade", "zombietron"),
    "zombie_cosmodrome": ("Ascension", "zombie_cosmo"),
    "zombie_coast": ("Call of the Dead", "zombie_coast"),
    "zombie_temple": ("Shangri-La", "zombie_temple"),
    "zombie_moon": ("Moon", "zombie_moon"),
    "zombie_cod5_prototype": ("Nacht der Untoten", "loadscreen_zombie_prototype_mini"),
    "zombie_cod5_asylum": ("Verrückt", "loadscreen_zombie_asylum_mini"),
    "zombie_cod5_sumpf": ("Shi No Numa", "loadscreen_zombie_sumpf_mini"),
    "zombie_cod5_factory": ("Der Riese", "loadscreen_zombie_factory_mini"),
}
DISPLAY_MODES = ("Windowed", "Fullscreen", "Borderless")


def map_title(map_name: str) -> str:
    return MAP_ART.get(map_name, (map_name.replace("_", " ").title(), None))[0]


def save_date(value: str, *, long: bool = False) -> str:
    try:
        date = datetime.fromisoformat(value).astimezone()
        return date.strftime("%B %d, %Y at %I:%M %p" if long else "%b %d, %Y  %I:%M %p")
    except (TypeError, ValueError):
        return value or "Unknown date"


def launch_as_administrator() -> bool:
    if sys.platform != "win32" or ctypes.windll.shell32.IsUserAnAdmin():
        return False
    executable = Path(sys.executable)
    pythonw = executable.with_name("pythonw.exe")
    if pythonw.exists():
        executable = pythonw
    command = ("--elevated" if getattr(sys, "frozen", False) else
               subprocess.list2cmdline([str(Path(__file__).resolve()), "--elevated"]))
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    shell.ShellExecuteW.argtypes = [wintypes.HWND, wintypes.LPCWSTR,
                                    wintypes.LPCWSTR, wintypes.LPCWSTR,
                                    wintypes.LPCWSTR, ctypes.c_int]
    shell.ShellExecuteW.restype = ctypes.c_void_p
    result = shell.ShellExecuteW(None, "runas", str(executable), command,
                                 str(core.ROOT), 1)
    return bool(result and result > 32)


class CheckpointApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Game Save — Black Ops Zombies")
        try:
            self.iconbitmap(str(core.ROOT / "BlackOpsGameSaves.ico"))
        except tk.TclError:
            pass
        self.geometry("1200x800")
        self.minsize(1010, 670)
        try:
            recovered = core.promote_recovery()
        except (OSError, RuntimeError, KeyError):
            recovered = None
        self.library = SaveLibrary()
        if recovered:
            self.library.register(recovered, kind="auto",
                                  profile_id=self.library.data["active_profile"])
        self.events = queue.Queue()
        self.save_lock = threading.Lock()
        self.watch_stop = None
        self.watch_thread = None
        self.start_cancel = None
        self.pending_coop = None
        self.started_save_name = None
        self.skip_initial_round = None
        self.coop_paused = False
        self.coop_pause_pid = None
        self.current_session_legacy = None
        self.current_map = None
        self.map_images = {}
        self.busy = False
        self.closing = False
        self.launch_after_close = None
        self.display_pid = None
        self.display_applied_mode = None
        self.display_working = False
        self.display_last_attempt = 0.0
        preferred_display = self.library.data.get("display_mode", "Borderless")
        self.display_mode = tk.StringVar(value=preferred_display if preferred_display in DISPLAY_MODES
                                         else "Borderless")
        self.fov_stop = threading.Event()
        try:
            fov, scale = fov_keeper.validate_settings(
                self.library.data.get("fov_value", 90),
                self.library.data.get("fov_scale", 1.0))
        except (TypeError, ValueError):
            fov, scale = 90.0, 1.0
        self.fov_enabled = bool(self.library.data.get("fov_enabled", False))
        self.fov_value = tk.StringVar(value=f"{fov:g}")
        self.fov_scale = tk.StringVar(value=f"{scale:.2f}")
        self.fov_settings = (self.fov_enabled, fov, scale)
        self.category = tk.StringVar(value="All saves")
        self.search = tk.StringVar()
        self.status = tk.StringVar(value="Recovery save found." if recovered else
                                   "Automatic saves happen after each round. F11 makes a manual save.")
        if core.game_pid() is None:
            try:
                game_launcher.prepare_script_variant(legacy=False)
            except (OSError, RuntimeError) as error:
                self.status.set(f"Could not prepare the pause script: {error}")
        self.save_policy = tk.StringVar(value=self.library.data.get("save_policy", "Keep new saves"))
        preferred_timing = self.library.data.get("save_timing", core.SAVE_TIMINGS[0])
        self.save_timing = tk.StringVar(value=preferred_timing if preferred_timing in core.SAVE_TIMINGS
                                        else core.SAVE_TIMINGS[0])
        self.configure(background=BG)
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 10))
        style.configure("TButton", padding=(10, 7), font=("Segoe UI", 10),
                        background=PANEL, foreground=TEXT, bordercolor=BORDER)
        style.map("TButton", background=[("active", "#383838"), ("disabled", SURFACE)],
                  foreground=[("disabled", "#697c96")])
        style.configure("TEntry", fieldbackground=SURFACE, foreground=TEXT, bordercolor=BORDER)
        style.configure("TCombobox", fieldbackground=SURFACE, background=PANEL,
                        foreground=TEXT, arrowcolor=TEXT, bordercolor=BORDER)
        style.map("TCombobox", fieldbackground=[("readonly", SURFACE)],
                  foreground=[("readonly", TEXT)])
        style.configure("TCheckbutton", background=BG, foreground=TEXT)
        style.configure("TRadiobutton", background=BG, foreground=TEXT)
        style.configure("Vertical.TScrollbar", background=PANEL, troughcolor=BG,
                        bordercolor=BG, arrowcolor=TEXT)
        style.configure("Treeview", rowheight=43, font=("Segoe UI", 10),
                        background=SURFACE, fieldbackground=SURFACE, foreground=TEXT,
                        bordercolor=BORDER)
        style.map("Treeview", background=[("selected", "#454545")],
                  foreground=[("selected", "#ffffff")])
        style.configure("Treeview.Heading", background=PANEL, foreground=TEXT,
                        font=("Segoe UI", 10, "bold"))
        style.layout("Checkpoint.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        style.configure("Checkpoint.Treeview", rowheight=52, font=("Segoe UI", 10),
                        background=SURFACE, fieldbackground=SURFACE, foreground=TEXT,
                        borderwidth=0, relief="flat")
        style.map("Checkpoint.Treeview", background=[("selected", "#383838")],
                  foreground=[("selected", TEXT)])
        self._build()
        self.refresh()
        self._start_watch()
        self.fov_thread = threading.Thread(target=self._fov_loop, daemon=True)
        self.fov_thread.start()
        self.after(100, self._poll_events)
        self.after(1500, self._ensure_display_mode)
        self.protocol("WM_DELETE_WINDOW", self.close)

    def _build(self):
        heading = tk.Frame(self, bg=SURFACE, padx=22, pady=17)
        heading.pack(fill="x")
        tk.Label(heading, text="GAME SAVE  ·  BLACK OPS ZOMBIES", bg=SURFACE, fg=ACCENT,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w")
        tk.Label(heading, text="Checkpoint saves", bg=SURFACE, fg=TEXT,
                 font=("Segoe UI", 21, "bold")).pack(anchor="w")
        tk.Label(heading, text="Choose a map, then choose a checkpoint to continue.",
                 bg=SURFACE, fg=MUTED, font=("Segoe UI", 10)).pack(anchor="w", pady=(3, 0))

        outer = ttk.Frame(self, padding=18)
        outer.pack(fill="both", expand=True)
        self.gallery_page = ttk.Frame(outer)
        self.gallery_page.pack(fill="both", expand=True)
        gallery_heading = ttk.Frame(self.gallery_page)
        gallery_heading.pack(fill="x", pady=(0, 8))
        ttk.Label(gallery_heading, text="Choose a map", font=("Segoe UI", 16, "bold")).pack(side="left")
        ttk.Button(gallery_heading, text="Import saves", command=self.import_saves).pack(side="right")
        ttk.Button(gallery_heading, text="Export all", command=self.export_all).pack(side="right", padx=(0, 8))
        for label in ("All saves", "Imported saves"):
            ttk.Radiobutton(gallery_heading, text=label, value=label, variable=self.category,
                            command=self.refresh).pack(side="right", padx=(0, 12))
        self.gallery_canvas = tk.Canvas(self.gallery_page, bg=BG, highlightthickness=0, bd=0)
        self.gallery_canvas.pack(fill="both", expand=True)
        self.gallery_grid = tk.Frame(self.gallery_canvas, bg=BG)
        self.gallery_window = self.gallery_canvas.create_window((0, 0), window=self.gallery_grid,
                                                                 anchor="nw")
        self.gallery_grid.bind("<Configure>", lambda _event: self.gallery_canvas.configure(
            scrollregion=self.gallery_canvas.bbox("all")))
        self.gallery_canvas.bind("<Configure>", lambda event: self.gallery_canvas.itemconfigure(
            self.gallery_window, width=event.width))
        self._bind_wheel(self.gallery_canvas, self._scroll_gallery)
        self._bind_wheel(self.gallery_grid, self._scroll_gallery)

        self.saves_page = ttk.Frame(outer)
        top = ttk.Frame(self.saves_page)
        top.pack(fill="x", pady=(0, 10))
        ttk.Button(top, text="← Maps", command=self.show_gallery).pack(side="left", padx=(0, 16))
        self.map_heading = ttk.Label(top, text="", font=("Segoe UI", 17, "bold"))
        self.map_heading.pack(side="left")
        ttk.Button(top, text="Import saves", command=self.import_saves).pack(side="right")
        ttk.Button(top, text="Export selected", command=self.export_selected).pack(side="right", padx=(0, 8))
        filter_bar = ttk.Frame(self.saves_page)
        filter_bar.pack(fill="x", pady=(0, 10))
        for label in ("All saves", "Favorites", "Imported saves"):
            ttk.Radiobutton(filter_bar, text=label, value=label, variable=self.category,
                            command=self.refresh).pack(side="left", padx=(0, 15))
        ttk.Label(filter_bar, text="Search").pack(side="right", padx=(7, 0))
        search_entry = ttk.Entry(filter_bar, textvariable=self.search, width=25)
        search_entry.pack(side="right")
        self.search.trace_add("write", lambda *_: self.refresh())

        content = ttk.Frame(self.saves_page)
        content.pack(fill="both", expand=True)
        map_preview = tk.Frame(content, bg=BG, width=266)
        map_preview.pack(side="left", fill="y", padx=(0, 16))
        map_preview.pack_propagate(False)
        self.selected_map_art = tk.Label(map_preview, bg=BG)
        self.selected_map_art.pack(anchor="nw", pady=(4, 10))
        self.selected_map_caption = tk.Label(map_preview, bg=BG, fg=TEXT,
                                             font=("Segoe UI", 16, "bold"),
                                             wraplength=255, justify="left")
        self.selected_map_caption.pack(anchor="nw")
        self.start_new_button = ttk.Button(map_preview, text="Start New Game",
                                            command=self.start_new_game)
        self.start_new_button.pack(anchor="nw", pady=(12, 0))
        info_content = ttk.Frame(content)
        info_content.pack(side="left", fill="both", expand=True)
        list_frame = tk.Frame(info_content, bg=SURFACE, padx=14, pady=14)
        list_frame.pack(side="left", fill="both", expand=True, padx=(0, 14))
        tk.Label(list_frame, text="SAVED CHECKPOINTS", bg=SURFACE, fg=ACCENT,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 9))
        self.tree = ttk.Treeview(list_frame, show="tree", selectmode="browse",
                                 style="Checkpoint.Treeview")
        self.tree.column("#0", minwidth=320, width=490, stretch=True)
        self.tree.pack(fill="both", expand=True)
        self._bind_wheel(self.tree, self._scroll_saves)
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._render_details())
        self.tree.bind("<Double-1>", lambda _event: self.start_selected_game())
        self.tree.bind("<Button-3>", self._show_save_menu)
        details_container = tk.Frame(info_content, bg=SURFACE, width=310)
        details_container.pack(side="right", fill="both")
        details_container.pack_propagate(False)
        self.details_canvas = tk.Canvas(details_container, bg=SURFACE,
                                        highlightthickness=0, bd=0)
        details_scroll = ttk.Scrollbar(details_container, orient="vertical",
                                       command=self.details_canvas.yview)
        self.details_canvas.configure(yscrollcommand=details_scroll.set)
        self.details_canvas.pack(side="left", fill="both", expand=True)
        details_scroll.pack(side="right", fill="y")
        self.details = tk.Frame(self.details_canvas, bg=SURFACE, padx=16, pady=16)
        details_window = self.details_canvas.create_window((0, 0), window=self.details, anchor="nw")
        self.details.bind("<Configure>", lambda _event: self.details_canvas.configure(
            scrollregion=self.details_canvas.bbox("all")))
        self.details_canvas.bind("<Configure>", lambda event: self.details_canvas.itemconfigure(
            details_window, width=event.width))
        self.save_menu = tk.Menu(self, tearoff=False, bg=PANEL, fg=TEXT,
                                 activebackground="#454545", activeforeground=TEXT)
        self.save_menu.add_command(label="Start Game", command=self.start_selected_game)
        self.save_menu.add_command(label="Rename Save Title", command=self.rename_save_title)
        self.save_menu.add_command(label="Favorite", command=self.favorite)
        self.save_menu.add_command(label="Export Save", command=self.export_selected)
        self.save_menu.add_separator()
        self.save_menu.add_command(label="Delete", command=self.delete_save)

        actions = ttk.Frame(outer)
        self.actions = actions
        actions.pack(fill="x", pady=(12, 10))
        self.pause_button = ttk.Button(actions, text="Pause co-op", command=self.toggle_coop_pause)
        self.pause_button.pack(side="left")
        self.overwrite_button = tk.Button(actions, command=self.toggle_overwrite,
                                          bg=PANEL, activebackground="#383838",
                                          font=("Segoe UI", 10, "bold"), padx=12, pady=7,
                                          bd=0, highlightthickness=0, cursor="hand2")
        self.overwrite_button.pack(side="left", padx=(8, 0))
        self._update_overwrite_button()
        self.auto_save_button = ttk.Button(actions, command=self.toggle_save_timing)
        self.auto_save_button.pack(side="left", padx=(8, 0))
        self._update_auto_save_button()
        self.cancel_start_button = ttk.Button(actions, text="Cancel start", command=self.cancel_start,
                                               state="disabled")
        self.cancel_start_button.pack(side="left", padx=(8, 0))
        options = ttk.Frame(outer)
        options.pack(fill="x", pady=(0, 10))
        ttk.Label(options, text="FoV").pack(side="left", padx=(0, 4))
        self.fov_entry = ttk.Spinbox(options, from_=1, to=360, increment=1,
                                      textvariable=self.fov_value, width=4,
                                      command=self._commit_fov)
        self.fov_entry.pack(side="left")
        ttk.Label(options, text="Scale").pack(side="left", padx=(6, 4))
        self.fov_scale_entry = ttk.Spinbox(options, from_=1.0, to=2.0, increment=0.05,
                                            textvariable=self.fov_scale, width=4,
                                            command=self._commit_fov)
        self.fov_scale_entry.pack(side="left")
        for field in (self.fov_entry, self.fov_scale_entry):
            field.bind("<Return>", self._commit_fov)
            field.bind("<FocusOut>", self._commit_fov)
        self.fov_button = tk.Button(options, command=self.toggle_fov,
                                    bg=PANEL, activebackground="#383838",
                                    font=("Segoe UI", 10, "bold"), padx=10, pady=7,
                                    bd=0, highlightthickness=0, cursor="hand2")
        self.fov_button.pack(side="left", padx=(6, 0))
        self._update_fov_button()
        self.install_button = ttk.Button(options, text="Install Game Save mod",
                                         command=self.install_mod)
        self.install_button.pack(side="right")
        self.display_box = ttk.Combobox(options, textvariable=self.display_mode,
                                        values=DISPLAY_MODES, state="readonly", width=11)
        self.display_box.pack(side="right", padx=(0, 8))
        self.display_box.bind("<<ComboboxSelected>>", self._select_display_mode)
        ttk.Label(options, text="Display").pack(side="right", padx=(0, 5))

        status_frame = tk.Frame(self, bg=SURFACE, padx=19, pady=11)
        status_frame.pack(fill="x")
        tk.Label(status_frame, textvariable=self.status, bg=SURFACE, fg=MUTED,
                 font=("Segoe UI", 10), anchor="w", wraplength=1000,
                 justify="left").pack(fill="x")

    @staticmethod
    def _bind_wheel(widget, callback):
        widget.bind("<MouseWheel>", callback)
        widget.bind("<Button-4>", callback)
        widget.bind("<Button-5>", callback)

    @staticmethod
    def _wheel_steps(event):
        if getattr(event, "num", None) == 4:
            return -1
        if getattr(event, "num", None) == 5:
            return 1
        return -int(event.delta / 120) if getattr(event, "delta", 0) else 0

    def _scroll_gallery(self, event):
        self.gallery_canvas.yview_scroll(self._wheel_steps(event), "units")
        return "break"

    def _scroll_saves(self, event):
        self.tree.yview_scroll(self._wheel_steps(event), "units")
        return "break"

    def _update_overwrite_button(self):
        overwrite = self.save_policy.get() == "Replace started save"
        self.overwrite_button.configure(
            text=("✓ " if overwrite else "✕ ") + "Overwrite Game Saves",
            fg="#6dda82" if overwrite else "#f07575",
            activeforeground="#6dda82" if overwrite else "#f07575")

    def toggle_overwrite(self):
        self.save_policy.set("Keep new saves" if self.save_policy.get() == "Replace started save"
                             else "Replace started save")
        self.library.data["save_policy"] = self.save_policy.get()
        self.library.write()
        self._update_overwrite_button()
        self.status.set("New checkpoints will overwrite the started save." if
                        self.save_policy.get() == "Replace started save" else
                        "New checkpoints will be kept as separate saves.")

    def _update_auto_save_button(self):
        self.auto_save_button.configure(text=f"Auto Save Settings: {self.save_timing.get()}")

    def toggle_save_timing(self):
        current = core.SAVE_TIMINGS.index(self.save_timing.get())
        self.save_timing.set(core.SAVE_TIMINGS[(current + 1) % len(core.SAVE_TIMINGS)])
        self.library.data["save_timing"] = self.save_timing.get()
        self.library.write()
        self._update_auto_save_button()
        self.status.set(f"Automatic checkpoints will save at: {self.save_timing.get().lower()}.")
        if self.watch_stop:
            self.watch_stop.set()

    def install_mod(self):
        if self.busy:
            return
        if core.game_pid() is not None:
            messagebox.showinfo("Close Black Ops first",
                                "Close Black Ops before installing Game Save. Your existing checkpoints will be copied safely.",
                                parent=self)
            return
        game = game_save_installer.find_game()
        if game is None:
            selected = filedialog.askdirectory(title="Select the Call of Duty Black Ops folder",
                                               parent=self)
            if not selected:
                return
            game = Path(selected)
        self._set_busy(True)
        self.install_button.configure(state="disabled")
        self.status.set(f"Installing Game Save in {game}...")

        def work():
            try:
                result = game_save_installer.install(core.ROOT, game)
            except Exception as error:
                self.events.put(("install_error", str(error)))
            else:
                self.events.put(("installed", result))
        threading.Thread(target=work, daemon=False).start()

    def _update_fov_button(self):
        self.fov_button.configure(text="FoV On" if self.fov_enabled else "FoV Off",
                                  fg="#6dda82" if self.fov_enabled else "#f07575",
                                  activeforeground="#6dda82" if self.fov_enabled else "#f07575")

    def _commit_fov(self, _event=None):
        try:
            fov, scale = fov_keeper.validate_settings(self.fov_value.get(), self.fov_scale.get())
        except (TypeError, ValueError) as error:
            messagebox.showerror("Check FoV", str(error), parent=self)
            return False
        self.fov_settings = (self.fov_enabled, fov, scale)
        self.library.data.update(fov_enabled=self.fov_enabled,
                                 fov_value=fov, fov_scale=scale)
        self.library.write()
        return True

    def toggle_fov(self):
        if not self._commit_fov():
            return
        self.fov_enabled = not self.fov_enabled
        self.fov_settings = (self.fov_enabled, self.fov_settings[1], self.fov_settings[2])
        self.library.data["fov_enabled"] = self.fov_enabled
        self.library.write()
        self._update_fov_button()
        self.status.set("FoV will be kept at the selected value while Black Ops is running."
                        if self.fov_enabled else "FoV changer turned off.")

    def _fov_loop(self):
        game = None
        attached_pid = None
        rejected_pid = None
        last_pid = None
        try:
            while not self.fov_stop.is_set():
                enabled, fov, scale = self.fov_settings
                try:
                    pid = core.game_pid() if enabled else None
                    if pid != last_pid:
                        rejected_pid = None
                        last_pid = pid
                    if pid != attached_pid:
                        if game is not None:
                            game.close()
                        game = None
                        attached_pid = None
                    if pid and pid != rejected_pid:
                        if game is None:
                            try:
                                game = core.GameProcess(pid, write=True)
                                attached_pid = pid
                            except RuntimeError as error:
                                rejected_pid = pid
                                self.events.put(("fov_error", str(error)))
                            except PermissionError as error:
                                rejected_pid = pid
                                self.events.put(("fov_error", str(error)))
                        if game is not None:
                            try:
                                fov_keeper.apply_fov(game, fov, scale)
                            except OSError:
                                # Pointers can be unavailable during map changes.
                                pass
                except (OSError, RuntimeError) as error:
                    self.events.put(("fov_error", str(error)))
                self.fov_stop.wait(1)
        finally:
            if game is not None:
                game.close()

    def _select_display_mode(self, _event=None):
        mode = self.display_mode.get()
        if mode not in DISPLAY_MODES:
            return
        self.library.data["display_mode"] = mode
        self.library.write()
        self.display_applied_mode = None
        self._request_display_mode(manual=True)

    def _request_display_mode(self, *, manual: bool = False):
        if self.closing or self.busy or self.display_working:
            if manual:
                self.status.set(f"{self.display_mode.get()} saved. It will apply after the current task finishes.")
            return
        pid = core.game_pid()
        if pid is None:
            if manual:
                self.status.set(f"{self.display_mode.get()} saved. It will apply when Black Ops starts.")
            return
        mode = self.display_mode.get()
        self.display_working = True
        self.display_last_attempt = time.monotonic()
        self.status.set(f"Switching Black Ops to {mode.lower()}...")

        def work():
            game = None
            try:
                game = core.GameProcess(pid)
                if mode == "Borderless":
                    if display_mode.is_fullscreen(pid):
                        game_launcher.wait_for_focus(game)
                        game.press_game_key(0x76, "F7 windowed mode")
                        display_mode.wait_for_windowed(pid)
                    if not display_mode.is_borderless(pid):
                        display_mode.make_borderless(pid)
                elif mode == "Fullscreen":
                    if not display_mode.is_fullscreen(pid):
                        game_launcher.wait_for_focus(game)
                        game.press_game_key(0x75, "F6 fullscreen")
                        display_mode.wait_for_fullscreen(pid)
                elif display_mode.is_fullscreen(pid) or display_mode.is_borderless(pid):
                    game_launcher.wait_for_focus(game)
                    game.press_game_key(0x76, "F7 windowed mode")
                    display_mode.wait_for_windowed(pid)
                self.events.put(("display_changed", mode, pid))
            except Exception as error:
                self.events.put(("display_error", str(error), mode, pid, manual))
            finally:
                if game is not None:
                    game.close()
        threading.Thread(target=work, daemon=False).start()

    def _ensure_display_mode(self):
        if self.closing:
            return
        try:
            if not self.busy and not self.display_working:
                pid = core.game_pid()
                if pid is not None and time.monotonic() - self.display_last_attempt >= 5:
                    mode = self.display_mode.get()
                    matches = ((mode == "Borderless" and display_mode.is_borderless(pid)) or
                               (mode == "Fullscreen" and display_mode.is_fullscreen(pid)) or
                               (mode == "Windowed" and not display_mode.is_fullscreen(pid) and
                                not display_mode.is_borderless(pid)))
                    if not matches:
                        self._request_display_mode()
                    else:
                        self.display_pid, self.display_applied_mode = pid, mode
        except (OSError, RuntimeError):
            pass  # The game window may be recreated while the map loads.
        self.after(2000, self._ensure_display_mode)

    def refresh(self):
        self.library.scan()
        selected = self.selected_name()
        self._render_gallery()
        self.tree.delete(*self.tree.get_children())
        if not self.current_map:
            return
        category = self.category.get()
        search = self.search.get().casefold().strip()
        profiles = {p["id"]: p for p in self.library.profiles()}
        saves = sorted(self.library.data["saves"].items(),
                       key=lambda item: item[1].get("saved_at", ""), reverse=True)
        for name, entry in saves:
            if entry.get("map") != self.current_map:
                continue
            if category == "Favorites" and not entry["favorite"]:
                continue
            if category == "Imported saves" and not entry.get("imported"):
                continue
            profile = profiles.get(entry["profile_id"], profiles["imported"])
            haystack = f"{entry['title']} {entry['map']} {profile['title']} {entry.get('round', '')}".casefold()
            if search and search not in haystack:
                continue
            count = entry.get("player_count") or len(entry.get("players", []))
            mode = entry.get("saved_mode") or profile["mode"]
            if count:
                mode = "Solo" if count == 1 else "Co-op"
            people = "Solo" if mode == "Solo" else (f"{count} players" if count else
                     ("Co-op" if mode == "Co-op" else "Players unknown"))
            title = (f"{'★  ' if entry['favorite'] else ''}{entry.get('title', 'Save Game')}"
                     f"    •    Round {entry['round']}    •    {people}"
                     f"    •    {save_date(entry.get('saved_at', ''))}")
            self.tree.insert("", "end", iid=name, text=title)
        if selected and self.tree.exists(selected):
            self.tree.selection_set(selected)
        elif self.tree.get_children():
            self.tree.selection_set(self.tree.get_children()[0])
        self._render_details()

    def _render_gallery(self):
        for child in self.gallery_grid.winfo_children():
            child.destroy()
        counts = {}
        for entry in self.library.data["saves"].values():
            if self.category.get() == "Imported saves" and not entry.get("imported"):
                continue
            counts[entry.get("map", "")] = counts.get(entry.get("map", ""), 0) + 1
        maps = list(MAP_ART) if self.category.get() != "Imported saves" else [
            name for name in MAP_ART if counts.get(name)]
        maps.extend(name for name in counts if name and name not in MAP_ART)
        for col in range(4):
            self.gallery_grid.columnconfigure(col, weight=1)
        for index, map_name in enumerate(maps):
            row, column = divmod(index, 4)
            card = tk.Frame(self.gallery_grid, bg=BG, width=220, height=184, cursor="hand2")
            card.grid(row=row, column=column, padx=9, pady=9, sticky="n")
            card.pack_propagate(False)
            art_name = MAP_ART.get(map_name, ("", None))[1]
            image_label = None
            if art_name:
                try:
                    if art_name not in self.map_images:
                        path = core.ROOT / "ui textures" / "png" / f"{art_name}.png"
                        self.map_images[art_name] = tk.PhotoImage(file=str(path)).subsample(2, 2)
                    image_label = tk.Label(card, image=self.map_images[art_name], bg=BG,
                                           cursor="hand2")
                    image_label.pack(pady=(7, 2))
                    image_label.bind("<Button-1>", lambda _event, key=map_name: self.show_map(key))
                except tk.TclError:
                    pass
            name_label = tk.Label(card, text=map_title(map_name), bg=BG, fg=TEXT,
                                  font=("Segoe UI", 10, "bold"), cursor="hand2")
            name_label.pack()
            count = counts.get(map_name, 0)
            count_label = tk.Label(card, text=f"{count} {'save' if count == 1 else 'saves'}",
                                   bg=BG, fg=MUTED, font=("Segoe UI", 9), cursor="hand2")
            count_label.pack(pady=(2, 0))
            for widget in (card, name_label, count_label):
                widget.bind("<Button-1>", lambda _event, key=map_name: self.show_map(key))
                self._bind_wheel(widget, self._scroll_gallery)
            if image_label is not None:
                self._bind_wheel(image_label, self._scroll_gallery)

    def show_map(self, map_name: str):
        self.current_map = map_name
        self.map_heading.configure(text=map_title(map_name))
        self.selected_map_caption.configure(text=map_title(map_name))
        art_name = MAP_ART.get(map_name, ("", None))[1]
        if art_name:
            try:
                key = f"full:{art_name}"
                if key not in self.map_images:
                    path = core.ROOT / "ui textures" / "png" / f"{art_name}.png"
                    self.map_images[key] = tk.PhotoImage(file=str(path))
                self.selected_map_art.configure(image=self.map_images[key])
            except tk.TclError:
                self.selected_map_art.configure(image="")
        else:
            self.selected_map_art.configure(image="")
        self.gallery_page.pack_forget()
        self.saves_page.pack(fill="both", expand=True, before=self.actions)
        self.refresh()

    def show_gallery(self):
        self.current_map = None
        self.saves_page.pack_forget()
        self.gallery_page.pack(fill="both", expand=True, before=self.actions)
        self.refresh()

    def start_new_game(self):
        if self.busy or not self.current_map:
            return
        map_name = self.current_map
        self.start_cancel = threading.Event()
        self.cancel_start_button.configure(state="normal")
        self._set_busy(True)
        self.status.set(f"Starting a new {map_title(map_name)} game...")

        def work():
            self._resume_coop_if_needed()
            if self.watch_stop:
                self.watch_stop.set()
            if self.watch_thread and self.watch_thread.is_alive():
                self.watch_thread.join()
            game = game_launcher.start_new_game(
                map_name, self.start_cancel,
                lambda message: self.events.put(("startup_status", message)))
            try:
                self.events.put(("new_game_started", map_name))
            finally:
                game.close()
        self._start_worker(work)

    def _render_details(self):
        for child in self.details.winfo_children():
            child.destroy()
        self.details_canvas.yview_moveto(0)
        name = self.selected_name()
        if not name or name not in self.library.data["saves"]:
            tk.Label(self.details, text="Select a checkpoint to see its details.", bg=SURFACE,
                     fg=MUTED, wraplength=245, justify="left").pack(anchor="w")
            return
        entry = self.library.data["saves"][name]
        profile = next((p for p in self.library.profiles() if p["id"] == entry["profile_id"]),
                       self.library.profiles()[0])
        title = entry.get("title") or "Save Game"
        tk.Label(self.details, text=title, bg=SURFACE, fg=TEXT,
                 font=("Segoe UI", 19, "bold")).pack(anchor="w")
        tk.Label(self.details, text=save_date(entry.get("saved_at", ""), long=True),
                 bg=SURFACE, fg=MUTED, font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 11))
        count = entry.get("player_count") or len(entry.get("players", []))
        mode = entry.get("saved_mode") or profile["mode"]
        description = "Solo · 1 player" if mode == "Solo" else (f"{count} players" if count else mode)
        for line in (f"Round {entry.get('round', '?')}", description, profile["title"]):
            tk.Label(self.details, text=line, bg=SURFACE, fg=MUTED, font=("Segoe UI", 10),
                     wraplength=245, justify="left").pack(anchor="w", pady=(0, 4))
        tk.Frame(self.details, bg=BORDER, height=1).pack(fill="x", pady=(11, 12))
        tk.Label(self.details, text="PLAYER STATS", bg=SURFACE, fg=ACCENT,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 8))
        players = entry.get("players") or []
        if not players:
            tk.Label(self.details, text="Player stats have not been recorded for this save.",
                     bg=SURFACE, fg=MUTED, wraplength=245, justify="left").pack(anchor="w", pady=(0, 12))
            players = [{"name": "Player 1"}] if mode == "Solo" else []
        for index, player in enumerate(players, 1):
            player_frame = tk.Frame(self.details, bg=PANEL, padx=10, pady=8)
            player_frame.pack(fill="x", pady=(0, 8))
            player_name = player.get("name") or f"Player {index}"
            if (index == 1 and not entry.get("imported") and
                    player_name.casefold().startswith("unknown soldier")):
                player_name = steam_identity.local_persona_name(core.GAME) or player_name
            tk.Label(player_frame, text=player_name, bg=PANEL,
                     fg=TEXT, font=("Segoe UI", 10, "bold")).pack(anchor="w")
            def value(key):
                result = player.get(key)
                return str(result) if result not in (None, "") else "—"
            tk.Label(player_frame, text=f"Points {value('points')}   Kills {value('kills')}   Downs {value('downs')}   Revives {value('revives')}",
                     bg=PANEL, fg=MUTED, font=("Segoe UI", 9), wraplength=245,
                     justify="left").pack(anchor="w", pady=(3, 0))
            tk.Label(player_frame, text=f"Weapons / loadout: {value('weapons')}",
                     bg=PANEL, fg=MUTED, font=("Segoe UI", 9), wraplength=245,
                     justify="left").pack(anchor="w", pady=(2, 0))
        ttk.Button(self.details, text="Start Game", command=self.start_selected_game).pack(
            anchor="w", pady=(9, 0))

    def selected_name(self) -> str | None:
        selection = self.tree.selection()
        return selection[0] if selection else None

    def _selected(self) -> tuple[str, dict] | None:
        name = self.selected_name()
        if not name:
            messagebox.showinfo("Select a save", "Select a save from the list first.", parent=self)
            return None
        return name, self.library.data["saves"][name]

    def _export_names(self, names: list[str]):
        if not names:
            messagebox.showinfo("Export saves", "There are no saves to export.", parent=self)
            return
        folder = filedialog.askdirectory(parent=self, title="Choose a folder for the exported saves")
        if not folder:
            return
        try:
            destination = self.library.export_saves(names, Path(folder))
        except (OSError, ValueError, KeyError) as error:
            messagebox.showerror("Export failed", str(error), parent=self)
            return
        self.status.set(f"Exported {len(names)} save(s) to {destination.name}")
        messagebox.showinfo("Export complete", f"Your portable save package is in:\n{destination}", parent=self)

    def export_selected(self):
        name = self.selected_name()
        if name:
            self._export_names([name])
        else:
            messagebox.showinfo("Export saves", "Select a save first.", parent=self)

    def export_all(self):
        names = [name for name, entry in self.library.data["saves"].items()
                 if self.category.get() != "Imported saves" or entry.get("imported")]
        self._export_names(names)

    def import_saves(self):
        paths = filedialog.askopenfilenames(
            parent=self, title="Choose portable Black Ops save packages",
            filetypes=[("Black Ops Game Saves", "*.bo1gamesave"), ("All files", "*.*")])
        if not paths:
            return
        added = []
        try:
            for path in paths:
                added.extend(self.library.import_saves(Path(path)))
        except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as error:
            self.refresh()
            messagebox.showerror("Import failed", str(error), parent=self)
            return
        self.category.set("Imported saves")
        if self.current_map and not any(self.library.data[name].get("map") == self.current_map for name in added):
            self.show_gallery()
        elif self.current_map:
            self.refresh()
        else:
            self.refresh()
        self.status.set(f"Imported {len(added)} save(s).")
        messagebox.showinfo("Import complete", f"Imported {len(added)} save(s) into Imported saves.", parent=self)

    def _show_save_menu(self, event):
        row = self.tree.identify_row(event.y)
        if not row:
            return
        self.tree.selection_set(row)
        self.tree.focus(row)
        entry = self.library.data["saves"][row]
        self.save_menu.entryconfigure(2, label="Remove Favorite" if entry["favorite"] else "Favorite")
        try:
            self.save_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.save_menu.grab_release()

    def rename_save_title(self):
        if self.busy:
            return
        chosen = self._selected()
        if not chosen:
            return
        name, entry = chosen
        title = simpledialog.askstring("Rename save", "New title:", initialvalue=entry["title"], parent=self)
        if title is None:
            return
        if not title.strip():
            messagebox.showerror("Title needed", "Enter a title for this save.", parent=self)
            return
        self.library.edit_save(name, title=title, profile_id=entry["profile_id"],
                               kind=entry["kind"], favorite=entry["favorite"])
        self.refresh()

    def favorite(self):
        if self.busy:
            return
        chosen = self._selected()
        if chosen:
            self.library.toggle_favorite(chosen[0])
            self.refresh()

    def delete_save(self):
        if self.busy:
            return
        chosen = self._selected()
        if not chosen:
            return
        name, entry = chosen
        if messagebox.askyesno("Delete save", f"Permanently delete ‘{entry['title']}’?",
                               parent=self):
            try:
                self.library.delete_save(name)
                if self.started_save_name == name:
                    self.started_save_name = None
                self.refresh()
                self.status.set(f"Deleted {entry['title']}.")
            except OSError as error:
                messagebox.showerror("Delete failed", str(error), parent=self)

    def _mode_for_save(self, entry: dict) -> str | None:
        mode = entry.get("saved_mode") or self.library.profile(entry["profile_id"])["mode"]
        count = entry.get("player_count") or len(entry.get("players", []))
        if count:
            mode = "Solo" if count == 1 else "Co-op"
        if mode == "Unknown":
            solo = messagebox.askyesnocancel(
                "Choose a mode", "Was this imported checkpoint saved in Solo?\n\nYes: Solo    No: Co-op    Cancel: do not load",
                parent=self)
            if solo is None:
                return None
            mode = "Solo" if solo else "Co-op"
        return mode

    def _resume_coop_if_needed(self):
        if not self.coop_paused:
            return
        pid = core.game_pid()
        if pid != self.coop_pause_pid:
            self.coop_paused = False
            self.coop_pause_pid = None
            self.events.put(("coop_pause_changed", False, None))
            return
        game = core.GameProcess(pid)
        try:
            game_launcher.wait_for_focus(game)
            game.press_coop_resume()
            time.sleep(0.4)
        finally:
            game.close()
        self.coop_paused = False
        self.coop_pause_pid = None
        self.events.put(("coop_pause_changed", False, None))

    def toggle_coop_pause(self):
        if self.busy or self.pending_coop:
            return
        if not self.coop_paused:
            legacy_source = (game_launcher.SCRIPT_VARIANTS / "_zombiemode_legacy.gsc").read_bytes()
            if (self.current_session_legacy or
                    (self.current_session_legacy is None and
                     game_launcher.SCRIPT_SOURCE.read_bytes() == legacy_source)):
                messagebox.showinfo(
                    "Original checkpoint scripts",
                    "This game uses the original scripts required by its saved checkpoint. "
                    "The co-op pause control is available in new games with the updated scripts.",
                    parent=self)
                return
        self._set_busy(True)

        def work():
            if self.coop_paused:
                self._resume_coop_if_needed()
                return
            if self.watch_stop:
                self.watch_stop.set()
            if self.watch_thread and self.watch_thread.is_alive():
                self.watch_thread.join()
            pid = core.game_pid()
            if not pid:
                raise RuntimeError("Black Ops is not running. Start a Co-op game first.")
            game = core.GameProcess(pid)
            try:
                if core.live_round(game) is None:
                    raise RuntimeError("Wait until the Co-op map is playable before pausing.")
                game_launcher.wait_for_focus(game)
                game.press_coop_pause()
            finally:
                game.close()
            self.coop_paused = True
            self.coop_pause_pid = pid
            self.events.put(("coop_pause_changed", True, pid))

        self._start_worker(work)

    def start_selected_game(self):
        if self.busy:
            return
        chosen = self._selected()
        if not chosen:
            return
        name, entry = chosen
        if entry.get("error"):
            messagebox.showerror("Invalid save", entry["error"], parent=self)
            return
        mode = self._mode_for_save(entry)
        if mode is None:
            return
        self.pending_coop = None
        self.start_cancel = threading.Event()
        self.cancel_start_button.configure(state="normal")
        self._set_busy(True)
        self.status.set(f"Starting {entry['title']} with the selected map and Game Save mod...")
        save_path = core.ARCHIVE / name

        def work():
            self._resume_coop_if_needed()
            if self.watch_stop:
                self.watch_stop.set()
            if self.watch_thread and self.watch_thread.is_alive():
                self.watch_thread.join()
            game, metadata = game_launcher.start_selected_game(
                save_path, mode, self.start_cancel,
                lambda message: self.events.put(("startup_status", message)))
            try:
                if mode == "Co-op":
                    self.events.put(("coop_waiting", name, entry["title"], metadata["round"],
                                     entry["profile_id"], game_launcher.legacy_scripts(metadata)))
                    return
                self.events.put(("startup_status", "Map ready. Making a fresh checkpoint, then restoring your save..."))
                game_launcher.restore_and_continue(game, save_path, mode, self.start_cancel)
                self.events.put(("start_loaded", name, entry["title"], metadata["round"],
                                 entry["profile_id"], game_launcher.legacy_scripts(metadata)))
            finally:
                game.close()
        self._start_worker(work)

    def _ask_coop_ready(self):
        if not self.pending_coop or self.closing:
            return
        ready = messagebox.askokcancel(
            "Co-op players", "The map is ready. Have every player rejoin, then choose OK to load the saved game.",
            parent=self)
        if ready:
            self.continue_coop()
        else:
            self.cancel_start()

    def continue_coop(self):
        if self.busy or not self.pending_coop:
            return
        name, title, round_number, profile_id = self.pending_coop
        self.start_cancel = threading.Event()
        self.cancel_start_button.configure(state="normal")
        self._set_busy(True)
        self.status.set("Checking the co-op map and saving all joined players before restore...")

        def work():
            pid = core.game_pid()
            if not pid:
                raise RuntimeError("Black Ops closed. Use Start Game to launch this save again.")
            game = core.GameProcess(pid, write=True, suspend=True)
            try:
                save_path = core.ARCHIVE / name
                metadata, _ = core.load_archive(save_path)
                game_launcher.wait_for_map_ready(game, metadata["map"], self.start_cancel)
                game_launcher.restore_and_continue(game, save_path, "Co-op", self.start_cancel)
                self.events.put(("start_loaded", name, title, round_number, profile_id,
                                 game_launcher.legacy_scripts(metadata)))
            finally:
                game.close()
        self._start_worker(work)

    def cancel_start(self):
        if self.start_cancel:
            self.start_cancel.set()
            self.status.set("Canceling the start process...")
        elif self.pending_coop:
            self.pending_coop = None
            self.status.set("Co-op resume canceled. Black Ops remains open.")
            self._start_watch()

    def _set_busy(self, busy: bool):
        self.busy = busy

    def _start_worker(self, function):
        def run():
            try:
                function()
            except Exception as error:
                self.events.put(("error", str(error)))
        threading.Thread(target=run, daemon=False).start()

    def _start_watch(self):
        if (self.closing or self.busy or self.pending_coop or self.coop_paused
                or (self.watch_thread and self.watch_thread.is_alive())):
            return
        self.watch_stop = threading.Event()
        skip_round = self.skip_initial_round
        save_timing = self.save_timing.get()

        def work():
            try:
                def callback(event, _round, path):
                    if event in ("saved", "manual", "recovery"):
                        kind = "manual" if event == "manual" else "auto"
                        profile_id = self.library.data["active_profile"]
                        self.events.put(("saved", path, kind, profile_id, None))
                    elif event == "round_seen":
                        self.events.put(("watch_round", _round))
                    elif event == "round_end":
                        self.events.put(("watch_end", _round))
                    elif event == "error":
                        self.events.put(("watch_error", _round))
                core.watch(None, self.watch_stop, callback, self.save_lock,
                           skip_initial_round=skip_round, enable_recovery=False,
                           save_timing=save_timing)
            except Exception as error:
                self.events.put(("watch_error", str(error)))
            finally:
                self.events.put(("watch_stopped",))
        self.watch_thread = threading.Thread(target=work, daemon=True)
        self.watch_thread.start()

    def _poll_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "saved":
                    _, path, save_kind, profile_id, title = event
                    try:
                        if (self.started_save_name and
                                self.save_policy.get() == "Replace started save"):
                            try:
                                details = self.library.replace_save(path, self.started_save_name)
                            except (FileNotFoundError, ValueError):
                                self.started_save_name = None
                                details = self.library.register(path, kind=save_kind,
                                                                profile_id=profile_id, title=title)
                        else:
                            details = self.library.register(path, kind=save_kind,
                                                            profile_id=profile_id, title=title)
                        if details["round"] != self.skip_initial_round:
                            self.skip_initial_round = None
                        self.refresh()
                        when = datetime.fromisoformat(details["saved_at"]).strftime("%I:%M %p")
                        self.status.set(f"Saved {details['map']} at {when}.")
                    except Exception as error:
                        messagebox.showerror("Save catalog error", str(error), parent=self)
                elif kind == "watch_error":
                    self.status.set(f"Saving: {event[1]}")
                elif kind == "install_error":
                    self._set_busy(False)
                    self.install_button.configure(state="normal")
                    self.status.set(f"Installation failed: {event[1]}")
                    messagebox.showerror("Game Save installation failed", event[1], parent=self)
                elif kind == "installed":
                    result = event[1]
                    target = result["target"]
                    self._set_busy(False)
                    self.install_button.configure(state="normal")
                    self.status.set(f"Game Save installed in {target}. "
                                    f"Copied {result['saves']} existing save files.")
                    if target.resolve() != core.ROOT.resolve():
                        self.launch_after_close = target
                        self.after(500, self.close)
                elif kind == "fov_error":
                    if self.fov_enabled:
                        self.status.set(f"FoV changer: {event[1]}")
                elif kind == "display_error":
                    self.display_working = False
                    self.status.set(f"Could not change display mode: {event[1]}")
                    if event[4]:
                        messagebox.showerror("Display mode", event[1], parent=self)
                elif kind == "display_changed":
                    self.display_working = False
                    self.display_applied_mode, self.display_pid = event[1], event[2]
                    self.status.set(f"{event[1]} display enabled.")
                elif kind == "watch_round":
                    if not self.busy:
                        self.status.set(f"Watching round {event[1]}. Auto save: {self.save_timing.get().lower()}; F11 saves manually.")
                elif kind == "watch_end":
                    self.status.set(f"Round {event[1]} ended. Saving checkpoint…")
                elif kind == "watch_stopped":
                    if not self.busy and not self.closing and not self.pending_coop and not self.coop_paused:
                        self.after(1000, self._start_watch)
                elif kind == "coop_pause_changed":
                    if self.start_cancel is None:
                        self._set_busy(False)
                    self.pause_button.configure(text="Resume co-op" if event[1] else "Pause co-op")
                    self.status.set("Co-op pause requested. It engages with two or more players; confirm in game."
                                    if event[1] else "Co-op resume requested. Saving continues automatically.")
                    if not event[1]:
                        self._start_watch()
                elif kind == "startup_status":
                    self.status.set(event[1])
                elif kind == "coop_waiting":
                    _, name, title, round_number, profile_id, legacy = event
                    self.pending_coop = (name, title, round_number, profile_id)
                    self.current_session_legacy = legacy
                    self.start_cancel = None
                    self.cancel_start_button.configure(state="disabled")
                    self._set_busy(False)
                    self.status.set(f"{title} is on the matching map. Waiting for all co-op players to rejoin.")
                    self.after(100, self._ask_coop_ready)
                elif kind == "start_loaded":
                    _, name, title, round_number, profile_id, legacy = event
                    self.current_session_legacy = legacy
                    self.pending_coop = None
                    self.started_save_name = name
                    self.skip_initial_round = round_number
                    self.start_cancel = None
                    self.cancel_start_button.configure(state="disabled")
                    self._set_busy(False)
                    self.library.set_active_profile(profile_id)
                    self.refresh()
                    self.status.set(f"Loaded {title}. Auto save: {self.save_timing.get().lower()}; F11 saves manually.")
                    self._start_watch()
                elif kind == "new_game_started":
                    map_name = event[1]
                    self.started_save_name = None
                    self.skip_initial_round = None
                    self.current_session_legacy = False
                    self.start_cancel = None
                    self.cancel_start_button.configure(state="disabled")
                    self.library.new_profile(
                        f"{map_title(map_name)} · {datetime.now():%b %d, %Y %I:%M %p}", "Solo")
                    self._set_busy(False)
                    self.refresh()
                    self.status.set(f"New {map_title(map_name)} game started. Auto save: {self.save_timing.get().lower()}.")
                    self._start_watch()
                elif kind == "restored":
                    self.status.set(f"Restored {event[1]}. Switch to Black Ops within 15 seconds; the UI will press F12 to continue.")
                elif kind == "loaded":
                    self._set_busy(False)
                    self.status.set(f"Continued {event[1]}. Saving continues automatically.")
                    self._start_watch()
                elif kind == "restored_manual":
                    self._set_busy(False)
                    self.status.set(f"Restored {event[1]}. In Black Ops, press F12 or run loadgame_continue to continue.")
                    self._start_watch()
                elif kind == "error":
                    self.start_cancel = None
                    self.skip_initial_round = None
                    self.started_save_name = None
                    self.cancel_start_button.configure(state="disabled")
                    self._set_busy(False)
                    self.status.set(event[1])
                    messagebox.showerror("Checkpoint error", event[1], parent=self)
                    self._start_watch()
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    def close(self):
        if self.busy:
            messagebox.showinfo("Checkpoint in progress", "Wait for the current save or load to finish before closing.", parent=self)
            return
        if self.coop_paused:
            try:
                self._resume_coop_if_needed()
            except Exception as error:
                messagebox.showerror("Resume Co-op first", str(error) + "\n\nYou can also press F8 in Black Ops.", parent=self)
                return
        self.closing = True
        self.fov_stop.set()
        if self.watch_stop:
            self.watch_stop.set()
        if self.watch_thread and self.watch_thread.is_alive():
            self.status.set("Finishing save monitoring before closing...")
            self.after(150, self.close)
            return
        target = self.launch_after_close
        self.destroy()
        if target is not None:
            installed_exe = target / "BlackOpsGameSaves.exe"
            command = ([str(installed_exe)] if installed_exe.is_file() else
                       [sys.executable, str(target / "checkpoint_gui.py")])
            if sys.platform == "win32" and ctypes.windll.shell32.IsUserAnAdmin():
                command.append("--elevated")
            try:
                subprocess.Popen(command, cwd=target)
            except OSError as error:
                messagebox.showerror("Open Game Save", f"Installed the mod, but could not open it: {error}")


def main():
    if "--smoke" not in sys.argv and "--elevated" not in sys.argv:
        if launch_as_administrator():
            return
    app = CheckpointApp()
    if "--smoke" in sys.argv:
        app.withdraw()
        app.show_map("zombie_cod5_factory")
        app.update()
        app.show_gallery()
        app.update()
        app.destroy()
    else:
        app.mainloop()


if __name__ == "__main__":
    main()
