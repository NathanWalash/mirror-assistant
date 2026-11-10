#!/usr/bin/env bash
# One-time (and safe to re-run) setup of a Raspberry Pi 5 as the mirror. Run ON the Pi,
# as the normal desktop user (not root), from the repo folder:
#   scripts/pi/install.sh
# Or from your Mac: scripts/pi/deploy.sh --install
#
# It installs system packages, builds llama.cpp for the Pi's CPU, runs scripts/setup.sh
# (uv, Python deps, voice, private config + persona), installs the systemd user services,
# and sets the desktop up to boot straight into the mirror. See docs/pi.md.
set -euo pipefail
cd "$(dirname "$0")/../.."
repo=$(pwd)

# llama.cpp release tag to build. Bump it deliberately (and re-run) to upgrade.
LLAMA_CPP_REF=${LLAMA_CPP_REF:-b12244}
llama_src="$HOME/.local/src/llama.cpp"
bin_dir="$HOME/.local/bin"
units_dir="$HOME/.config/systemd/user"
labwc_autostart="$HOME/.config/labwc/autostart"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

if [[ "$(uname -s)" != Linux ]]; then
  echo "This is for the Raspberry Pi (Linux). On a Mac, use scripts/setup.sh."
  exit 1
fi
if [[ $EUID -eq 0 ]]; then
  echo "Run this as your normal user (it uses sudo where needed), not as root."
  exit 1
fi
if [[ "$(uname -m)" != aarch64 ]]; then
  echo "Warning: expected a 64-bit Raspberry Pi (aarch64), this is $(uname -m). Carrying on."
fi

say "System packages"
packages=(
  git build-essential cmake pkg-config libssl-dev # to build llama.cpp
  curl rsync                                       # health checks, deploys
  libportaudio2 pipewire-alsa                      # audio for sounddevice, via PipeWire
)
if ! command -v chromium >/dev/null && ! command -v chromium-browser >/dev/null; then
  # Newer Raspberry Pi OS calls the package chromium; older Bookworm chromium-browser.
  if apt-cache show chromium >/dev/null 2>&1; then
    packages+=(chromium)
  else
    packages+=(chromium-browser)
  fi
fi
sudo apt-get update
sudo apt-get install -y "${packages[@]}"

say "llama.cpp ($LLAMA_CPP_REF)"
stamp="$llama_src/.mirror-built"
if [[ -x "$bin_dir/llama-server" && -f "$stamp" && "$(cat "$stamp")" == "$LLAMA_CPP_REF" ]]; then
  echo "llama-server $LLAMA_CPP_REF already built."
else
  if [[ -d "$llama_src/.git" ]]; then
    git -C "$llama_src" fetch --depth 1 origin tag "$LLAMA_CPP_REF"
    git -C "$llama_src" checkout -q "$LLAMA_CPP_REF"
  else
    mkdir -p "$(dirname "$llama_src")"
    git clone --depth 1 --branch "$LLAMA_CPP_REF" https://github.com/ggml-org/llama.cpp "$llama_src"
  fi
  # Target the Pi 5's Cortex-A76 explicitly (Armv8.2-A with the dotprod and fp16
  # instructions llama.cpp uses for quantised models) rather than GGML_NATIVE: GCC 12's
  # CPU detection can enable fp16 maths without the fp16 flag and fail to compile.
  # No BLAS: per llama.cpp's docs it only speeds up big prompt batches, never token
  # generation, which is what Mirror waits on. Static, so it's one self-contained binary.
  echo "Building (about 10-15 minutes on a Pi 5)..."
  cmake -S "$llama_src" -B "$llama_src/build" \
    -DCMAKE_BUILD_TYPE=Release \
    -DGGML_NATIVE=OFF \
    -DGGML_CPU_ARM_ARCH=armv8.2-a+dotprod+fp16 \
    -DGGML_CCACHE=OFF \
    -DBUILD_SHARED_LIBS=OFF \
    -DLLAMA_BUILD_TESTS=OFF \
    -DLLAMA_BUILD_EXAMPLES=OFF
  cmake --build "$llama_src/build" --config Release --target llama-server -j "$(nproc)"
  mkdir -p "$bin_dir"
  install -m 755 "$llama_src/build/bin/llama-server" "$bin_dir/llama-server"
  echo "$LLAMA_CPP_REF" >"$stamp"
fi
export PATH="$bin_dir:$PATH"

say "Mirror itself (scripts/setup.sh)"
scripts/setup.sh
mkdir -p models

say "Services (systemd user units)"
mkdir -p "$units_dir"
for template in deploy/systemd/*.service; do
  sed "s|@REPO@|$repo|g" "$template" >"$units_dir/$(basename "$template")"
  echo "Installed $(basename "$template")"
done
systemctl --user daemon-reload
systemctl --user enable mirror-llm.service mirror-voice.service
# Start the user's services at boot, without waiting for anyone to log in.
sudo loginctl enable-linger "$USER"

say "Desktop: boot straight into the mirror"
if command -v raspi-config >/dev/null; then
  sudo raspi-config nonint do_boot_behaviour B4 # desktop, logged in automatically
  sudo raspi-config nonint do_blanking 1        # 1 = never blank the screen
else
  echo "raspi-config not found (not Raspberry Pi OS?): set up desktop autologin and"
  echo "turn screen blanking off yourself."
fi
mkdir -p "$(dirname "$labwc_autostart")"
touch "$labwc_autostart"
if ! grep -q mirror-kiosk "$labwc_autostart"; then
  # Hand the Wayland session's variables to the user manager, then start the kiosk.
  cat >>"$labwc_autostart" <<'EOF'
# mirror-assistant: show the mirror full screen (scripts/pi/install.sh added this)
sh -c 'systemctl --user import-environment WAYLAND_DISPLAY DISPLAY XDG_CURRENT_DESKTOP XDG_SESSION_TYPE && systemctl --user start mirror-kiosk.service' &
EOF
  echo "Added the kiosk to $labwc_autostart"
else
  echo "Kiosk already in $labwc_autostart"
fi
session=$(grep -hs '^autologin-session=' /etc/lightdm/lightdm.conf || true)
if [[ -n "$session" && "$session" != *labwc* ]]; then
  echo "Warning: the desktop isn't labwc ($session), so the kiosk won't autostart."
  echo "  Switch with: sudo raspi-config -> Advanced Options -> Wayland -> labwc"
fi

say "Starting Mirror"
systemctl --user restart mirror-llm.service mirror-voice.service
echo "First start downloads the model (~2 GB). Watch it with: scripts/pi/status.sh -f"
echo "Reboot to check everything comes up by itself: sudo reboot"
