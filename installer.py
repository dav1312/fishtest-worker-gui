import os
import sys
import urllib.request
import zipfile
import shutil
import subprocess
import venv
import platform

# Constants
FISHTEST_URL = "https://github.com/official-stockfish/fishtest/archive/master.zip"
WORKER_DIR_NAME = "worker"

class Installer:
    def __init__(self, base_dir, log_callback=None):
        """
        :param base_dir: The directory where the 'worker' folder will be created.
        :param log_callback: A function that takes a string message (for GUI updates).
        """
        self.base_dir = base_dir
        self.worker_path = os.path.join(base_dir, WORKER_DIR_NAME)
        self.log_callback = log_callback if log_callback else print
        self.is_windows = sys.platform.startswith('win32')

    def log(self, message):
        self.log_callback(message)

    def _get_venv_python(self):
        """Returns the path to the python executable inside the venv."""
        if self.is_windows:
            return os.path.join(self.worker_path, "env", "Scripts", "python.exe")
        else:
            return os.path.join(self.worker_path, "env", "bin", "python")

    def install(self, username, password, concurrency):
        try:
            self.log(f"--- Starting Installation in {self.worker_path} ---")

            # 1. Clean existing directory
            if os.path.exists(self.worker_path):
                self.log("Removing existing worker directory...")
                shutil.rmtree(self.worker_path)

            os.makedirs(self.worker_path, exist_ok=True)

            # 2. Download Fishtest
            zip_path = os.path.join(self.base_dir, "fishtest_master.zip")
            self.log(f"Downloading Fishtest from {FISHTEST_URL}...")

            # Using custom user-agent to avoid Github API blocking basic scripts
            req = urllib.request.Request(FISHTEST_URL, headers={'User-Agent': "FishtestManager"})
            with urllib.request.urlopen(req) as response, open(zip_path, 'wb') as out_file:
                shutil.copyfileobj(response, out_file)

            # 3. Extract
            self.log("Extracting files...")
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                # We need to strip the top-level folder "fishtest-master/worker"
                # This is slightly complex because zipfile extracts full paths.
                # simpler approach: extract all, then move files.
                temp_extract_dir = os.path.join(self.base_dir, "temp_extract")
                zip_ref.extractall(temp_extract_dir)

            # Move the inner 'worker' folder to our target location
            source_worker = os.path.join(temp_extract_dir, "fishtest-master", "worker")

            # Move contents of source_worker to self.worker_path
            for file_name in os.listdir(source_worker):
                shutil.move(os.path.join(source_worker, file_name), self.worker_path)

            # Cleanup temp files
            self.log("Cleaning up temporary download files...")
            os.remove(zip_path)
            shutil.rmtree(temp_extract_dir)

            # 4. Create Virtual Environment
            self.log("Creating Python Virtual Environment (venv)...")
            venv_dir = os.path.join(self.worker_path, "env")

            # EnvBuilder with with_pip=True
            builder = venv.EnvBuilder(with_pip=True)
            builder.create(venv_dir)

            venv_python = self._get_venv_python()
            if not os.path.exists(venv_python):
                raise FileNotFoundError(f"Virtual environment python not found at {venv_python}")

            # 5. Install Dependencies (requests)
            self.log("Installing dependencies (requests, wheel)...")
            subprocess.check_call(
                [venv_python, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"],
                stdout=subprocess.DEVNULL
            )
            subprocess.check_call(
                [venv_python, "-m", "pip", "install", "requests"],
                stdout=subprocess.DEVNULL
            )

            # 6. Generate Configuration
            self.log("Generating fishtest.cfg configuration...")

            # We run the downloaded worker.py to generate the config
            worker_script = os.path.join(self.worker_path, "worker.py")

            cmd = [
                venv_python,
                worker_script,
                username,
                password,
                "--concurrency", str(concurrency),
                "--only_config",
                "--no_validation"
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise Exception(f"Config generation failed: {result.stderr}")

            self.log("SUCCESS: Installation complete.")
            return True

        except Exception as e:
            self.log(f"FATAL ERROR during installation: {e}")
            return False