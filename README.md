# Fishtest Worker GUI

A user-friendly graphical interface for setting up and running a [Fishtest](https://tests.stockfishchess.org/tests) worker on Windows.

It automates the installation of MSYS2 and the Fishtest worker scripts, manages configuration, and provides real-time log feedback.

![app](https://github.com/user-attachments/assets/0eee98c0-28c4-4c89-9e2b-9968aa7f0874)

## Prerequisites

-   Windows 10 or Windows 11.
-   An active internet connection.

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