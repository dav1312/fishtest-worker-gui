import customtkinter as ctk
import tkinter.scrolledtext
import tkinter.messagebox
import subprocess
import threading
import os
import sys
import ctypes
from ctypes import wintypes
import configparser
import webbrowser
import re
import time
import json
import netrc
import urllib.request
import tempfile

# --- Constants ---
APP_NAME = "Fishtest Worker Manager"
APP_VERSION = "v1.1.1"
REPO_OWNER = "dav1312"
REPO_NAME = "fishtest-worker-gui"

WORKER_DIR = os.path.abspath("worker")
CONFIG_FILE_NAME = "fishtest.cfg"
CONFIG_FILE = os.path.join(WORKER_DIR, CONFIG_FILE_NAME)
EXIT_FILE_NAME = "fish.exit"
MSYS2_PATH = "C:\\msys64"
# Keep in sync with the packages installed by setup_msys2.cmd
MSYS2_REQUIRED_FILES = (
    "msys2_shell.cmd",
    os.path.join("usr", "bin", "wget.exe"),
    os.path.join("usr", "bin", "unzip.exe"),
    os.path.join("usr", "bin", "make.exe"),
    os.path.join("ucrt64", "bin", "gcc.exe"),
    os.path.join("ucrt64", "bin", "python3.exe"),
)
USERNAME_DEFAULT = "your_username"
GITHUB_NETRC_HOST = "api.github.com"
# Matches one "machine api.github.com ..." entry up to the next netrc entry (or end of file)
GITHUB_NETRC_ENTRY_RE = re.compile(
    r"(?<!\S)machine\s+api\.github\.com(?!\S).*?(?=(?<!\S)(?:machine|default|macdef)(?!\S)|\Z)",
    re.DOTALL)

# --- Theme ---
COLOR_BG = "#0F1218"
COLOR_SIDEBAR = "#0B0D12"
COLOR_BORDER = "#222835"
COLOR_PANEL = "#161A22"
COLOR_INPUT_BORDER = "#2E3546"
COLOR_TEXT = "#E9ECF2"
COLOR_TEXT_NAV = "#C3C9D6"
COLOR_TEXT_MUTED = "#7E8798"
COLOR_TEXT_DISABLED = "#4A5160"
COLOR_NAV_HOVER = "#171B24"
COLOR_NAV_SELECTED = "#1F2638"
COLOR_ACCENT = "#238A4F"
COLOR_ACCENT_HOVER = "#1C7242"
COLOR_ACCENT_DISABLED = "#1C3A2A"
COLOR_ACCENT_TEXT = "#6FD39A"
COLOR_DANGER = "#E5484D"
COLOR_DANGER_HOVER = "#C93C41"
COLOR_DANGER_TEXT = "#FF7A80"
COLOR_STATE = {"idle": "#7E8798", "running": "#4ADE80", "busy": "#E0A93B"}

SEE_MASK_NOCLOSEPROCESS = 0x00000040
SW_HIDE = 0

class SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", wintypes.ULONG),
        ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", wintypes.LPVOID),
        ("lpClass", wintypes.LPCWSTR),
        ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD),
        ("hIconOrMonitor", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]

try:
    OEM_CODEPAGE = f"cp{ctypes.windll.kernel32.GetOEMCP()}"
except Exception:
    OEM_CODEPAGE = "cp1252"

def decode_output(raw_bytes: bytes) -> str:
    """ Decodes stdout bytes, trying UTF-8 first, falling back to the Windows console OEM code page. """
    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return raw_bytes.decode(OEM_CODEPAGE, errors="replace")

def get_asset_path(relative_path):
    """ Get absolute path to asset, works for dev and for PyInstaller """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, "assets", relative_path)

def windows_to_msys2_path(path):
    # Converts C:\Users\... to /c/Users/...
    drive, rest = os.path.splitdrive(os.path.abspath(path))
    drive_letter = drive.rstrip(":\\/").lower()
    rest = rest.replace("\\", "/").lstrip("/\\")
    return f"/{drive_letter}/{rest}"

def is_msys2_ready():
    """ True if MSYS2 and all the packages the worker needs are installed. """
    return all(os.path.exists(os.path.join(MSYS2_PATH, f)) for f in MSYS2_REQUIRED_FILES)

def validate_concurrency(value):
    """ Returns an error message if the concurrency is invalid, otherwise None.
        Plain numbers get the worker's full check. Expressions only get a basic character
        check, since evaluating them needs the worker's parser; the worker validates them. """
    max_cores = os.cpu_count() or 1
    if not value:
        return "Concurrency cannot be empty."
    if re.fullmatch(r"[0-9]+", value):
        cores = int(value)
        if cores < 1:
            return "Concurrency must be at least 1."
        # Same rule as the worker: using all cores requires writing 'MAX' explicitly
        if cores >= max_cores:
            if max_cores == 1:
                return "This computer has 1 core. Use 'MAX' to use it."
            return f"Concurrency can be at most {max_cores - 1}, or 'MAX' to use all {max_cores} cores."
        return None
    if (not re.fullmatch(r"[A-Za-z0-9\s.,()+\-*/]+", value) or "**" in value
            or not set(re.findall(r"[A-Za-z_]+", value)) <= {"MAX", "min", "max"}):
        return "Concurrency must be a number or an expression using MAX, min, max, numbers and + - * / ( )."
    return None

def concurrency_help():
    """ One-line hint about the concurrency values this computer accepts. """
    max_cores = os.cpu_count() or 1
    if max_cores == 1:
        return "This computer has 1 core. Use MAX to use it."
    return f"This computer has {max_cores} cores. Use 1 to {max_cores - 1}, or MAX for all {max_cores}."

def get_netrc_path():
    """ Returns the netrc file that requests (used by the worker) will read. """
    if os.environ.get("NETRC"):
        return os.environ["NETRC"]
    home = os.path.expanduser("~")
    for name in (".netrc", "_netrc"):
        path = os.path.join(home, name)
        if os.path.exists(path):
            return path
    return os.path.join(home, "_netrc")

