# Fishtest Worker GUI

A user-friendly graphical interface for setting up and running a [Fishtest](https://tests.stockfishchess.org/tests) worker on Windows.

It automates the installation of MSYS2 and the Fishtest worker scripts, manages configuration, and provides real-time log feedback.

## Prerequisites

-   Windows 10 or Windows 11.
-   An active internet connection.

## How to Use

### 1. Download

Download the `fishtest-worker-gui.exe` file from the [Releases page](https://github.com/dav1312/fishtest-worker-gui/releases).  
Place the executable in a new, empty folder where you want to manage your worker (e.g., `C:\Users\%username%\Downloads\FishtestWorker`).

### 2. Installation

1.  Run `fishtest-worker-gui.exe`.
2.  Click the **Install/Re-Install Worker** button.
3.  A Windows User Account Control (UAC) prompt will appear asking for Administrator privileges. Click **Yes**.
4.  The application will automatically download and install MSYS2 (to `C:\msys64`) and then set up the Fishtest worker files inside a new `worker` sub-folder.
5.  Wait for the process to complete. You can monitor the progress in the log viewer at the bottom of the window. This may take several minutes.

### 3. Configuration

1.  Click the **Settings** button.
2.  In the new window, enter your Fishtest **username**, **password**, and the number of **cores** (concurrency) you wish to use.
3.  Click **Save**. Your details will be saved to `worker/fishtest.cfg`.

### 4. Running the Worker

-   **To Start**: Click the large **START WORKER** button. All other controls will be disabled to prevent conflicts. The log viewer will now show the output from the Fishtest worker.
-   **To Stop Gracefully**: Click the **STOP WORKER (Graceful)** button. This creates a `fish.exit` file, which tells the worker to finish its current task and then shut down cleanly. This is the recommended way to stop the worker.
-   **To Force Stop**: If the worker is unresponsive, **right-click** the red "STOP WORKER" button. You will be asked to confirm. This immediately terminates the worker process, and any work-in-progress may be lost.

### 5. Maintenance and Uninstallation

-   **Update MSYS2**: Click the **Update MSYS2 Environment** button to run the standard update commands for the underlying environment. This requires Administrator rights.
-   **Uninstall**: The uninstallation process is staged, first removing the worker files and then uninstalling MSYS2. Both steps require Administrator rights.
    1.  **Delete Worker Folder**: The button will first offer to delete the local `worker` folder. This removes your worker scripts and configuration.
    2.  **Uninstall MSYS2**: After the `worker` folder is gone, the same button will change its text to "Uninstall MSYS2". Clicking it will run the MSYS2 uninstaller, completely removing it from your system (`C:\msys64`).

## Building from Source

If you want to build the application from the source code, follow these steps:

1.  Clone the repository.
2.  Create and activate a Python virtual environment.
3.  Install the required packages:
    ```sh
    pip install -r requirements.txt
    ```
4.  Build the executable using PyInstaller.
    ```sh
    pyinstaller --name "fishtest-worker-gui" --onefile --noconsole --add-data "assets;assets" main.py
    ```
5.  The final `.exe` will be located in the `dist` folder.

## License

This project is licensed under the GNU General Public License v3.0. See the [LICENSE](LICENSE) file for details.