#!/usr/bin/env bash
# Copy this checkout (including your private config.yaml and personas) to the Pi, update
# its Python deps and restart Mirror. Run from your Mac:
#   MIRROR_HOST=you@mirror.local scripts/pi/deploy.sh             # every deploy
#   MIRROR_HOST=you@mirror.local scripts/pi/deploy.sh --install   # first time, or to re-run setup
# The host can also be the first argument instead of MIRROR_HOST. The repo goes to
# ~/mirror-assistant on the Pi unless you set MIRROR_DIR (relative to the Pi's home).
#
# It sends your working tree as it is, uncommitted changes included, so you can try
# things on the Pi before committing. The Pi's .git, .venv and models are left alone.
set -euo pipefail
cd "$(dirname "$0")/../.."

install=false
host=${MIRROR_HOST:-}
for arg in "$@"; do
  case "$arg" in
    --install) install=true ;;
    -h | --help)
      sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    -*)
      echo "Unknown option: $arg"
      exit 1
      ;;
    *) host=$arg ;;
  esac
done
if [[ -z "$host" ]]; then
  echo "Which Pi? Set MIRROR_HOST (e.g. MIRROR_HOST=you@mirror.local) or pass it as an argument."
  exit 1
fi
dir=${MIRROR_DIR:-mirror-assistant}

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

# rsync --delete would remove the Pi's copy of a private file you don't have here, so
# insist on them (scripts/setup.sh creates both).
for private in config.yaml personality/personas/mirror.md; do
  if [[ ! -f "$private" ]]; then
    echo "Missing $private. Run scripts/setup.sh first (or create it), then deploy."
    exit 1
  fi
done

say "Checking $host"
if ! ssh "$host" true; then
  echo "Can't reach $host over SSH. See Troubleshooting in docs/pi.md."
  exit 1
fi
if ! ssh "$host" "command -v rsync >/dev/null"; then
  echo "Installing rsync on the Pi..."
  ssh -t "$host" "sudo apt-get update && sudo apt-get install -y rsync"
fi

say "Copying to $host:~/$dir"
# Ignored files are copied on purpose: config.yaml, personas and .env are private (not in
# git) but the Pi needs them. Excluded paths are never deleted on the Pi.
rsync -az --delete \
  --exclude .git \
  --exclude .venv/ \
  --exclude /models/ \
  --exclude __pycache__/ \
  --exclude .pytest_cache/ \
  --exclude .ruff_cache/ \
  --exclude .claude/ \
  --exclude .idea/ \
  --exclude .vscode/ \
  --exclude .DS_Store \
  --exclude '*.wav' \
  ./ "$host:$dir/"

if $install; then
  say "Installing on the Pi (first time: ~20 minutes, mostly building llama.cpp)"
  ssh -t "$host" "cd '$dir' && scripts/pi/install.sh"
else
  say "Updating Python deps and restarting Mirror"
  # shellcheck disable=SC2029  # $dir is meant to expand here, $HOME/$PATH on the Pi
  ssh "$host" "cd '$dir' && export PATH=\"\$HOME/.local/bin:\$PATH\" && uv sync --locked \
    && systemctl --user restart mirror-llm.service mirror-voice.service \
    && systemctl --user try-restart mirror-kiosk.service" || {
    echo
    echo "That failed. If this Pi has never been set up, run: scripts/pi/deploy.sh --install"
    exit 1
  }
fi

say "Deployed. Logs: scripts/pi/status.sh $host -f"