def read_github_token():
    """ Returns the GitHub token stored in the netrc file, or '' if there is none. """
    try:
        auth = netrc.netrc(get_netrc_path()).authenticators(GITHUB_NETRC_HOST)
    except (OSError, netrc.NetrcParseError, UnicodeDecodeError):
        return ""
    return auth[0] if auth else ""

def write_github_token(token):
    """ Adds, replaces or (if token is empty) removes the api.github.com entry, keeping all other entries. """
    path = get_netrc_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        content = ""

    content = GITHUB_NETRC_ENTRY_RE.sub("", content).rstrip()
    if token:
        entry = f"machine {GITHUB_NETRC_HOST}\nlogin {token}\npassword x-oauth-basic"
        content = f"{content}\n{entry}" if content else entry

    if content:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content + "\n")
    elif os.path.exists(path):
        os.remove(path)
    return path

class FishtestManagerApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.worker_process = None
        self.is_long_operation_running = False
        self.is_stopping_gracefully = False
        # Same settings as the worker's own parser: '%' is a literal character and ';' starts an inline comment
        self.config = configparser.ConfigParser(inline_comment_prefixes=";", interpolation=None)
        self.task_total_games = 0
        self.task_current_games = 0
        self.task_start_time = None

        self._setup_window()
        self._create_widgets()
        self._load_config()
        self.after(100, self._initial_environment_check)
        self.after(101, self._update_all_controls_state) # Defer check to allow window to draw

        # Start update check in background
        self.after(2000, lambda: threading.Thread(target=self._check_latest_version_thread, daemon=True).start())

        self.protocol("WM_DELETE_WINDOW", self._on_closing)

    def _is_admin(self):
        try:
            return ctypes.windll.shell32.IsUserAnAdmin()
        except:
            return False

    def _setup_window(self):
        self.title(f"{APP_NAME} ({APP_VERSION})")
        self.geometry("920x650")
        self.minsize(780, 520)
        self.configure(fg_color=COLOR_BG)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.iconbitmap(get_asset_path("icon.ico"))

    def _create_widgets(self):
        self._create_sidebar()

        # --- Main area: the dashboard and the settings page share one grid cell ---
        main_frame = ctk.CTkFrame(self, fg_color="transparent")
        main_frame.grid(row=0, column=1, sticky="nsew")
        main_frame.grid_columnconfigure(0, weight=1)
        main_frame.grid_rowconfigure(0, weight=1)

        self.dash_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        self.dash_frame.grid(row=0, column=0, sticky="nsew", padx=18, pady=18)
        self.settings_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        self.settings_frame.grid(row=0, column=0, sticky="nsew", padx=28, pady=22)
        self._create_dashboard()
        self._create_settings_page()
        self._show_view("dashboard")

    def _create_sidebar(self):
        sidebar = ctk.CTkFrame(self, width=220, corner_radius=0, fg_color=COLOR_SIDEBAR)
        sidebar.grid(row=0, column=0, sticky="nsw")
        sidebar.grid_propagate(False)
        sidebar.grid_columnconfigure(0, weight=1)
        sidebar.grid_rowconfigure(5, weight=1) # Pushes the bottom buttons down

        fishtest_label = ctk.CTkLabel(sidebar, text="Fishtest", font=("Arial", 15, "bold"), anchor="w", cursor="hand2")
        fishtest_label.grid(row=0, column=0, padx=22, pady=(18, 14), sticky="ew")
        fishtest_label.bind("<Button-1>", lambda e: webbrowser.open("https://tests.stockfishchess.org/tests"))

        self.dashboard_button = self._create_nav_button(sidebar, "Dashboard", lambda: self._show_view("dashboard"))
        self.dashboard_button.grid(row=1, column=0, padx=12, pady=2, sticky="ew")
        self.settings_button = self._create_nav_button(sidebar, "Settings", self._show_settings)
        self.settings_button.grid(row=2, column=0, padx=12, pady=2, sticky="ew")

        ctk.CTkFrame(sidebar, height=1, fg_color=COLOR_BORDER).grid(row=3, column=0, padx=18, pady=10, sticky="ew")

        self.setup_button = self._create_nav_button(sidebar, "Install/Re-Install Worker", self._run_full_setup)
        self.setup_button.grid(row=4, column=0, padx=12, pady=2, sticky="ew")
        self.update_button = self._create_nav_button(sidebar, "Update MSYS2 Environment", self._update_msys2)
        self.update_button.grid(row=5, column=0, padx=12, pady=2, sticky="new")

        # Hidden by default
        self.new_version_button = ctk.CTkButton(sidebar, text="Update available", command=self._open_release_page,
                                                fg_color="transparent", border_width=1, border_color=COLOR_ACCENT,
                                                text_color=COLOR_ACCENT_TEXT, hover_color=COLOR_NAV_HOVER, height=34, corner_radius=6)
        self.new_version_button.grid(row=6, column=0, padx=12, pady=(0, 6), sticky="ew")
        self.new_version_button.grid_remove()

        issues_label = ctk.CTkLabel(sidebar, text="Report an issue on GitHub", font=("Arial", 12, "underline"),
                                    text_color=COLOR_TEXT_MUTED, cursor="hand2")
        issues_label.grid(row=7, column=0, padx=12, pady=(6, 4), sticky="ew")
        issues_label.bind("<Button-1>", lambda e: webbrowser.open(f"https://github.com/{REPO_OWNER}/{REPO_NAME}/issues"))

        self.uninstall_button = self._create_nav_button(sidebar, "Uninstall...", self._handle_uninstall_click, text_color=COLOR_DANGER_TEXT)
        self.uninstall_button.grid(row=8, column=0, padx=12, pady=(2, 14), sticky="ew")

    def _create_nav_button(self, parent, text, command, text_color=COLOR_TEXT_NAV):
        return ctk.CTkButton(parent, text=text, command=command, anchor="w", height=36, corner_radius=6,
                             fg_color="transparent", hover_color=COLOR_NAV_HOVER,
                             text_color=text_color, text_color_disabled=COLOR_TEXT_DISABLED)

    def _create_dashboard(self):
        frame = self.dash_frame
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        # --- Worker control card ---
        card = ctk.CTkFrame(frame, corner_radius=6, fg_color=COLOR_PANEL, border_width=1, border_color=COLOR_BORDER)
        card.grid(row=0, column=0, sticky="ew")
        card.grid_columnconfigure(0, weight=1)

        info = ctk.CTkFrame(card, fg_color="transparent")
        info.grid(row=0, column=0, padx=(18, 10), pady=16, sticky="ew")
        info.grid_columnconfigure(0, weight=1)

        state_row = ctk.CTkFrame(info, fg_color="transparent")
        state_row.grid(row=0, column=0, sticky="w")
        self.state_dot = ctk.CTkLabel(state_row, text="●", font=("Arial", 14), text_color=COLOR_STATE["idle"])
        self.state_dot.pack(side="left")
        self.state_label = ctk.CTkLabel(state_row, text="Idle", font=("Arial", 16, "bold"))
        self.state_label.pack(side="left", padx=(6, 0))
        self.who_label = ctk.CTkLabel(state_row, text="", text_color=COLOR_TEXT_MUTED)
        self.who_label.pack(side="left", padx=(8, 0))

        # --- Progress bar for worker tasks ---
        self.task_progress_label = ctk.CTkLabel(info, text="", font=("Arial", 12), text_color=COLOR_TEXT_MUTED, anchor="w")
        self.task_progress_label.grid(row=1, column=0, pady=(10, 0), sticky="ew")

        self.task_progress_bar = ctk.CTkProgressBar(info, height=8, progress_color=COLOR_ACCENT, fg_color="#232937")
        self.task_progress_bar.grid(row=2, column=0, pady=(4, 0), sticky="ew")
        self.task_progress_bar.set(0)

        # Initially hide them until the worker starts
        self.task_progress_label.grid_remove()
        self.task_progress_bar.grid_remove()

        can_start = is_msys2_ready() and os.path.exists(os.path.join(WORKER_DIR, "worker.py"))
        button_text = "START WORKER" if can_start else "INSTALL WORKER"
        self.worker_button = ctk.CTkButton(card, text=button_text, command=self._toggle_worker, width=170, height=44, corner_radius=6,
                                           font=("Arial", 14, "bold"), fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER)
        self.worker_button.grid(row=0, column=1, padx=(10, 18), pady=16)
        self.worker_button.bind("<Button-3>", self._force_stop_worker_event) # Right-click to force stop

        # --- Log ---
        self.log_text = ctk.CTkTextbox(frame, wrap=ctk.WORD, state='disabled', corner_radius=6,
                                       fg_color=COLOR_PANEL, border_width=1, border_color=COLOR_BORDER,
                                       text_color="#D0D5E0", font=("Consolas", 12))
        self.log_text.grid(row=1, column=0, pady=(14, 0), sticky="nsew")

        # --- Color Tags ---
        self.log_text.tag_config("INFO", foreground="#4FC1FF")      # Light Blue
        self.log_text.tag_config("WARNING", foreground="#FFD700")   # Gold/Yellow
        self.log_text.tag_config("ERROR", foreground="#FF453A")     # Red
        self.log_text.tag_config("SUCCESS", foreground="#32D74B")   # Bright Green
        self.log_text.tag_config("FATAL", foreground="#FF00FF")     # Magenta
        self.log_text.tag_config("TIMESTAMP", foreground="#808080") # Gray
        self.log_text.tag_config("WORKER", foreground="#DCE4EE")    # Standard Text
        self.log_text.tag_config("CMD", foreground="#B0B0B0")       # Dimmer Text for shell output

    def _create_settings_page(self):
        frame = self.settings_frame
        ctk.CTkLabel(frame, text="Settings", font=("Arial", 20, "bold"), anchor="w").grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(frame, text=f"Saved to worker/{CONFIG_FILE_NAME}. Changes apply the next time the worker starts.",
                     text_color=COLOR_TEXT_MUTED, anchor="w").grid(row=1, column=0, pady=(2, 16), sticky="w")

        box = ctk.CTkFrame(frame, corner_radius=6, fg_color=COLOR_PANEL, border_width=1, border_color=COLOR_BORDER)
        box.grid(row=2, column=0, sticky="nw")

        self.user_entry = self._add_settings_field(box, 0, "Fishtest username")
        self.pass_entry = self._add_settings_field(box, 1, "Fishtest password", secret=True)
        self.cores_entry = self._add_settings_field(box, 2, "Concurrency (cores)", help_text=concurrency_help())
        self.token_entry = self._add_settings_field(box, 3, "GitHub personal access token (optional)", secret=True,
                                                    help_text="Avoids GitHub API rate limits when updating.")

        self.settings_error = ctk.CTkLabel(box, text="", text_color=COLOR_DANGER_TEXT, anchor="w", justify="left", wraplength=420)
        self.settings_error.grid(row=4, column=0, padx=18, sticky="w")

        buttons = ctk.CTkFrame(box, fg_color="transparent")
        buttons.grid(row=5, column=0, padx=18, pady=(8, 18), sticky="ew")
        ctk.CTkButton(buttons, text="Save", width=90, command=self._save_settings,
                      fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER).pack(side="left")
        ctk.CTkButton(buttons, text="Cancel", width=90, command=lambda: self._show_view("dashboard"), fg_color="transparent",
                      border_width=1, border_color=COLOR_INPUT_BORDER, text_color=COLOR_TEXT_NAV,
                      hover_color=COLOR_NAV_HOVER).pack(side="left", padx=(10, 0))

        register_label = ctk.CTkLabel(buttons, text="Don't have an account? Register here!", text_color=COLOR_ACCENT_TEXT, cursor="hand2")
        register_label.pack(side="right")
        register_label.bind("<Button-1>", lambda e: webbrowser.open("https://tests.stockfishchess.org/signup"))

    def _add_settings_field(self, parent, row, label, secret=False, help_text=""):
        field = ctk.CTkFrame(parent, fg_color="transparent")
        field.grid(row=row, column=0, padx=18, pady=(16 if row == 0 else 12, 0), sticky="ew")
        ctk.CTkLabel(field, text=label, font=("Arial", 12, "bold"), text_color=COLOR_TEXT_NAV, anchor="w").pack(anchor="w")

        row_frame = ctk.CTkFrame(field, fg_color="transparent")
        row_frame.pack(fill="x", pady=(4, 0))
        entry = ctk.CTkEntry(row_frame, width=380 if secret else 440, height=34, corner_radius=6, border_width=1,
                             fg_color=COLOR_BG, border_color=COLOR_INPUT_BORDER, show="*" if secret else "")
        entry.pack(side="left")
        if secret:
            def toggle():
                hidden = entry.cget("show") == "*"
                entry.configure(show="" if hidden else "*")
                show_button.configure(text="Hide" if hidden else "Show")
            show_button = ctk.CTkButton(row_frame, text="Show", width=52, height=34, command=toggle, fg_color="transparent",
                                        text_color=COLOR_TEXT_MUTED, hover_color=COLOR_NAV_HOVER)
            show_button.pack(side="left", padx=(8, 0))

        if help_text:
            ctk.CTkLabel(field, text=help_text, font=("Arial", 11), text_color=COLOR_TEXT_MUTED, anchor="w",
                         justify="left", wraplength=440).pack(anchor="w", pady=(4, 0))
        return entry

    # --- Navigation ---
    def _show_view(self, name):
        self.current_view = name
        if name == "settings":
            self.dash_frame.grid_remove()
            self.settings_frame.grid()
        else:
            self.settings_frame.grid_remove()
            self.dash_frame.grid()
        # The selected entry gets a fill, no border
        for button, view in ((self.dashboard_button, "dashboard"), (self.settings_button, "settings")):
            selected = name == view
            button.configure(fg_color=COLOR_NAV_SELECTED if selected else "transparent",
                             hover_color=COLOR_NAV_SELECTED if selected else COLOR_NAV_HOVER,
                             text_color="white" if selected else COLOR_TEXT_NAV)

    def _show_settings(self):
        if self.is_long_operation_running or (self.worker_process and self.worker_process.poll() is None):
            return
        for entry, value in ((self.user_entry, self.config.get('login', 'username')),
                             (self.pass_entry, self.config.get('login', 'password')),
                             (self.cores_entry, self.config.get('parameters', 'concurrency')),
                             (self.token_entry, read_github_token())):
            entry.delete(0, ctk.END)
            entry.insert(0, value)
        self._settings_token = self.token_entry.get()
        self.settings_error.configure(text="")
        self._show_view("settings")

    def _save_settings(self):
        cores = self.cores_entry.get().strip()
        error = validate_concurrency(cores)
        if error:
            self.settings_error.configure(text=error)
            return
        self.config.set('login', 'username', self.user_entry.get())
        self.config.set('login', 'password', self.pass_entry.get())
        self.config.set('parameters', 'concurrency', cores)
        # Older versions stored the token here; the worker removes this section anyway
        self.config.remove_section('Fishtest')
        self._save_config()
        token = self.token_entry.get().strip()
        if token != self._settings_token:
            self._save_github_token(token)
        self._show_view("dashboard")
        self._update_all_controls_state()

    def _set_state(self, text, kind="idle"):
        """ Updates the state line of the control card. kind is one of idle, running, busy. """
        self.state_dot.configure(text_color=COLOR_STATE[kind])
        self.state_label.configure(text=text)
        self.who_label.configure(text=self._who_text() if kind != "busy" else "")

    def _who_text(self):
        user = self.config.get('login', 'username')
        cores = self.config.get('parameters', 'concurrency')
        cores_text = f"{cores} core{'' if cores == '1' else 's'}" if cores.isdigit() else f"cores: {cores}"
        return f"·  {user}  ·  {cores_text}"

    # --- Configuration and State Management ---
    def _load_config(self):
        self.config.read(CONFIG_FILE)
        if 'login' not in self.config:
            self.config['login'] = {
                'username': USERNAME_DEFAULT, 'password': ''
            }
        if 'parameters' not in self.config:
            self.config['parameters'] = {
                'concurrency': '3'
            }

    def _save_config(self):
        try:
            with open(CONFIG_FILE, 'w') as configfile:
                self.config.write(configfile)
            self._load_config()
            self.who_label.configure(text=self._who_text())
            self.add_log(f"Settings saved to {CONFIG_FILE_NAME}.", level="SUCCESS")
        except PermissionError:
            self.add_log(f"Failed to save settings. Permission denied writing to {CONFIG_FILE}.", level="ERROR")
        except Exception as e:
            self.add_log(f"Failed to save settings due to an unexpected IO error: {e}", level="ERROR")

    def _initial_environment_check(self):
        """ Log initial environment status without changing UI components. """
        msys2_installed = os.path.exists(os.path.join(MSYS2_PATH, "msys2_shell.cmd"))
        worker_installed = os.path.exists(os.path.join(WORKER_DIR, "worker.py"))

        if not msys2_installed:
            self.add_log("MSYS2 not found. Click 'INSTALL WORKER' to install the worker.", level="WARNING")
        elif not is_msys2_ready():
            self.add_log("MSYS2 found, but required packages are missing. Click 'INSTALL WORKER' to install them.", level="WARNING")
        elif not worker_installed:
            self.add_log("MSYS2 found, but worker files are missing. Click 'INSTALL WORKER' to set them up.", level="WARNING")
        else:
            self.add_log("Full environment setup is complete.", level="SUCCESS")
            user = self.config.get('login', 'username', fallback=USERNAME_DEFAULT)
            password = self.config.get('login', 'password', fallback='')
            if user == USERNAME_DEFAULT or not user or not password:
                self.add_log("Before starting the worker, open the 'Settings' and enter your Fishtest username and password. Then, click 'START WORKER'.")
                self.after(500, self._show_settings)
            else:
                self.add_log("You may now start the worker by clicking 'START WORKER'.")

    def _leave_settings_page(self):
        """ Settings can't be edited while something is running, so go back to the dashboard. """
        if self.current_view == "settings":
            self._show_view("dashboard")

    def _update_all_controls_state(self):
        """ Master function to set the state of all controls based on app state. """
        is_worker_running = self.worker_process and self.worker_process.poll() is None

        # Case 1: Worker is running
        if is_worker_running:
            self._leave_settings_page()
            for button in [self.setup_button, self.update_button, self.settings_button, self.uninstall_button]:
                button.configure(state='disabled')
            if self.is_stopping_gracefully:
                self.worker_button.configure(text="FORCE STOP NOW", fg_color=COLOR_DANGER, hover_color=COLOR_DANGER_HOVER, state="normal")
                self._set_state("Stopping...", "busy")
            else:
                self.worker_button.configure(text="STOP WORKER", fg_color=COLOR_DANGER, hover_color=COLOR_DANGER_HOVER, state="normal")
                self._set_state("Running", "running")
            return

        # Case 2: A long setup/update/uninstall operation is running
        if self.is_long_operation_running:
            self._leave_settings_page()
            for button in [self.setup_button, self.update_button, self.settings_button, self.uninstall_button, self.worker_button]:
                button.configure(state='disabled')
            return

        # Case 3: App is idle
        self._load_config()
        self._set_state("Idle")

        msys2_installed = os.path.exists(os.path.join(MSYS2_PATH, "msys2_shell.cmd"))
        worker_installed = os.path.exists(os.path.join(WORKER_DIR, "worker.py"))
        worker_dir_exists = os.path.exists(WORKER_DIR)
        msys2_uninstaller_exists = os.path.exists(os.path.join(MSYS2_PATH, "uninstall.exe"))

        self.setup_button.configure(state='normal')
        self.settings_button.configure(state='normal')
        self.update_button.configure(state='normal' if msys2_installed else 'disabled')
        is_ready = worker_installed and is_msys2_ready()

        if is_ready:
            user = self.config.get('login', 'username', fallback=USERNAME_DEFAULT)
            password = self.config.get('login', 'password', fallback='')
            has_credentials = not (user == USERNAME_DEFAULT or not user or not password)
            self.worker_button.configure(state='normal' if has_credentials else 'disabled', text="START WORKER", fg_color=COLOR_ACCENT if has_credentials else COLOR_ACCENT_DISABLED, hover_color=COLOR_ACCENT_HOVER)
        else:
            self.worker_button.configure(state='normal', text="INSTALL WORKER", fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER)

        if worker_dir_exists:
            self.uninstall_button.configure(text="Delete Worker Folder", state='normal')
        elif msys2_uninstaller_exists:
            self.uninstall_button.configure(text="Uninstall MSYS2", state='normal')
        else:
            self.uninstall_button.configure(text="Uninstall", state='disabled')

    # --- Update Checker Logic ---
    def _check_latest_version_thread(self):
        """ Checks GitHub for the latest release in a background thread. """
        url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"
        try:
            # The GitHub API rejects requests without a User-Agent
            req = urllib.request.Request(url, headers={'User-Agent': APP_NAME})

            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode())
                    latest_tag = data.get("tag_name", "")

                    if latest_tag:
                        self._compare_versions(latest_tag)
        except urllib.error.HTTPError as e:
            if e.code == 403:
                self.after(0, self.add_log, "App update check skipped (GitHub API rate limit exceeded).", "WARNING")
            else:
                self.after(0, self.add_log, f"App update check failed (HTTP {e.code}).", "WARNING")
        except Exception as e:
            self.after(0, self.add_log, f"App update check failed. Check your internet connection before running the worker. ({e})", "WARNING")

    def _compare_versions(self, latest_tag):
        def parse_version(v_str):
            try:
                return tuple(map(int, v_str.lstrip('v').split('.')))
            except ValueError:
                return (0, 0, 0)

        current = parse_version(APP_VERSION)
        latest = parse_version(latest_tag)

        if latest > current:
            self.after(0, lambda: self._show_update_notification(latest_tag))
        else:
            self.after(0, self.add_log, f"You are using the latest version of the app ({APP_VERSION}).")

    def _show_update_notification(self, latest_tag):
        self.new_version_button.configure(text=f"Update available: {latest_tag}")
        self.new_version_button.grid()
        self.add_log(f"A new version of the Manager is available ({latest_tag}).")

    def _open_release_page(self):
        webbrowser.open(f"https://github.com/{REPO_OWNER}/{REPO_NAME}/releases/latest")

    # --- Core Actions ---
    def _run_elevated_command(self, command, start_message="", end_message="", on_complete=None, on_error=None):
        """ Runs an elevated command via ShellExecuteExW without elevating the main GUI process.
            Streams output to the log viewer by tailing a temporary log file. """
        if self._is_admin():
            self._run_command_in_thread(
                command,
                start_message=start_message,
                end_message=end_message,
                on_complete=on_complete,
                on_error=on_error
            )
            return

        def run():
            self.is_long_operation_running = True
            self.after(0, self._update_all_controls_state)
            self.after(0, self._set_state, f"{start_message}..." if start_message else "Working...", "busy")
            if start_message:
                self.after(0, self.add_log, start_message)

            temp_dir = tempfile.gettempdir()
            run_id = f"ft_elevated_{int(time.time() * 1000)}"
            log_file = os.path.join(temp_dir, f"{run_id}.log")
            runner_cmd = os.path.join(temp_dir, f"{run_id}.cmd")

            try:
                with open(runner_cmd, "w", encoding="utf-8") as f:
                    f.write("@echo off\n")
                    f.write("chcp 65001 >nul\n")
                    f.write(f'{command} > "{log_file}" 2>&1\n')
                    f.write("exit /b %ERRORLEVEL%\n")
            except Exception as e:
                self.after(0, self.add_log, f"Failed to prepare elevated task: {e}", "FATAL")
                if on_error:
                    self.after(0, on_error)
                self.is_long_operation_running = False
                self.after(0, self._update_all_controls_state)
                return

            sei = SHELLEXECUTEINFOW()
            sei.cbSize = ctypes.sizeof(SHELLEXECUTEINFOW)
            sei.fMask = SEE_MASK_NOCLOSEPROCESS
            sei.lpVerb = "runas"
            sei.lpFile = runner_cmd
            sei.lpParameters = None
            sei.lpDirectory = os.path.abspath(".")
            sei.nShow = SW_HIDE

            # Without use_last_error, the interpreter can overwrite the error code before we read it
            shell32 = ctypes.WinDLL("shell32", use_last_error=True)
            success = shell32.ShellExecuteExW(ctypes.byref(sei))
            if not success or not sei.hProcess:
                err = ctypes.get_last_error()
                if err == 1223:  # ERROR_CANCELLED (user clicked "No" on UAC)
                    self.after(0, self.add_log, "Administrator rights were not granted. The action was cancelled.", "WARNING")
                else:
                    self.after(0, self.add_log, f"Failed to launch elevated task (Error code {err}).", "ERROR")
                    if on_error:
                        self.after(0, on_error)
                try:
                    if os.path.exists(runner_cmd): os.remove(runner_cmd)
                    if os.path.exists(log_file): os.remove(log_file)
                except OSError:
                    pass
                self.is_long_operation_running = False
                self.after(0, self._update_all_controls_state)
                return

            h_process = sei.hProcess
            read_pos = 0

            try:
                # Read as bytes: programs that ignore chcp 65001 write in the OEM code page
                while True:
                    wait_res = ctypes.windll.kernel32.WaitForSingleObject(h_process, 100)
                    if os.path.exists(log_file):
                        try:
                            with open(log_file, "rb") as lf:
                                lf.seek(read_pos)
                                for raw_line in lf:
                                    stripped = decode_output(raw_line).strip()
                                    if stripped:
                                        self.after(0, self.add_log, stripped, "CMD")
                                read_pos = lf.tell()
                        except Exception:
                            pass
                    if wait_res != 0x00000102:  # WAIT_TIMEOUT is 0x102
                        break

                exit_code = wintypes.DWORD()
                ctypes.windll.kernel32.GetExitCodeProcess(h_process, ctypes.byref(exit_code))
                rc = exit_code.value

                if end_message:
                    self.after(0, self.add_log, end_message)

                if rc == 0:
                    if on_complete:
                        self.after(0, on_complete)
                else:
                    self.after(0, self.add_log, f"Elevated process finished with non-zero exit code: {rc}", "ERROR")
                    if on_error:
                        self.after(0, on_error)

            finally:
                ctypes.windll.kernel32.CloseHandle(h_process)
                try:
                    if os.path.exists(runner_cmd): os.remove(runner_cmd)
                    if os.path.exists(log_file): os.remove(log_file)
                except OSError:
                    pass
                self.is_long_operation_running = False
                self.after(0, self._update_all_controls_state)

        threading.Thread(target=run, daemon=True).start()

    def _run_full_setup(self):
        if is_msys2_ready():
            if not tkinter.messagebox.askyesno("Confirm Worker Setup", "MSYS2 environment is already installed.\n\nThis will download and set up the fishtest worker files in this directory.\n\nNote: Any existing 'worker' folder will be deleted and replaced.\n\nContinue?"):
                return
            self._install_worker_files()
        else:
            if not tkinter.messagebox.askyesno("Confirm Installation", "This will install the MSYS2 environment and download the fishtest worker files.\nThis may take several minutes.\n\nNote: Any existing 'worker' folder in this directory will be deleted and replaced.\n\nContinue?"):
                return

            command = f'call "{get_asset_path("setup_msys2.cmd")}"'
            self._run_elevated_command(
                command,
                start_message="Starting MSYS2 Installation and Package Setup",
                end_message="MSYS2 Installation and Package Setup finished",
                on_complete=self._install_worker_files,
                on_error=self._prompt_manual_msys2_install
            )

    def _prompt_manual_msys2_install(self):
        self.add_log("Automated MSYS2 installation failed.", level="ERROR")
        self.add_log("To install manually:", level="INFO")
        self.add_log("1. Download the MSYS2 installer from https://www.msys2.org", level="INFO")
        self.add_log("2. Install it to the DEFAULT directory: C:\\msys64", level="INFO")
        self.add_log("3. Once installed, click 'Install/Re-Install Worker' again.", level="INFO")

        if tkinter.messagebox.askyesno(
            "MSYS2 Installation Failed",
            "Automated MSYS2 installation failed.\n\n"
            "Would you like to open the official MSYS2 download page to install it manually?\n\n"
            "IMPORTANT: When installing manually, you MUST use the default installation directory: C:\\msys64\n\n"
            "After manual installation completes, click 'Install/Re-Install Worker' again.",
            icon='warning'
        ):
            webbrowser.open("https://www.msys2.org")

    def _install_worker_files(self):
        user = self.config.get('login', 'username')
        password = self.config.get('login', 'password')
        cores = self.config.get('parameters', 'concurrency')

        msys2_script_path = windows_to_msys2_path(get_asset_path('setup_worker.sh'))
        # The script is expected to run from the app's root to create the 'worker' sub-directory.
        app_run_dir = os.path.abspath(".")

        # The script path is quoted with single quotes for bash to handle spaces in the MSYS2 path.
        # User values are NOT put in the command line: cmd and bash would interpret characters
        # like ' " % & in them. They are passed as environment variables instead.
        worker_install_cmd = f"bash '{msys2_script_path}'"

        # Use -where with a quoted Windows path, which is safer than -here for paths with spaces.
        full_command = f'"{os.path.join(MSYS2_PATH, "msys2_shell.cmd")}" -defterm -ucrt64 -no-start -where "{app_run_dir}" -c "{worker_install_cmd}"'

        env = os.environ.copy()
        env["FT_USER"] = user
        env["FT_PASSWORD"] = password
        env["FT_CORES"] = cores

        self._run_command_in_thread(
            full_command,
            start_message="Installing worker files and dependencies",
            end_message="Worker installation finished",
            on_complete=self._initial_environment_check,
            env=env
        )

    def _update_msys2(self):
        command = f'call "{get_asset_path("update_msys2.cmd")}"'
        self._run_elevated_command(
            command,
            start_message="Updating MSYS2 environment",
            end_message="MSYS2 Update finished"
        )

    def _handle_uninstall_click(self):
        worker_dir_exists = os.path.exists(WORKER_DIR)
        msys2_uninstaller_exists = os.path.exists(os.path.join(MSYS2_PATH, "uninstall.exe"))

        if worker_dir_exists:
            self._delete_worker_folder()
        elif msys2_uninstaller_exists:
            self._uninstall_msys2()

    def _delete_worker_folder(self):
        if not tkinter.messagebox.askyesno("Confirm Deletion",
                                           "WARNING: This is a destructive action.\n\n"
                                           "This will permanently delete the 'worker' folder and all its contents, including your configuration file.\n\n"
                                           "Are you sure you want to continue?",
                                           icon='warning'):
            return

        worker_dir_abs = os.path.abspath(WORKER_DIR)
        command = f'if exist "{worker_dir_abs}" (echo Removing worker directory... & rd /s /q "{worker_dir_abs}") else (echo Worker directory not found.)'

        self._run_command_in_thread(
            command,
            start_message="Deleting worker folder",
            end_message="Worker folder deleted"
        )

    def _uninstall_msys2(self):
        if not tkinter.messagebox.askyesno("Confirm Uninstallation",
                                           "WARNING: This is a destructive action.\n\n"
                                           "This will run the MSYS2 uninstaller and remove the entire MSYS2 environment.\n\n"
                                           "Are you sure you want to continue?",
                                           icon='warning'):
            return

        command = f'call "{get_asset_path("uninstall_msys2.cmd")}"'

        self._run_elevated_command(
            command,
            start_message="Uninstalling MSYS2, this may take a few minutes",
            end_message="MSYS2 Uninstallation finished"
        )

    def _save_github_token(self, token):
        # The token lives only in the netrc file: the worker deletes unknown sections from fishtest.cfg
        if any(c.isspace() for c in token):
            return self.add_log("GitHub token not saved: it must not contain spaces.", level="ERROR")
        try:
            netrc_path = write_github_token(token)
            if token:
                self.add_log(f"Saved GitHub token to '{netrc_path}' for GitHub API authentication.")
            else:
                self.add_log(f"Removed GitHub token from '{netrc_path}'.")
        except Exception as e:
            self.add_log(f"Failed to update the netrc file: {e}", level="ERROR")

    # --- Worker Start/Stop Logic ---
    def _toggle_worker(self):
        if self.worker_process is not None:
            if self.is_stopping_gracefully:
                self._confirm_and_force_stop()
            else:
                self._stop_worker_gracefully()
        elif is_msys2_ready() and os.path.exists(os.path.join(WORKER_DIR, "worker.py")):
            self._start_worker()
        else:
            self._run_full_setup()

    def _start_worker(self):
        self.add_log("Attempting to start the worker...")
        self.is_stopping_gracefully = False

        exit_file_path = os.path.join(WORKER_DIR, EXIT_FILE_NAME)
        if os.path.exists(exit_file_path):
            try:
                os.remove(exit_file_path)
                self.add_log(f"Cleaned up leftover {EXIT_FILE_NAME} file.")
            except Exception as e:
                self.add_log(f"Could not clean up leftover {EXIT_FILE_NAME} file. The worker may not start correctly: {e}", level="ERROR")

        self.task_total_games = 0
        self.task_current_games = 0
        self.task_start_time = None
        self.task_progress_bar.set(0)
        self.task_progress_label.configure(text="")
        self.task_progress_label.grid()
        self.task_progress_bar.grid()

        # worker.py must run from inside WORKER_DIR, which -where sets as the working directory
        worker_dir_win_path = os.path.abspath(WORKER_DIR)
        worker_command = "env/bin/python3 worker.py"

        full_command = f'"{os.path.join(MSYS2_PATH, "msys2_shell.cmd")}" -defterm -ucrt64 -no-start -where "{worker_dir_win_path}" -c "{worker_command}"'

        threading.Thread(target=self._execute_worker_process, args=(full_command,), daemon=True).start()

    def _execute_worker_process(self, command):
        try:
            self.worker_process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                shell=True, creationflags=subprocess.CREATE_NO_WINDOW
            )
            self.after(0, self._update_all_controls_state)
            for raw_line in iter(self.worker_process.stdout.readline, b''):
                line = decode_output(raw_line)
                self.after(0, self._process_worker_output, line.strip())
            self.worker_process.stdout.close()
            self.worker_process.wait()
        except Exception as e:
            self.after(0, self.add_log, f"Worker failed to start: {e}", "FATAL")
        finally:
            self.after(0, self._on_worker_stopped)

    def _stop_worker_gracefully(self):
        if self.worker_process is None:
            return self.add_log("Worker is not running.")

        # The wrapper process can be dead while the worker itself keeps running
        if self.worker_process.poll() is not None:
            self.add_log("Wrapper process is dead. Attempting to stop the worker.", level="WARNING")

        exit_file_path = os.path.join(WORKER_DIR, EXIT_FILE_NAME)
        try:
            with open(exit_file_path, "w") as f:
                pass
            self.is_stopping_gracefully = True
            self.add_log("Graceful stop requested.", level="INFO")
            self.add_log("The worker will finish its current batch of games to safely save results. This may take several minutes.", level="INFO")
            self.add_log("To stop immediately without saving the in-flight batch, click 'FORCE STOP NOW'.", level="INFO")
            self._update_all_controls_state()
            self._update_progress_display()
        except Exception as e:
            self.add_log(f"Could not create {EXIT_FILE_NAME} file: {e}. Consider a force stop.", level="ERROR")
            self.is_stopping_gracefully = False
            self._update_all_controls_state()

    def _confirm_and_force_stop(self):
        if self.worker_process is not None:
            if tkinter.messagebox.askyesno("Force Stop", "Are you sure you want to force stop the worker?\n\nIn-progress batch results will be lost."):
                self._stop_worker_forcefully()

    def _force_stop_worker_event(self, event=None):
        self._confirm_and_force_stop()

    def _stop_worker_forcefully(self):
        # Check the object rather than poll(), so we can clean up even if the wrapper process died silently
        if self.worker_process is None:
            return self.add_log("Worker is not running.")

        self.add_log("Force stopping worker...")
        try:
            subprocess.run(f"taskkill /F /PID {self.worker_process.pid} /T", check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        except Exception as e:
            # If the process is already dead (Zombie), taskkill will fail.
            self.add_log(f"taskkill failed (process might be dead): {e}", level="WARNING")
            try:
                self.worker_process.terminate()
            except Exception as e:
                # Log this just in case, but usually it means the process is already gone.
                self.add_log(f"Internal terminate() failed (ignoring): {e}", level="DEBUG")

        # Clean up the lingering fish.exit file left from the previous *graceful* attempt (if any)
        exit_file_path = os.path.join(WORKER_DIR, EXIT_FILE_NAME)
        if os.path.exists(exit_file_path):
            try:
                os.remove(exit_file_path)
                self.add_log(f"Cleaned up leftover {EXIT_FILE_NAME} file.")
            except Exception as e:
                self.add_log(f"Could not clean up leftover {EXIT_FILE_NAME} file: {e}", level="ERROR")

    def _on_worker_stopped(self):
        self.add_log("Worker process has stopped.", level="SUCCESS")
        self.worker_process = None
        self.is_stopping_gracefully = False
        self.task_progress_label.grid_remove()
        self.task_progress_bar.grid_remove()
        self._update_all_controls_state()

    # --- Worker progress tracking ---
    def _process_worker_output(self, line):
        """Parses a line from the worker's stdout to update task progress."""
        self.add_log(line, level="WORKER")

        # Detect Start/Total Games
        # Pattern: Started game X of Y ...
        match_start = re.search(r"^Started game (\d+) of (\d+)", line)
        if match_start:
            game_num = int(match_start.group(1))
            total_games = int(match_start.group(2))

            self.task_total_games = total_games

            # If this is specifically Game 1, reset the timer for ETA calculation.
            # If we resumed at Game 50, we don't reset time (or ETA would be wrong).
            if game_num == 1:
                self.task_current_games = 0
                self.task_start_time = time.time()
                self._update_progress_display()

            return

        # Detect Progress
        # Pattern: Games: N, Wins: ...
        match_progress = re.search(r"^Games: (\d+), Wins:", line)
        if match_progress:
            self.task_current_games = int(match_progress.group(1))
            self._update_progress_display()

    def _update_progress_display(self):
        """Updates the progress bar and label widgets based on current state, including ETA."""
        if self.task_total_games > 0:
            progress = self.task_current_games / self.task_total_games
            self.task_progress_bar.set(progress)

            base_text = f"Task Progress: {self.task_current_games} / {self.task_total_games}"
            eta_text = ""

            # Calculate ETA if task has started and is in progress
            if self.task_start_time and self.task_current_games > 0 and self.task_current_games < self.task_total_games:
                elapsed_seconds = time.time() - self.task_start_time
                if elapsed_seconds > 1: # Avoid division by zero/erratic early values
                    games_per_second = self.task_current_games / elapsed_seconds
                    remaining_games = self.task_total_games - self.task_current_games
                    remaining_seconds = remaining_games / games_per_second

                    if remaining_seconds < 60:
                        eta_text = f" (ETA: {int(remaining_seconds)}s)"
                    else:
                        remaining_minutes = remaining_seconds / 60
                        eta_text = f" (ETA: {int(remaining_minutes)}m)"

            elif self.task_current_games == self.task_total_games:
                eta_text = " (Finished)"

            if self.is_stopping_gracefully:
                eta_text += " • Stopping after batch"

            self.task_progress_label.configure(text=base_text + eta_text)
        else:
            # This case is handled when the worker starts, but good to have
            self.task_progress_bar.set(0)
            self.task_progress_label.configure(text="")

    # --- Threading and Utilities ---
    def _run_command_in_thread(self, command, start_message="", end_message="", on_complete=None, on_error=None, env=None):
        def run():
            self.is_long_operation_running = True
            self.after(0, self._update_all_controls_state)
            self.after(0, self._set_state, f"{start_message}..." if start_message else "Working...", "busy")
            if start_message: self.after(0, self.add_log, start_message)
            try:
                process = subprocess.Popen(
                    command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    shell=True, creationflags=subprocess.CREATE_NO_WINDOW, env=env
                )
                for raw_line in iter(process.stdout.readline, b''):
                    line = decode_output(raw_line)
                    self.after(0, self.add_log, line.strip(), "CMD")
                rc = process.wait()
                if end_message: self.after(0, self.add_log, end_message)
                if rc == 0:
                    if on_complete: self.after(0, on_complete)
                else:
                    self.after(0, self.add_log, f"Process finished with non-zero exit code: {rc}", "ERROR")
                    if on_error: self.after(0, on_error)
            except Exception as e:
                self.after(0, self.add_log, f"executing command: {e}", "FATAL")
                if on_error: self.after(0, on_error)
            finally:
                self.is_long_operation_running = False
                self.after(0, self._update_all_controls_state)
        threading.Thread(target=run, daemon=True).start()

    def add_log(self, message, level="INFO"):
        # Check if user is looking at history (scrolled up)
        is_at_bottom = self.log_text.yview()[1] == 1.0

        self.log_text.configure(state='normal')

        timestamp = time.strftime("[%H:%M:%S]")

        level_str = level.upper()
        tag = level_str
        padded_level = f"[{level_str:<7}]"

        self.log_text.insert(ctk.END, timestamp + " ", "TIMESTAMP")

        self.log_text.insert(ctk.END, padded_level, tag)
        self.log_text.insert(ctk.END, " ")

        self.log_text.insert(ctk.END, message + '\n')

        self.log_text.configure(state='disabled')

        # Only scroll down if we were already at the bottom
        if is_at_bottom:
            self.log_text.yview(ctk.END)

    def _on_closing(self):
        if self.worker_process and self.worker_process.poll() is None:
            if tkinter.messagebox.askyesno("Exit", "The worker is still running. Do you want to force stop it and exit?"):
                self._stop_worker_forcefully()
                self.destroy()
        else:
            self.destroy()

if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    app = FishtestManagerApp()
    app.mainloop()