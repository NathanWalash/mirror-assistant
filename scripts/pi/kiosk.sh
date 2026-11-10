#!/usr/bin/env bash
# Run by mirror-kiosk.service (started from the desktop's autostart): wait for the
# display server, then show it full screen in Chromium. The page hides the cursor itself.
set -euo pipefail
cd "$(dirname "$0")/../.."
export PATH="$HOME/.local/bin:$PATH"

read -r enabled port < <(uv run --no-sync python -c "
from mirror_voice.config import load_config
d = load_config().display
print(int(d.enabled), d.port)")
if [[ "$enabled" != 1 ]]; then
  echo "display.enabled is false in config.yaml, so there's nothing to show."
  sleep infinity
fi
url="http://127.0.0.1:$port/?kiosk"  # ?kiosk: never show the full-screen hint

browser=$(command -v chromium || command -v chromium-browser || true)
if [[ -z "$browser" ]]; then
  echo "Chromium isn't installed. Run scripts/pi/install.sh."
  exit 1
fi

waited=0
until curl -sf -o /dev/null "$url"; do
  if ((waited % 30 == 0)); then
    echo "Waiting for the display at $url (${waited}s so far)..."
  fi
  sleep 2
  waited=$((waited + 2))
done

# --incognito: no "restore pages?" bubble after a power cut.
# --password-store=basic: no keyring unlock prompt on a desktop with autologin.
exec "$browser" "$url" \
  --kiosk --incognito --noerrdialogs --disable-infobars --no-first-run \
  --no-default-browser-check --password-store=basic \
  --ozone-platform-hint=auto --check-for-update-interval=31536000
