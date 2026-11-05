#!/usr/bin/env bash
# One-time setup: installs tools, Python deps, the voice, and your private persona copy.
# Safe to re-run any time.
set -euo pipefail
cd "$(dirname "$0")/.."

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

say "Checking tools"
if ! command -v uv >/dev/null; then
  echo "Installing uv (Python package manager)..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
if ! command -v llama-server >/dev/null; then
  if [[ "$(uname)" == "Darwin" ]] && command -v brew >/dev/null; then
    echo "Installing llama.cpp via Homebrew..."
    brew install llama.cpp
  else
    echo "llama.cpp (llama-server) isn't installed."
    echo "  macOS: brew install llama.cpp"
    echo "  Linux / Raspberry Pi: see https://github.com/ggml-org/llama.cpp (Pi script coming later)"
    exit 1
  fi
fi

say "Installing Python dependencies"
uv sync

say "Downloading voice"
voice=$(uv run python -c "from mirror_voice.config import load_config; print(load_config().tts.voice)")
voices_dir=$(uv run python -c "from mirror_voice.config import load_config; print(load_config().tts.voices_dir)")
mkdir -p "$voices_dir"
if [[ -f "$voices_dir/$voice.onnx" ]]; then
  echo "Already have $voice"
else
  uv run python -m piper.download_voices --data-dir "$voices_dir" "$voice"
fi

say "Personal persona"
persona=personality/personas/mirror.md
if [[ -f "$persona" ]]; then
  echo "Keeping your existing $persona"
else
  cp personality/personas/mirror.example.md "$persona"
  echo "Created $persona from the template. It's git-ignored: make it yours."
fi

say "Done. Start talking with: scripts/talk.sh"
echo "(First run downloads the ~2 GB model, so give it a few minutes.)"
