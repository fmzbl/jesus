# Sofia - Voice Assistant for Raspberry Pi

## Quick start

### 1. System packages
```bash
sudo apt update
sudo apt install -y python3-pip python3-venv portaudio19-dev espeak-ng
```

### 2. Ollama (LLM runtime)
```bash
curl -fsSL https://ollama.ai/install.sh | sh
ollama pull llama3.2:3b   # default model
```

### 3. Vosk speech model
```bash
wget https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
unzip vosk-model-small-en-us-0.15.zip
mv vosk-model-small-en-us-0.15 vosk-model
```

### 4. Python dependencies
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 5. Run
```bash
source venv/bin/activate
python main.py
```

---

## Usage

| Say | Effect |
|-----|--------|
| "Sofia start conversation" | Wake up Sofia |
| *(your prompt)* | Sofia processes and reads answer aloud |
| "stop" | Interrupt Sofia while she's speaking |
| "Sofia stop conversation" | End session, return to standby |

Conversations are saved to `conversations/session_YYYYMMDD_HHMMSS.json`.

---

## config.json

Auto-created on first run. Options:

```json
{
  "model": "llama3.2:3b",
  "available_models": ["llama3.2:1b", "llama3.2:3b", "phi3:mini", "gemma2:2b", "mistral:7b"],
  "tts_engine": "espeak",
  "tts_voice": "en",
  "speech_rate": 150,
  "piper_model": "en_US-lessac-medium",
  "user_name": "Facu",
  "vosk_model_path": "vosk-model",
  "sample_rate": 16000
}
```

### Switch model
Edit `model` in `config.json` — takes effect on the next conversation.

### Piper TTS (better voice quality)
```bash
pip install piper-tts
python -c "import piper; piper.download_model('en_US-lessac-medium', '.')"
```
Then set `"tts_engine": "piper"` in `config.json`.

---

## Models for Raspberry Pi

| Model | RAM needed | Notes |
|-------|-----------|-------|
| `llama3.2:1b` | ~1 GB | Fastest |
| `llama3.2:3b` | ~2 GB | Good balance (default) |
| `phi3:mini` | ~2.3 GB | Microsoft, efficient |
| `gemma2:2b` | ~1.6 GB | Google, fast |
| `mistral:7b` | ~5 GB | Best quality, needs 8 GB RAM |

Tool calling (web search) works with llama3.2 and mistral.
For phi3/gemma, the LLM will answer without web search.

---

## Hardware tips
- USB microphone positioned away from the speaker reduces echo
- RPi 5 with 8 GB RAM handles 7B models comfortably
- RPi 4 with 4 GB RAM: stick to 1B–3B models
