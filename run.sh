#!/bin/bash
set -e

cd "$(dirname "$0")"

# Start Ollama if not already running
if ! pgrep -x ollama > /dev/null; then
    echo "Starting Ollama..."
    ollama serve &>/dev/null &
    # Wait until Ollama is ready
    for i in $(seq 1 30); do
        if curl -sf http://localhost:11434 &>/dev/null; then
            break
        fi
        sleep 1
    done
fi

exec venv/bin/python main.py
