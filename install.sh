#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "Installing system dependencies..."
sudo apt install -y python3-dev portaudio19-dev espeak-ng

if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

echo "Installing Python dependencies..."
venv/bin/pip install -r requirements.txt

echo "Done. Run ./run.sh to start Sofia."
