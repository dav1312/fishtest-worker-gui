#!/bin/bash
# NON-INTERACTIVE fishtest worker installer for GUI use

# Arguments from the GUI
usr_name="$1"
usr_pwd="$2"
n_cores="$3"

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

# 1. Update system and install essential packages
echo "--- Updating system and installing required packages ---"
pacman -Syuu --noconfirm
pacman -S --noconfirm --needed unzip make mingw-w64-ucrt-x86_64-gcc mingw-w64-ucrt-x86_64-python

echo "--- Cleaning package cache to save disk space ---"
pacman -Scc --noconfirm

# 2. Delete old worker directory to ensure a clean slate
echo "--- Removing old worker directory if it exists ---"
rm -rf worker

# 3. Download and extract the fishtest worker
echo "--- Downloading and extracting fishtest worker ---"
tmp_dir=___${RANDOM}
mkdir ${tmp_dir} && pushd ${tmp_dir} > /dev/null
wget https://github.com/official-stockfish/fishtest/archive/master.zip
unzip -q master.zip "fishtest-master/worker/**" # -q for quiet
pushd fishtest-master/worker > /dev/null

# 4. Setup a virtual environment and install dependencies
echo "--- Setting up Python virtual environment ---"
python3 -m venv "env"
env/bin/python3 -m pip install -q --upgrade pip setuptools wheel
env/bin/python3 -m pip install -q requests

# 5. Write fishtest.cfg using the worker's own logic
echo "--- Generating fishtest.cfg ---"
env/bin/python3 worker.py "$usr_name" "$usr_pwd" --concurrency "$n_cores" --only_config --no_validation
if [ $? -eq 0 ]; then
    echo "Successfully created fishtest.cfg"
else
    echo "Error: Failed to create fishtest.cfg"
    exit 1
fi

# 6. Create the fishtest.cmd launcher
cat << EOF > fishtest.cmd
@echo off
set "HERE=%~dp0"
set "PATH=C:\msys64\ucrt64\bin;C:\msys64\usr\bin;%PATH%"
cd /d "%HERE%"
env\\bin\\python3.exe worker.py
EOF

echo "--- Finalizing installation ---"
popd > /dev/null && popd > /dev/null
mv $tmp_dir/fishtest-master/worker .
rm -rf $tmp_dir

echo "--- Installation complete! ---"