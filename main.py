import customtkinter as ctk
import tkinter.scrolledtext
import tkinter.messagebox
import subprocess
import threading
import os
import sys
import ctypes
import configparser
import webbrowser
import re
import time
import json
import urllib.request

# --- Constants ---
APP_NAME = "Fishtest Worker Manager"
APP_VERSION = "v1.0.3"
REPO_OWNER = "dav1312"
REPO_NAME = "fishtest-worker-gui"

WORKER_DIR = os.path.abspath("worker")
CONFIG_FILE = os.path.join(WORKER_DIR, "fishtest.cfg")
MSYS2_PATH = "C:\\msys64"
USERNAME_DEFAULT = "your_username"

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

class FishtestManagerApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.worker_process = None
        self.is_long_operation_running = False
        self.config = configparser.ConfigParser()
        self.task_total_games = 0
        self.task_current_games = 0
        self.task_start_time = None
        self.is_waiting_for_new_task = True

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

        self.setup_button = ctk.CTkButton(top_frame, text="Install/Re-Install Worker", command=lambda: self._run_with_elevation(self._run_full_setup, 'install'))
        self.setup_button.grid(row=0, column=0, padx=5, pady=10)

        self.update_button = ctk.CTkButton(top_frame, text="Update MSYS2 Environment", command=lambda: self._run_with_elevation(self._update_msys2, 'update'))
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
        self.log_text.tag_config("INFO", foreground="#4FC1FF")    # Light Blue
        self.log_text.tag_config("WARNING", foreground="#FFD700") # Gold/Yellow
        self.log_text.tag_config("ERROR", foreground="#FF453A")   # Red
        self.log_text.tag_config("SUCCESS", foreground="#32D74B") # Bright Green
        self.log_text.tag_config("FATAL", foreground="#FF00FF")   # Magenta

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
        with open(CONFIG_FILE, 'w') as configfile:
            self.config.write(configfile)
        self._load_config() # Refresh the status label
        self.add_log("INFO: Settings saved to fishtest.cfg")
        self._handle_github_token()

    def _initial_environment_check(self):
        """ Log initial environment status without changing UI components. """
        msys2_installed = os.path.exists(os.path.join(MSYS2_PATH, "msys2_shell.cmd"))
        worker_installed = os.path.exists(os.path.join(WORKER_DIR, "worker.py"))

        if not msys2_installed:
            self.add_log("INFO: MSYS2 not found. Please run 'Install/Re-Install Worker'.")
        elif not worker_installed:
            self.add_log("INFO: MSYS2 found, but worker files are missing. Run 'Install/Re-Install Worker' to set them up.")
        else:
            self.add_log("SUCCESS: Full environment setup is complete.")
            user = self.config.get('login', 'username', fallback=USERNAME_DEFAULT)
            password = self.config.get('login', 'password', fallback='')
            if user == USERNAME_DEFAULT or not user or not password:
                self.add_log("IMPORTANT: Before starting the worker, open the 'Settings' and enter your Fishtest username and password.")
                self.add_log("Then click 'START WORKER'.")
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
            self.worker_button.configure(text="STOP WORKER (Graceful)", fg_color="#C00000", hover_color="#A00000", state="normal")
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
        self.worker_button.configure(state='normal' if worker_installed else 'disabled',
                                     text="START WORKER", fg_color=("#3B8ED0", "#1F6AA5"))

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
            # Create request with User-Agent to avoid some basic filtering
            req = urllib.request.Request(url, headers={'User-Agent': APP_NAME})

            # 5 second timeout to avoid hanging if network is bad
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode())
                    latest_tag = data.get("tag_name", "")

                    if latest_tag:
                        self._compare_versions(latest_tag)
        except urllib.error.HTTPError as e:
            if e.code == 403:
                self.after(0, self.add_log, "WARNING: App update check skipped (GitHub API rate limit exceeded).")
            else:
                self.after(0, self.add_log, f"WARNING: App update check failed (HTTP {e.code}).")
        except Exception as e:
            self.after(0, self.add_log, f"WARNING: App update check failed. Check your internet connection before running the worker. ({e})")

    def _compare_versions(self, latest_tag):
        def parse_version(v_str):
            # Remove 'v', split by '.', convert to integers
            try:
                return tuple(map(int, v_str.lstrip('v').split('.')))
            except ValueError:
                return (0, 0, 0)

        current = parse_version(APP_VERSION)
        latest = parse_version(latest_tag)

        if latest > current:
            self.after(0, lambda: self._show_update_notification(latest_tag))
        else:
            self.after(0, self.add_log, f"INFO: You are using the latest version of the app ({APP_VERSION}).")

    def _show_update_notification(self, latest_tag):
        self.new_version_button.configure(text=f"New Version Available: {latest_tag}")
        self.new_version_button.grid()
        self.add_log(f"INFO: A new version of the Manager is available ({latest_tag}).")

    def _open_release_page(self):
        webbrowser.open(f"https://github.com/{REPO_OWNER}/{REPO_NAME}/releases/latest")

    # --- Core Actions ---
    def _run_with_elevation(self, action_func, action_arg_name):
        """ Checks for admin rights. If not present, re-launches the app with elevation. If present, runs the action. """
        if self._is_admin():
            action_func()
        else:
            try:
                # Use sys.argv[0] for robustness (works for .py and frozen .exe)
                script_path = os.path.abspath(sys.argv[0])
                # We need to pass the script path and our argument to the new elevated process
                params = f'"{script_path}" --run-as-admin={action_arg_name}'
                ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
                self.destroy()  # Close the current non-admin window
            except Exception as e:
                tkinter.messagebox.showerror("Elevation Failed", f"Could not re-launch with admin rights: {e}")

    def _run_full_setup(self):
        if not tkinter.messagebox.askyesno("Confirm Installation", "This will install the MSYS2 environment and download the fishtest worker files.\nThis may take several minutes.\n\nNote: Any existing 'worker' folder in this directory will be deleted and replaced.\n\nContinue?"):
            return

        command = f'"{get_asset_path("00_install_winget_msys2_admin.cmd")}"'
        self._run_command_in_thread(
            command,
            start_message="--- Starting MSYS2 Installation ---",
            end_message="--- MSYS2 Installation finished ---",
            on_complete=self._install_worker_files
        )

    def _install_worker_files(self):
        user = self.config.get('login', 'username')
        password = self.config.get('login', 'password')
        cores = self.config.get('parameters', 'concurrency')

        # Convert the path to the install script to an MSYS2-compatible path
        msys2_script_path = windows_to_msys2_path(get_asset_path('gui_install_worker.sh'))
        # The script is expected to run from the app's root to create the 'worker' sub-directory.
        app_run_dir = os.path.abspath(".")

        # We need to escape arguments for the shell. The script path itself should be quoted
        # with single quotes for bash to handle spaces in the MSYS2 path.
        worker_install_cmd = f"bash '{msys2_script_path}' '{user}' '{password}' '{cores}'"

        # Use -where with a quoted Windows path, which is safer than -here for paths with spaces.
        full_command = f'"{os.path.join(MSYS2_PATH, "msys2_shell.cmd")}" -defterm -ucrt64 -no-start -where "{app_run_dir}" -c "{worker_install_cmd}"'

        self._run_command_in_thread(
            full_command,
            start_message="--- Installing worker files and dependencies ---",
            end_message="--- Worker installation finished ---",
            on_complete=self._initial_environment_check
        )

    def _update_msys2(self):
        command = f'"{get_asset_path("04_update_msys2.cmd")}"'
        self._run_command_in_thread(
            command,
            start_message="--- Updating MSYS2 environment ---",
            end_message="--- MSYS2 Update finished ---"
        )

    def _handle_uninstall_click(self):
        worker_dir_exists = os.path.exists(WORKER_DIR)
        msys2_uninstaller_exists = os.path.exists(os.path.join(MSYS2_PATH, "uninstall.exe"))

        if worker_dir_exists:
            self._run_with_elevation(self._delete_worker_folder, 'delete_worker')
        elif msys2_uninstaller_exists:
            self._run_with_elevation(self._uninstall_msys2, 'uninstall_msys2')

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
        command = f'if exist "{msys2_uninstaller}" (echo Uninstalling MSYS2... & start /wait "" "{msys2_uninstaller}" /S) else (echo MSYS2 not found.)'

        self._run_command_in_thread(
            command,
            start_message="--- Starting MSYS2 Uninstallation ---",
            end_message="--- MSYS2 Uninstallation finished ---"
        )

    def _handle_github_token(self):
        token = self.config.get('Fishtest', 'github_token', fallback='').strip()
        if token:
            try:
                # In Windows, the file can be .netrc or _netrc
                netrc_path = os.path.join(os.path.expanduser("~"), "_netrc")
                netrc_content = f"machine api.github.com\nlogin {token}\npassword x-oauth-basic\n"
                with open(netrc_path, "w") as f:
                    f.write(netrc_content)
                self.add_log(f"INFO: Created/Updated '{netrc_path}' for GitHub API authentication.")
            except Exception as e:
                self.add_log(f"ERROR: Failed to create _netrc file: {e}")

    # --- Worker Start/Stop Logic ---
    def _toggle_worker(self):
        if self.worker_process and self.worker_process.poll() is None:
            self._stop_worker_gracefully()
        else:
            self._start_worker()

    def _start_worker(self):
        self.add_log("INFO: Attempting to start the worker...")

        # Reset progress state and make progress bar visible
        self.task_total_games = 0
        self.task_current_games = 0
        self.task_start_time = None
        self.task_progress_bar.set(0)
        self.task_progress_label.configure(text="")
        self.task_progress_label.grid()
        self.task_progress_bar.grid()
        self.is_waiting_for_new_task = True

        # The worker.py script must run from inside the WORKER_DIR.
        # The -where argument for msys2_shell.cmd takes a Windows path.
        # We quote it to handle spaces in the path.
        worker_dir_win_path = os.path.abspath(WORKER_DIR)

        # The command to run inside the MSYS2 shell.
        # Since -where sets the working directory, we don't need 'cd'.
        worker_command = "env/bin/python3 worker.py"

        full_command = f'"{os.path.join(MSYS2_PATH, "msys2_shell.cmd")}" -defterm -ucrt64 -no-start -where "{worker_dir_win_path}" -c "{worker_command}"'

        threading.Thread(target=self._execute_worker_process, args=(full_command,), daemon=True).start()

    def _execute_worker_process(self, command):
        try:
            self.worker_process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding='utf-8', errors='replace', shell=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            self.after(0, self._update_all_controls_state) # Update UI to "Running" state
            # --- Process each line for progress info ---
            for line in iter(self.worker_process.stdout.readline, ''):
                self.after(0, self._process_worker_output, line.strip())
            self.worker_process.stdout.close()
            self.worker_process.wait()
        except Exception as e:
            self.after(0, self.add_log, f"FATAL ERROR: Worker failed to start: {e}")
        finally:
            self.after(0, self._on_worker_stopped)

    def _stop_worker_gracefully(self):
        if not (self.worker_process and self.worker_process.poll() is None):
            return self.add_log("INFO: Worker is not running.")
        self.add_log("INFO: Stopping worker gracefully... (creating fish.exit)")
        self.worker_button.configure(text="STOPPING...", state="disabled")
        try:
            with open(os.path.join(WORKER_DIR, "fish.exit"), "w") as f: pass
        except Exception as e:
            self.add_log(f"ERROR: Could not create fish.exit file: {e}. Consider a force stop (right-click).")
            # Re-enable button if file creation fails
            self.worker_button.configure(text="STOP WORKER (Graceful)", state="normal")

    def _force_stop_worker_event(self, event):
        if self.worker_process and self.worker_process.poll() is None:
            if tkinter.messagebox.askyesno("Force Stop", "Are you sure you want to force stop the worker? Current game progress may be lost."):
                self._stop_worker_forcefully()

    def _stop_worker_forcefully(self):
        if not (self.worker_process and self.worker_process.poll() is None):
            return self.add_log("INFO: Worker is not running.")
        self.add_log("INFO: Force stopping worker...")
        try:
            subprocess.run(f"taskkill /F /PID {self.worker_process.pid} /T", check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        except Exception as e:
            self.add_log(f"ERROR: taskkill failed: {e}. Trying basic terminate.")
            self.worker_process.terminate()

    def _on_worker_stopped(self):
        self.add_log("INFO: Worker process has stopped.")
        self.worker_process = None
        # --- Hide progress UI when worker stops ---
        self.task_progress_label.grid_remove()
        self.task_progress_bar.grid_remove()
        self._update_all_controls_state() # Update UI to "Idle" state

    # --- Worker progress tracking ---
    def _process_worker_output(self, line):
        """Parses a line from the worker's stdout to update task progress."""
        self.add_log(line) # Always log the line

        if self.is_waiting_for_new_task:
            # Pattern: Started game X of Y ...
            match_total = re.search(r"^Started game \d+ of (\d+)", line)
            if match_total:
                self.is_waiting_for_new_task = False # Task found, stop looking for now
                self.task_total_games = int(match_total.group(1))
                self.task_current_games = 0 # New task, reset progress
                self.task_start_time = time.time() # Record start time of new task
                self._update_progress_display()
                return # Exit early, no need to check other patterns

        # Pattern: Games: N, Wins: ...
        match_current = re.search(r"^Games: (\d+), Wins:", line)
        if match_current:
            self.task_current_games = int(match_current.group(1))
            self._update_progress_display()
            return

        # Pattern: Task exited.
        if "Task exited." in line:
            if self.task_total_games > 0:
                self.task_current_games = self.task_total_games
                self._update_progress_display()

            # Re-arm for the next task
            self.is_waiting_for_new_task = True
            self.after(2000, self._reset_progress_for_next_task)

    # --- Update display logic to include ETA ---
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

    def _reset_progress_for_next_task(self):
        """Resets the progress display in preparation for a new task from the server."""
        # Only reset if the worker process is still alive and we are expecting a new task
        if self.worker_process and self.worker_process.poll() is None and self.is_waiting_for_new_task:
            self.task_total_games = 0
            self.task_current_games = 0
            self.task_start_time = None
            self._update_progress_display()

    # --- Threading and Utilities ---
    def _run_command_in_thread(self, command, start_message="", end_message="", on_complete=None):
        def run():
            self.is_long_operation_running = True
            self.after(0, self._update_all_controls_state)
            self.after(0, self.status_label.configure, {"text": f"Status: {start_message.replace('---', '').strip()}..."})
            if start_message: self.after(0, self.add_log, start_message)
            try:
                process = subprocess.Popen(
                    command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding='utf-8', errors='replace', shell=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                for line in iter(process.stdout.readline, ''):
                    self.after(0, self.add_log, line.strip())
                rc = process.wait()
                if end_message: self.after(0, self.add_log, end_message)
                if rc == 0:
                    if on_complete: self.after(0, on_complete)
                else:
                    self.after(0, self.add_log, f"ERROR: Process finished with non-zero exit code: {rc}")
            except Exception as e:
                self.after(0, self.add_log, f"FATAL ERROR executing command: {e}")
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
        token_entry = ctk.CTkEntry(win, width=250); token_entry.pack()

        user_entry.insert(0, self.config.get('login', 'username'))
        pass_entry.insert(0, self.config.get('login', 'password'))
        cores_entry.insert(0, self.config.get('parameters', 'concurrency'))
        token_entry.insert(0, self.config.get('Fishtest', 'github_token', fallback=''))

        def save():
            self.config.set('login', 'username', user_entry.get())
            self.config.set('login', 'password', pass_entry.get())
            self.config.set('parameters', 'concurrency', cores_entry.get())
            if not self.config.has_section('Fishtest'):
                self.config.add_section('Fishtest')
            self.config.set('Fishtest', 'github_token', token_entry.get())
            self._save_config()
            win.destroy()
        ctk.CTkButton(win, text="Save", command=save).pack(pady=20)

        register_label = ctk.CTkLabel(win, text="Don't have an account? Register here!", fg_color="transparent", text_color="#33a2ff", cursor="hand2")
        register_label.pack(pady=(0, 0))
        register_label.bind("<Button-1>", lambda e: webbrowser.open("https://tests.stockfishchess.org/signup"))

    def add_log(self, message):
        # Check if user is looking at history (scrolled up)
        is_at_bottom = self.log_text.yview()[1] == 1.0

        self.log_text.configure(state='normal')

        # Determine tag based on keywords
        tag = None
        if "FATAL" in message:
            tag = "FATAL"
        elif "ERROR" in message:
            tag = "ERROR"
        elif "WARNING" in message:
            tag = "WARNING"
        elif "SUCCESS" in message:
            tag = "SUCCESS"
        elif "INFO" in message:
            tag = "INFO"

        # Insert text with the specific tag if found, otherwise plain
        self.log_text.insert(ctk.END, message + '\n', tag)

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

    # Check for re-launch argument to auto-run an admin action
    run_action = None
    for arg in sys.argv:
        if arg.startswith('--run-as-admin='):
            run_action = arg.split('=', 1)[1]
            break

    if run_action:
        # Defer the action to allow the window to initialize
        if run_action == 'install':
            app.after(100, app._run_full_setup)
        elif run_action == 'update':
            app.after(100, app._update_msys2)
        elif run_action == 'delete_worker':
            app.after(100, app._delete_worker_folder)
        elif run_action == 'uninstall_msys2':
            app.after(100, app._uninstall_msys2)

    app.mainloop()