#!/usr/bin/env bash
# Start the model server (if it isn't already running) and talk to Mirror.
# Extra arguments go to mirror-talk, e.g. `scripts/talk.sh --selftest`.
set -euo pipefail
cd "$(dirname "$0")/.."

read -r port model ctx < <(uv run python -c "
from mirror_voice.config import load_config
c = load_config().llm
print(c.port, c.model, c.context_size)")

url="http://127.0.0.1:$port"
log=models/llama-server.log
server_pid=""

cleanup() { [[ -n "$server_pid" ]] && kill "$server_pid" 2>/dev/null || true; }
trap cleanup EXIT

if curl -sf "$url/health" >/dev/null; then
  echo "Model server already running on port $port, using it."
else
  echo "Starting model server ($model)..."
  echo "First run downloads the model; progress is in $log"
  llama-server -hf "$model" --port "$port" -c "$ctx" >"$log" 2>&1 &
  server_pid=$!
  until curl -sf "$url/health" >/dev/null; do
    if ! kill -0 "$server_pid" 2>/dev/null; then
      echo "Model server stopped unexpectedly. Last lines of $log:"
      tail -20 "$log"
      exit 1
    fi
    sleep 1
  done
  echo "Model ready."
fi

uv run mirror-talk "$@"
