#!/usr/bin/env bash
# Run by mirror-voice.service on the Pi: wait for the model server, then start the
# voice loop. The display is shown by the kiosk, so never open a browser from here.
set -euo pipefail
cd "$(dirname "$0")/../.."
export PATH="$HOME/.local/bin:$PATH"

port=$(uv run --no-sync python -c "
from mirror_voice.config import load_config
print(load_config().llm.port)")

# The first boot downloads the model, which can take a while, so wait as long as it takes.
waited=0
until curl -sf "http://127.0.0.1:$port/health" >/dev/null; do
  if ((waited % 30 == 0)); then
    echo "Waiting for the model server on port $port (${waited}s so far)..."
  fi
  sleep 2
  waited=$((waited + 2))
done

exec uv run --no-sync mirror-talk --no-browser
