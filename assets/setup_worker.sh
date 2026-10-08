#!/bin/bash
# NON-INTERACTIVE fishtest worker installer for GUI use
set -e

# Values from the GUI. They are passed as environment variables, not arguments,
# so that special characters in them are never interpreted by cmd or bash.
usr_name="$FT_USER"
usr_pwd="$FT_PASSWORD"
n_cores="$FT_CORES"
# Don't pass the password on to every program this script starts
unset FT_USER FT_PASSWORD FT_CORES

echo "--- Starting non-interactive worker installation ---"
echo "Username: $usr_name"

# n_cores should be a positive integer
# but if we are reinstalling it might contain a string like "2 ; = 2 cores"
# so we extract the first integer from it
n_cores=$(echo "$n_cores" | grep -oE '[0-9]+' | head -n 1)
# if n_cores is empty or not a number, default to 1
if ! [[ "$n_cores" =~ ^[0-9]+$ ]]; then
    echo "Invalid number of cores specified. Defaulting to 1 core."
    n_cores=1
fi
echo "Cores: $n_cores"

ORIG_DIR=$(pwd)
tmp_dir=""

cleanup() {
    cd "$ORIG_DIR" 2>/dev/null || true
    if [ -n "$tmp_dir" ] && [ -d "$tmp_dir" ]; then
        rm -rf "$tmp_dir"
    fi
}
trap cleanup EXIT

# 1. Clean up any leftover temp directories from prior runs
echo "--- Removing temporary files from previous runs if they exist ---"
rm -rf ___fishtest_tmp_* 2>/dev/null || true

# 2. Download and extract the fishtest worker
echo "--- Downloading and extracting fishtest worker ---"
tmp_dir="___fishtest_tmp_${RANDOM}"
mkdir -p "$tmp_dir"
cd "$tmp_dir"
wget https://github.com/official-stockfish/fishtest/archive/master.zip
unzip -q master.zip "fishtest-master/worker/**"
cd "fishtest-master/worker"

# 3. Setup a virtual environment and install dependencies
echo "--- Setting up Python virtual environment ---"
python3 -m venv "env"
env/bin/python3 -m pip install -q --upgrade pip setuptools wheel
env/bin/python3 -m pip install -q requests

# 4. Write fishtest.cfg using the worker's own logic
echo "--- Generating fishtest.cfg ---"
env/bin/python3 worker.py "$usr_name" "$usr_pwd" --concurrency "$n_cores" --only_config --no_validation
echo "Successfully created fishtest.cfg"

# 5. Create the fishtest.cmd launcher
cat << EOF > fishtest.cmd
@echo off
set "HERE=%~dp0"
set "PATH=C:\msys64\ucrt64\bin;C:\msys64\usr\bin;%PATH%"
cd /d "%HERE%"
env\\bin\\python3.exe worker.py
EOF

# 6. Finalize installation
echo "--- Finalizing installation ---"
cd "$ORIG_DIR"
# The old worker directory is only removed once the new one is ready,
# so a failed download or setup leaves the existing installation intact
echo "--- Replacing old worker directory ---"
rm -rf worker
mv "$tmp_dir/fishtest-master/worker" .

echo "--- Installation complete! ---"