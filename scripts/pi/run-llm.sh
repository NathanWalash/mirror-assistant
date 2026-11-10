#!/usr/bin/env bash
# Run by mirror-llm.service on the Pi: llama-server with the port, model and context
# size from config.yaml (falling back to config.example.yaml), like scripts/talk.sh.
# The first start downloads the model (~2 GB) into ~/.cache/llama.cpp.
set -euo pipefail
cd "$(dirname "$0")/../.."
export PATH="$HOME/.local/bin:$PATH"

read -r port model ctx < <(uv run --no-sync python -c "
from mirror_voice.config import load_config
c = load_config().llm
print(c.port, c.model, c.context_size)")

echo "Starting llama-server: $model on 127.0.0.1:$port, context $ctx"
exec llama-server -hf "$model" --host 127.0.0.1 --port "$port" -c "$ctx"
