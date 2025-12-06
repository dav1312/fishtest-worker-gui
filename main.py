import customtkinter as ctk
import tkinter.scrolledtext
import tkinter.messagebox
import subprocess
import threading
import os
import sys
import configparser
import webbrowser
import re
import time
import json
import urllib.request
import signal

# Import the new python-based installer module
import installer

# Platform check
IS_WINDOWS = sys.platform.startswith('win32')

if IS_WINDOWS:
    import ctypes

# --- Constants ---
APP_NAME = "Fishtest Worker Manager"
APP_VERSION = "v1.1.0"
REPO_OWNER = "dav1312"
REPO_NAME = "fishtest-worker-gui"

WORKER_DIR = os.path.abspath("worker")
CONFIG_FILE_NAME = "fishtest.cfg"
CONFIG_FILE = os.path.join(WORKER_DIR, CONFIG_FILE_NAME)
EXIT_FILE_NAME = "fish.exit"
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
    # Only relevant on Windows, but kept for compatibility
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

        self._setup_window()
        self._create_widgets()
        self._load_config()
        self.after(100, self._initial_environment_check)
        self.after(101, self._update_all_controls_state) # Defer check to allow window to draw

        # Start update check in background
        self.after(2000, lambda: threading.Thread(target=self._check_latest_version_thread, daemon=True).start())

        self.protocol("WM_DELETE_WINDOW", self._on_closing)

    def _is_admin(self):
        if IS_WINDOWS:
            try:
                return ctypes.windll.shell32.IsUserAnAdmin()
            except:
                return False
        else:
            # On Unix, check if euid is 0
            return os.geteuid() == 0

    def _setup_window(self):
        self.title(f"{APP_NAME} ({APP_VERSION})")
        self.geometry("900x650")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        try:
            if IS_WINDOWS:
                self.iconbitmap(get_asset_path("icon.ico"))
            else:
                # Linux/macOS use iconphoto with a PNG
                icon_image = tkinter.PhotoImage(file=get_asset_path("icon.png"))
                self.iconphoto(False, icon_image)
        except Exception as e:
            print(f"Warning: Could not load icon: {e}")

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
        try:
            with open(CONFIG_FILE, 'w') as configfile:
                self.config.write(configfile)
            self._load_config()
            self.add_log(f"SUCCESS: Settings saved to {CONFIG_FILE_NAME}.")
            self._handle_github_token()
        except PermissionError:
            self.add_log(f"ERROR: Failed to save settings. Permission denied writing to {CONFIG_FILE}.")
        except Exception as e:
            self.add_log(f"ERROR: Failed to save settings due to an unexpected IO error: {e}")

    def _initial_environment_check(self):
        """ Log initial environment status without changing UI components. """
        worker_installed = os.path.exists(os.path.join(WORKER_DIR, "worker.py"))

        # Check for Build Tools on Unix
        import shutil
        if not IS_WINDOWS:
            missing_tools = []
            if not shutil.which("make"):
                missing_tools.append("make")
            if not shutil.which("g++") and not shutil.which("gcc"):
                missing_tools.append("g++")

            if missing_tools:
                self.add_log("WARNING: Compiler tools missing! The worker needs these to compile Stockfish.")
                if sys.platform == 'darwin': # macOS
                    self.add_log("SOLUTION: Open a terminal and run: xcode-select --install")
                else: # Linux
                    self.add_log(f"SOLUTION: Install {', '.join(missing_tools)} using your package manager.")
                    self.add_log("Example (Ubuntu/Debian): sudo apt install build-essential")
                    self.add_log("Example (Fedora): sudo dnf groupinstall 'Development Tools'")
                    self.add_log("Example (Arch): sudo pacman -S base-devel")

        # Check MSYS2 only on Windows
        msys2_installed = False
        if IS_WINDOWS:
            msys2_installed = os.path.exists(os.path.join(MSYS2_PATH, "msys2_shell.cmd"))
            if not msys2_installed:
                self.add_log("INFO: MSYS2 not found. Please run 'Install/Re-Install Worker'.")
            elif not worker_installed:
                self.add_log("INFO: MSYS2 found, but worker files are missing. Run 'Install/Re-Install Worker' to set them up.")
        else:
            if not worker_installed:
                self.add_log("INFO: Worker files are missing. Run 'Install/Re-Install Worker' to set them up.")

        if worker_installed and (not IS_WINDOWS or msys2_installed):
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

        msys2_installed = False
        msys2_uninstaller_exists = False

        if IS_WINDOWS:
            msys2_installed = os.path.exists(os.path.join(MSYS2_PATH, "msys2_shell.cmd"))
            msys2_uninstaller_exists = os.path.exists(os.path.join(MSYS2_PATH, "uninstall.exe"))

        worker_installed = os.path.exists(os.path.join(WORKER_DIR, "worker.py"))
        worker_dir_exists = os.path.exists(WORKER_DIR)

        self.setup_button.configure(state='normal')
        self.settings_button.configure(state='normal')

        # MSYS2 update button is only relevant on Windows
        if IS_WINDOWS:
            self.update_button.configure(state='normal' if msys2_installed else 'disabled')
        else:
            self.update_button.configure(state='disabled')

        self.worker_button.configure(state='normal' if worker_installed else 'disabled',
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
                if IS_WINDOWS:
                    # Use sys.argv[0] for robustness (works for .py and frozen .exe)
                    script_path = os.path.abspath(sys.argv[0])
                    # We need to pass the script path and our argument to the new elevated process
                    params = f'"{script_path}" --run-as-admin={action_arg_name}'
                    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
                    self.destroy()  # Close the current non-admin window
                else:
                    # Unix elevation using sudo
                    args = ['sudo', sys.executable] + sys.argv + [f'--run-as-admin={action_arg_name}']
                    subprocess.call(args)
                    self.destroy()
            except Exception as e:
                tkinter.messagebox.showerror("Elevation Failed", f"Could not re-launch with admin rights: {e}")

    def _run_full_setup(self):
        if not tkinter.messagebox.askyesno("Confirm Installation", "This will download and install the fishtest worker files.\n\nNote: Any existing 'worker' folder in this directory will be deleted and replaced.\n\nContinue?"):
            return

        # On Windows, we still use MSYS2 for the compiler environment.
        # Check if it exists, if not, install it using the cmd script.
        if IS_WINDOWS:
            msys2_installed = os.path.exists(os.path.join(MSYS2_PATH, "msys2_shell.cmd"))
            if not msys2_installed:
                command = f'"{get_asset_path("00_install_winget_msys2_admin.cmd")}"'
                self._run_command_in_thread(
                    command,
                    start_message="--- Starting MSYS2 Installation (Windows) ---",
                    end_message="--- MSYS2 Installation finished ---",
                    on_complete=self._install_worker_files
                )
                return

        # If we are here, either we are on Unix, or MSYS2 is already installed.
        # Proceed directly to Python-based worker installation.
        self._install_worker_files()

    def _install_worker_files(self):
        # We use the new pure-Python installer module here
        user = self.config.get('login', 'username')
        password = self.config.get('login', 'password')
        cores = self.config.get('parameters', 'concurrency')

        # Launch the installer in a thread to keep GUI responsive
        threading.Thread(
            target=self._run_python_installer_thread,
            args=(user, password, cores),
            daemon=True
        ).start()

    def _run_python_installer_thread(self, user, password, cores):
        """ Helper thread function to run the Installer class logic """
        self.is_long_operation_running = True
        self.after(0, self._update_all_controls_state)

        # Helper to bridge installer logs to GUI logs
        def log_bridge(msg):
            self.after(0, self.add_log, msg)

        try:
            # Run installation
            inst = installer.Installer(os.path.abspath("."), log_callback=log_bridge)
            success = inst.install(user, password, cores)

            if success:
                self.after(0, self._initial_environment_check)
            else:
                self.after(0, lambda: tkinter.messagebox.showerror("Error", "Installation failed. Check logs."))

        except Exception as e:
            self.after(0, self.add_log, f"FATAL ERROR during installation: {e}")

        finally:
            self.is_long_operation_running = False
            self.after(0, self._update_all_controls_state)

    def _update_msys2(self):
        if not IS_WINDOWS:
            self.add_log("INFO: MSYS2 update is only available on Windows.")
            return

        command = f'"{get_asset_path("04_update_msys2.cmd")}"'
        self._run_command_in_thread(
            command,
            start_message="--- Updating MSYS2 environment ---",
            end_message="--- MSYS2 Update finished ---"
        )

    def _handle_uninstall_click(self):
        worker_dir_exists = os.path.exists(WORKER_DIR)

        if IS_WINDOWS:
            msys2_uninstaller_exists = os.path.exists(os.path.join(MSYS2_PATH, "uninstall.exe"))
        else:
            msys2_uninstaller_exists = False

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

        # Use Python generic deletion instead of shell commands
        def delete_task():
            self.is_long_operation_running = True
            self.after(0, self._update_all_controls_state)
            self.after(0, self.add_log, "--- Deleting worker folder ---")

            try:
                import shutil
                if os.path.exists(worker_dir_abs):
                    shutil.rmtree(worker_dir_abs)
                    self.after(0, self.add_log, "--- Worker folder deleted ---")
                else:
                    self.after(0, self.add_log, "Worker directory not found.")
            except Exception as e:
                self.after(0, self.add_log, f"ERROR deleting folder: {e}")
            finally:
                self.is_long_operation_running = False
                self.after(0, self._update_all_controls_state)

        threading.Thread(target=delete_task, daemon=True).start()

    def _uninstall_msys2(self):
        if not IS_WINDOWS:
            return

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
                # On Unix it should be .netrc
                filename = "_netrc" if IS_WINDOWS else ".netrc"
                netrc_path = os.path.join(os.path.expanduser("~"), filename)

                netrc_content = f"machine api.github.com\nlogin {token}\npassword x-oauth-basic\n"

                # Set restrictive permissions on Unix for security
                if not IS_WINDOWS:
                    # Create file first if not exists to set permissions
                    if not os.path.exists(netrc_path):
                        open(netrc_path, 'w').close()
                    os.chmod(netrc_path, 0o600)

                with open(netrc_path, "w") as f:
                    f.write(netrc_content)
                self.add_log(f"INFO: Created/Updated '{netrc_path}' for GitHub API authentication.")
            except Exception as e:
                self.add_log(f"ERROR: Failed to create netrc file: {e}")

    # --- Worker Start/Stop Logic ---
    def _toggle_worker(self):
        # Check if the object exists, rather than checking if Windows thinks it's running.
        if self.worker_process is not None:
            self._stop_worker_gracefully()
        else:
            self._start_worker()

    def _start_worker(self):
        self.add_log("INFO: Attempting to start the worker...")

        # Clean up fish.exit before starting the process
        exit_file_path = os.path.join(WORKER_DIR, EXIT_FILE_NAME)
        if os.path.exists(exit_file_path):
            try:
                os.remove(exit_file_path)
                self.add_log(f"INFO: Cleaned up leftover {EXIT_FILE_NAME} file.")
            except Exception as e:
                self.add_log(f"ERROR: Could not clean up leftover {EXIT_FILE_NAME} file. The worker may not start correctly: {e}")

        # Reset progress state and make progress bar visible
        self.task_total_games = 0
        self.task_current_games = 0
        self.task_start_time = None
        self.task_progress_bar.set(0)
        self.task_progress_label.configure(text="")
        self.task_progress_label.grid()
        self.task_progress_bar.grid()

        # Platform specific python path within the venv created by installer.py
        worker_script = os.path.join(WORKER_DIR, "worker.py")

        if IS_WINDOWS:
            python_exe = os.path.join(WORKER_DIR, "env", "Scripts", "python.exe")
        else:
            python_exe = os.path.join(WORKER_DIR, "env", "bin", "python")

        if not os.path.exists(python_exe):
            self.add_log(f"ERROR: Python interpreter not found at {python_exe}. Please Re-Install Worker.")
            return

        # Prepare arguments as a list (safer and cross-platform)
        cmd = [python_exe, worker_script]

        threading.Thread(target=self._execute_worker_process, args=(cmd,), daemon=True).start()

    def _execute_worker_process(self, command):
        try:
            # Windows specific flags to hide console window
            creationflags = 0
            if IS_WINDOWS:
                creationflags = subprocess.CREATE_NO_WINDOW

            self.worker_process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                shell=False, # Use False when passing a list
                cwd=WORKER_DIR, # Set working directory explicitly
                creationflags=creationflags
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
        # Only return if the object is actually None
        # If the object exists but is 'dead' (Zombie), we continue anyway.
        if self.worker_process is None:
            return self.add_log("INFO: Worker is not running.")

        # If poll() returns a value (is not None), the wrapper process is dead.
        # But since we are inside this function, self.worker_process is NOT None.
        # This is the "Zombie" state.
        if self.worker_process.poll() is not None:
            self.add_log("WARNING: Wrapper process is dead. Attempting to stop the worker.")

        self.add_log(f"INFO: Stopping worker gracefully... (creating {EXIT_FILE_NAME} file)")
        self.worker_button.configure(text="STOPPING...", state="disabled")
        try:
            with open(os.path.join(WORKER_DIR, EXIT_FILE_NAME), "w") as f: pass
        except Exception as e:
            self.add_log(f"ERROR: Could not create {EXIT_FILE_NAME} file: {e}. Consider a force stop (right-click).")
            # Re-enable button if file creation fails
            self.worker_button.configure(text="STOP WORKER (Graceful)", state="normal")

    def _force_stop_worker_event(self, event):
        # Check if the object exists, rather than checking if Windows thinks it's running.
        if self.worker_process is not None:
            if tkinter.messagebox.askyesno("Force Stop", "Are you sure you want to force stop the worker? Current game progress may be lost."):
                self._stop_worker_forcefully()

    def _stop_worker_forcefully(self):
        # Check object existence only.
        # This ensures we can clean up even if the wrapper process died silently.
        if self.worker_process is None:
            return self.add_log("INFO: Worker is not running.")

        self.add_log("INFO: Force stopping worker...")
        try:
            if IS_WINDOWS:
                subprocess.run(f"taskkill /F /PID {self.worker_process.pid} /T", check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                # Unix kill
                os.kill(self.worker_process.pid, signal.SIGKILL)
        except Exception as e:
            # If the process is already dead (Zombie), kill will fail.
            self.add_log(f"WARNING: kill failed (process might be dead): {e}")
            try:
                self.worker_process.terminate()
            except Exception as e:
                # Log this just in case, but usually it means the process is already gone.
                self.add_log(f"DEBUG: Internal terminate() failed (ignoring): {e}")

        # Clean up the lingering fish.exit file left from the previous *graceful* attempt (if any)
        exit_file_path = os.path.join(WORKER_DIR, EXIT_FILE_NAME)
        if os.path.exists(exit_file_path):
            try:
                os.remove(exit_file_path)
                self.add_log(f"INFO: Cleaned up leftover {EXIT_FILE_NAME} file.")
            except Exception as e:
                self.add_log(f"ERROR: Could not clean up leftover {EXIT_FILE_NAME} file: {e}")

    def _on_worker_stopped(self):
        self.add_log("SUCCESS: Worker process has stopped.")
        self.worker_process = None
        # --- Hide progress UI when worker stops ---
        self.task_progress_label.grid_remove()
        self.task_progress_bar.grid_remove()
        self._update_all_controls_state() # Update UI to "Idle" state

    # --- Worker progress tracking ---
    def _process_worker_output(self, line):
        """Parses a line from the worker's stdout to update task progress."""
        self.add_log(line) # Always log the line

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

    # --- Threading and Utilities ---
    def _run_command_in_thread(self, command, start_message="", end_message="", on_complete=None):
        def run():
            self.is_long_operation_running = True
            self.after(0, self._update_all_controls_state)
            self.after(0, self.status_label.configure, {"text": f"Status: {start_message.replace('---', '').strip()}..."})
            if start_message: self.after(0, self.add_log, start_message)
            try:
                # Windows specific flags for hidden window
                creationflags = 0
                if IS_WINDOWS:
                    creationflags = subprocess.CREATE_NO_WINDOW

                process = subprocess.Popen(
                    command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding='utf-8', errors='replace', shell=True,
                    creationflags=creationflags
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