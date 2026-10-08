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
        self.geometry("900x650")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self.iconbitmap(get_asset_path("icon.ico"))

    def _create_widgets(self):
        # --- Top Control Frame ---
        top_frame = ctk.CTkFrame(self)
        top_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        top_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.setup_button = ctk.CTkButton(top_frame, text="Install/Re-Install Worker", command=self._run_full_setup)
        self.setup_button.grid(row=0, column=0, padx=5, pady=10)

        self.update_button = ctk.CTkButton(top_frame, text="Update MSYS2 Environment", command=self._update_msys2)
        self.update_button.grid(row=0, column=1, padx=5, pady=10)

        self.settings_button = ctk.CTkButton(top_frame, text="Settings", command=self._open_settings_window)
        self.settings_button.grid(row=0, column=2, padx=5, pady=10)

        self.uninstall_button = ctk.CTkButton(top_frame, text="Uninstall...", command=self._handle_uninstall_click, fg_color="#C00000", hover_color="#A00000")
        self.uninstall_button.grid(row=0, column=3, padx=5, pady=10)

        # --- Update Notification Button (Hidden by default) ---
        self.new_version_button = ctk.CTkButton(top_frame, text="New Version Available!",
                                                command=self._open_release_page,
                                                fg_color="#229965", hover_color="#1F7A52", text_color="white")
        self.new_version_button.grid(row=1, column=0, columnspan=4, padx=5, pady=(0, 10), sticky="ew")
        self.new_version_button.grid_remove()

        # --- Main Action Frame ---
        action_frame = ctk.CTkFrame(self, fg_color="transparent")
        action_frame.grid(row=1, column=0, padx=10, pady=10, sticky="ew")
        action_frame.grid_columnconfigure(0, weight=1)

        self.worker_button = ctk.CTkButton(action_frame, text="START WORKER", command=self._toggle_worker, height=50, font=("Arial", 16, "bold"))
        self.worker_button.grid(row=0, column=0, padx=200, pady=5, sticky="ew")
        self.worker_button.bind("<Button-3>", self._force_stop_worker_event) # Right-click to force stop

        self.status_label = ctk.CTkLabel(action_frame, text="Status: Initializing...", font=("Arial", 14))
        self.status_label.grid(row=1, column=0, pady=(5,0))

        # --- Progress bar for worker tasks ---
        self.task_progress_label = ctk.CTkLabel(action_frame, text="", font=("Arial", 12))
        self.task_progress_label.grid(row=2, column=0, pady=(5,0), sticky="ew")

        self.task_progress_bar = ctk.CTkProgressBar(action_frame)
        self.task_progress_bar.grid(row=3, column=0, padx=50, pady=(5,10), sticky="ew")
        self.task_progress_bar.set(0)

        # Initially hide them until the worker starts
        self.task_progress_label.grid_remove()
        self.task_progress_bar.grid_remove()

        # --- Log Frame ---
        log_frame = ctk.CTkFrame(self)
        log_frame.grid(row=2, column=0, padx=10, pady=(0, 10), sticky="nsew")
        log_frame.grid_rowconfigure(0, weight=1)
        log_frame.grid_columnconfigure(0, weight=1)

        self.log_text = tkinter.scrolledtext.ScrolledText(log_frame, wrap=ctk.WORD, state='disabled',
                                                          bg="#2B2B2B", fg="#DCE4EE", font=("Consolas", 10),
                                                          relief="flat", borderwidth=0)
        self.log_text.grid(row=0, column=0, sticky="nsew")

        # --- Color Tags ---
        self.log_text.tag_config("INFO", foreground="#4FC1FF")      # Light Blue
        self.log_text.tag_config("WARNING", foreground="#FFD700")   # Gold/Yellow
        self.log_text.tag_config("ERROR", foreground="#FF453A")     # Red
        self.log_text.tag_config("SUCCESS", foreground="#32D74B")   # Bright Green
        self.log_text.tag_config("FATAL", foreground="#FF00FF")     # Magenta
        self.log_text.tag_config("TIMESTAMP", foreground="#808080") # Gray
        self.log_text.tag_config("WORKER", foreground="#DCE4EE")    # Standard Text
        self.log_text.tag_config("CMD", foreground="#B0B0B0")       # Dimmer Text for shell output

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
        user = self.config.get('login', 'username')
        cores = self.config.get('parameters', 'concurrency')
        self.status_label.configure(text=f"Status: Idle | User: {user} | Cores: {cores}")

    def _save_config(self):
        try:
            with open(CONFIG_FILE, 'w') as configfile:
                self.config.write(configfile)
            self._load_config()
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
            self.add_log("MSYS2 not found. Please run 'Install/Re-Install Worker'.")
        elif not is_msys2_ready():
            self.add_log("MSYS2 found, but required packages are missing. Run 'Install/Re-Install Worker' to install them.")
        elif not worker_installed:
            self.add_log("MSYS2 found, but worker files are missing. Run 'Install/Re-Install Worker' to set them up.")
        else:
            self.add_log("Full environment setup is complete.", level="SUCCESS")
            user = self.config.get('login', 'username', fallback=USERNAME_DEFAULT)
            password = self.config.get('login', 'password', fallback='')
            if user == USERNAME_DEFAULT or not user or not password:
                self.add_log("Before starting the worker, open the 'Settings' and enter your Fishtest username and password. Then, click 'START WORKER'.")
                self.after(500, self._open_settings_window)
            else:
                self.add_log("You may now start the worker by clicking 'START WORKER'.")

    def _update_all_controls_state(self):
        """ Master function to set the state of all controls based on app state. """
        is_worker_running = self.worker_process and self.worker_process.poll() is None

        # Case 1: Worker is running
        if is_worker_running:
            for button in [self.setup_button, self.update_button, self.settings_button, self.uninstall_button]:
                button.configure(state='disabled')
            self.worker_button.configure(text="STOP WORKER", fg_color="#C00000", hover_color="#A00000", state="normal")
            user = self.config.get('login', 'username')
            cores = self.config.get('parameters', 'concurrency')
            self.status_label.configure(text=f"Status: Running | User: {user} | Cores: {cores}")
            return

        # Case 2: A long setup/update/uninstall operation is running
        if self.is_long_operation_running:
            for button in [self.setup_button, self.update_button, self.settings_button, self.uninstall_button, self.worker_button]:
                button.configure(state='disabled')
            return

        # Case 3: App is idle
        self._load_config()  # This will refresh the status label to Idle

        msys2_installed = os.path.exists(os.path.join(MSYS2_PATH, "msys2_shell.cmd"))
        worker_installed = os.path.exists(os.path.join(WORKER_DIR, "worker.py"))
        worker_dir_exists = os.path.exists(WORKER_DIR)
        msys2_uninstaller_exists = os.path.exists(os.path.join(MSYS2_PATH, "uninstall.exe"))

        self.setup_button.configure(state='normal')
        self.settings_button.configure(state='normal')
        self.update_button.configure(state='normal' if msys2_installed else 'disabled')
        self.worker_button.configure(state='normal' if worker_installed and is_msys2_ready() else 'disabled',
                                     text="START WORKER", fg_color="#1F6AA5", hover_color="#144870")

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
        self.new_version_button.configure(text=f"New Version Available: {latest_tag}")
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
            status_text = f"Status: {start_message.replace('---', '').strip()}..."
            self.after(0, lambda: self.status_label.configure(text=status_text))
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
                start_message="--- Starting MSYS2 Installation and Package Setup ---",
                end_message="--- MSYS2 Installation and Package Setup finished ---",
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
            start_message="--- Installing worker files and dependencies ---",
            end_message="--- Worker installation finished ---",
            on_complete=self._initial_environment_check,
            env=env
        )

    def _update_msys2(self):
        command = f'call "{get_asset_path("update_msys2.cmd")}"'
        self._run_elevated_command(
            command,
            start_message="--- Updating MSYS2 environment ---",
            end_message="--- MSYS2 Update finished ---"
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
            start_message="--- Deleting worker folder ---",
            end_message="--- Worker folder deleted ---"
        )

    def _uninstall_msys2(self):
        if not tkinter.messagebox.askyesno("Confirm Uninstallation",
                                           "WARNING: This is a destructive action.\n\n"
                                           "This will run the MSYS2 uninstaller and remove the entire MSYS2 environment.\n\n"
                                           "Are you sure you want to continue?",
                                           icon='warning'):
            return

        msys2_uninstaller = os.path.join(MSYS2_PATH, "uninstall.exe")
        command = f'if exist "{msys2_uninstaller}" (echo Uninstalling MSYS2... & start /wait "" "{msys2_uninstaller}" pr --confirm-command) else (echo MSYS2 not found.)'

        self._run_elevated_command(
            command,
            start_message="--- Starting MSYS2 Uninstallation ---",
            end_message="--- MSYS2 Uninstallation finished ---"
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
            self._stop_worker_gracefully()
        else:
            self._start_worker()

    def _start_worker(self):
        self.add_log("Attempting to start the worker...")

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

        self.add_log(f"Stopping worker gracefully... (creating {EXIT_FILE_NAME} file)")
        self.worker_button.configure(text="STOPPING...", state="disabled")
        try:
            with open(os.path.join(WORKER_DIR, EXIT_FILE_NAME), "w") as f: pass
        except Exception as e:
            self.add_log(f"Could not create {EXIT_FILE_NAME} file: {e}. Consider a force stop (right-click).", level="ERROR")
            self.worker_button.configure(text="STOP WORKER", state="normal")

    def _force_stop_worker_event(self, event):
        if self.worker_process is not None:
            if tkinter.messagebox.askyesno("Force Stop", "Are you sure you want to force stop the worker? Current game progress may be lost."):
                self._stop_worker_forcefully()

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
            status_text = f"Status: {start_message.replace('---', '').strip()}..."
            self.after(0, lambda: self.status_label.configure(text=status_text))
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

    def _open_settings_window(self):
        win = ctk.CTkToplevel(self)
        win.title("Settings"); win.geometry("400x400"); win.transient(self); win.grab_set()

        ctk.CTkLabel(win, text="Fishtest Username:").pack(pady=(10,0))
        user_entry = ctk.CTkEntry(win, width=250); user_entry.pack()

        ctk.CTkLabel(win, text="Fishtest Password:").pack(pady=(10,0))
        pass_entry = ctk.CTkEntry(win, show="*", width=250); pass_entry.pack()

        ctk.CTkLabel(win, text="Concurrency (Cores):").pack(pady=(10,0))
        cores_entry = ctk.CTkEntry(win, width=250); cores_entry.pack()

        ctk.CTkLabel(win, text="GitHub Personal Access Token (Optional):").pack(pady=(10,0))
        token_entry = ctk.CTkEntry(win, show="*", width=250); token_entry.pack()

        current_token = read_github_token()
        user_entry.insert(0, self.config.get('login', 'username'))
        pass_entry.insert(0, self.config.get('login', 'password'))
        cores_entry.insert(0, self.config.get('parameters', 'concurrency'))
        token_entry.insert(0, current_token)

        def save():
            self.config.set('login', 'username', user_entry.get())
            self.config.set('login', 'password', pass_entry.get())
            self.config.set('parameters', 'concurrency', cores_entry.get())
            # Older versions stored the token here; the worker removes this section anyway
            self.config.remove_section('Fishtest')
            self._save_config()
            token = token_entry.get().strip()
            if token != current_token:
                self._save_github_token(token)
            win.destroy()
        ctk.CTkButton(win, text="Save", command=save).pack(pady=20)

        register_label = ctk.CTkLabel(win, text="Don't have an account? Register here!", fg_color="transparent", text_color="#33a2ff", cursor="hand2")
        register_label.pack(pady=(0, 0))
        register_label.bind("<Button-1>", lambda e: webbrowser.open("https://tests.stockfishchess.org/signup"))

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