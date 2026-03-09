#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "Installing system dependencies..."
sudo apt install -y python3-dev portaudio19-dev espeak-ng

echo "Installing Ollama..."
if ! command -v ollama &> /dev/null; then
    curl -fsSL https://ollama.com/install.sh | sh
else
    echo "Ollama already installed, skipping."
fi

echo "Pulling Ollama model..."
ollama pull llama3.2:3b

if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

echo "Installing Python dependencies..."
venv/bin/pip install -r requirements.txt

PIPER_MODEL="en_US-ryan-high"
PIPER_BASE="https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/ryan/high"

if [ ! -f "${PIPER_MODEL}.onnx" ]; then
    echo "Downloading Piper voice model '${PIPER_MODEL}'..."
    wget -q --show-progress -O "${PIPER_MODEL}.onnx" "${PIPER_BASE}/${PIPER_MODEL}.onnx"
    wget -q -O "${PIPER_MODEL}.onnx.json" "${PIPER_BASE}/${PIPER_MODEL}.onnx.json"
fi

echo "Done. Run ./run.sh to start Sofia."
