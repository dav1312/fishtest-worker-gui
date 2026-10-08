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

# On a reinstall n_cores may contain a string like "2 ; = 2 cores", so keep the first integer
n_cores=$(echo "$n_cores" | grep -oE '[0-9]+' | head -n 1)
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

echo "--- Removing temporary files from previous runs if they exist ---"
rm -rf ___fishtest_tmp_* 2>/dev/null || true

echo "--- Downloading and extracting fishtest worker ---"
tmp_dir="___fishtest_tmp_${RANDOM}"
mkdir -p "$tmp_dir"
cd "$tmp_dir"
wget https://github.com/official-stockfish/fishtest/archive/master.zip
unzip -q master.zip "fishtest-master/worker/**"
cd "fishtest-master/worker"

echo "--- Setting up Python virtual environment ---"
python3 -m venv "env"
env/bin/python3 -m pip install -q --upgrade pip setuptools wheel
env/bin/python3 -m pip install -q requests

echo "--- Generating fishtest.cfg ---"
env/bin/python3 worker.py "$usr_name" "$usr_pwd" --concurrency "$n_cores" --only_config --no_validation
echo "Successfully created fishtest.cfg"

cat << EOF > fishtest.cmd
@echo off
set "HERE=%~dp0"
set "PATH=C:\msys64\ucrt64\bin;C:\msys64\usr\bin;%PATH%"
cd /d "%HERE%"
env\\bin\\python3.exe worker.py
EOF

echo "--- Finalizing installation ---"
cd "$ORIG_DIR"
# Replace the old worker only now, so a failed install keeps it
echo "--- Replacing old worker directory ---"
rm -rf worker
mv "$tmp_dir/fishtest-master/worker" .

echo "--- Installation complete! ---"