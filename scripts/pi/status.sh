#!/usr/bin/env bash
# Is Mirror running, and what has it been saying? Shows the services and recent logs.
#   scripts/pi/status.sh you@mirror.local      # from your Mac (or set MIRROR_HOST)
#   scripts/pi/status.sh                       # on the Pi itself
#   scripts/pi/status.sh you@mirror.local -f   # keep following the logs (Ctrl+C to stop)
set -euo pipefail

follow=false
host=${MIRROR_HOST:-}
for arg in "$@"; do
  case "$arg" in
    -f | --follow) follow=true ;;
    *) host=$arg ;;
  esac
done

units="mirror-llm.service mirror-voice.service mirror-kiosk.service"
# --user-unit reads the system journal, which works even when it isn't kept on disk
# (unlike `journalctl --user`). The default Pi user is in the adm group, so may read it.
logs="journalctl --no-pager -o short --user-unit mirror-llm.service \
  --user-unit mirror-voice.service --user-unit mirror-kiosk.service"
if $follow; then
  cmd="$logs -n 20 -f"
else
  cmd="systemctl --user --no-pager status $units; echo; $logs -n 60"
fi

if [[ -n "$host" ]]; then
  ssh -t "$host" "$cmd"
elif [[ "$(uname -s)" == Linux ]]; then
  bash -c "$cmd"
else
  echo "Which Pi? Pass it (scripts/pi/status.sh you@mirror.local) or set MIRROR_HOST."
  exit 1
fi
