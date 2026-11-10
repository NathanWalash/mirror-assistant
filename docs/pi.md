# Running Mirror on the Raspberry Pi

The Pi boots straight into the mirror: the model server and voice loop start as
services, and the desktop opens the display full screen in Chromium. You edit code on
your Mac and push it to the Pi with one command.

**What you need:** a Raspberry Pi 5 (8 GB or 16 GB), its official 27 W power supply, a
microSD card (32 GB+, A2 class), a USB microphone and speakers (or a USB speakerphone,
which does both), an HDMI cable to the TV, and a keyboard for the very first boot only
(optional).

## 1. Flash the SD card

1. Install [Raspberry Pi Imager](https://www.raspberrypi.com/software/) on your Mac.
2. Choose **Raspberry Pi 5**, then **Raspberry Pi OS (64-bit)**: the normal desktop
   version, not Lite (the kiosk needs the desktop). The scripts were written for the
   Bookworm release; if Imager now offers a newer one, it should work, but if it gives
   you trouble pick the Bookworm one under *Raspberry Pi OS (other)*.
3. When it offers to customise the settings, set:
   - **Hostname:** `mirror` (so the Pi is `mirror.local` on your network)
   - **Username and password:** whatever you like. The examples below use `you`.
   - **Wi-Fi:** your network name and password, and country **GB**
   - **Locale:** Europe/London, keyboard `gb`
   - **Services:** enable **SSH**, ideally with *public-key authentication only*, pasting
     your Mac's public key (`cat ~/.ssh/id_ed25519.pub`; make one with `ssh-keygen -t
     ed25519` if you don't have it)
4. Write the card, put it in the Pi, plug in the TV, mic, speakers and power.
5. Give it a couple of minutes, then from your Mac: `ssh you@mirror.local`. If that
   works, you're ready.

## 2. First-time install (from your Mac)

From your checkout on the Mac, after `scripts/setup.sh` has created your private
`config.yaml` and persona:

```bash
export MIRROR_HOST=you@mirror.local     # put this in ~/.zshrc to save typing
scripts/pi/deploy.sh --install
```

This copies the repo to `~/mirror-assistant` on the Pi and runs
[`scripts/pi/install.sh`](../scripts/pi/install.sh) there, which:

1. installs system packages with apt (build tools, PortAudio, PipeWire's ALSA plugin,
   Chromium);
2. builds llama.cpp's `llama-server` for the Pi's CPU into `~/.local/bin` (10-15 minutes);
3. runs `scripts/setup.sh` (uv, Python 3.12, Python packages, the voice, private config);
4. installs and enables the services, and lets them start at boot without a login;
5. sets the desktop to log in automatically, turns screen blanking off and adds the
   kiosk to the desktop's autostart;
6. starts Mirror. The first start downloads the model (~2 GB), so give it a few minutes.

Then `ssh you@mirror.local sudo reboot` and check it all comes back on its own.

It's safe to re-run any time (it skips what's already done). You can also run
`scripts/pi/install.sh` on the Pi directly.

## 3. Deploying changes

```bash
scripts/pi/deploy.sh          # uses MIRROR_HOST, or: scripts/pi/deploy.sh you@mirror.local
```

It copies your working tree as it is (uncommitted changes too, so you can try things on
the Pi first), runs `uv sync`, and restarts Mirror (model server, voice and kiosk).
Persona edits need no restart on the Pi either, but deploying restarts anyway.

**What gets copied:** everything except `.git`, `.venv`, `models/`, caches and `*.wav`.
That includes the git-ignored private files: `config.yaml`,
`personality/personas/*.md` and `.env`. Files deleted on the Mac are deleted on the Pi
too; the excluded folders on the Pi (its `.venv` and `models/`) are never touched.

So **the Pi uses your Mac's `config.yaml`**. Whoever deploys, deploys their config: keep
the settings you both want on the Pi in it.

## 4. Is it working? Logs

```bash
scripts/pi/status.sh                # service status + the last 60 log lines
scripts/pi/status.sh -f             # follow the logs live (Ctrl+C to stop)
```

(Both use `MIRROR_HOST`, or take the host as an argument; on the Pi itself, run them
without one.) The services:

| Service | What | Starts |
|---|---|---|
| `mirror-llm` | llama.cpp model server (port/model from config) | at boot |
| `mirror-voice` | voice loop + display server, waits for the model | at boot |
| `mirror-kiosk` | Chromium full screen on the display | when the desktop starts |

They are systemd **user** services, so on the Pi, without sudo:

```bash
systemctl --user status mirror-voice
systemctl --user restart mirror-voice
systemctl --user stop mirror-llm mirror-voice mirror-kiosk    # e.g. to run talk.sh by hand
journalctl --user-unit mirror-voice -f
```

All three restart themselves if they crash.

## 5. Picking the microphone and speakers

Mirror records from and plays to the **default** audio devices. On Raspberry Pi OS the
desktop's sound server (PipeWire) decides what "default" means, so choose the devices
there. Either right-click the speaker icon on the desktop's top bar, or over SSH:

```bash
wpctl status                 # lists Sinks (speakers) and Sources (mics), with ID numbers
wpctl set-default 57         # the ID of your USB speaker
wpctl set-default 58         # the ID of your USB mic
wpctl set-volume @DEFAULT_AUDIO_SINK@ 80%
```

The choice is remembered across reboots. Then restart the voice:
`systemctl --user restart mirror-voice`.

To check the devices without Mirror: `arecord -l` and `aplay -l` list the ALSA cards,
`arecord -d 5 test.wav && aplay test.wav` records five seconds and plays it back, and
from the repo folder `uv run mirror-talk --say "Can you hear me?"` speaks through the
default output. (Stop `mirror-voice` first if a device is busy.)

## Why it's set up this way

- **systemd user services, not system ones.** Audio (PipeWire) and the screen (Wayland)
  belong to the logged-in user's session; a system service can't easily reach either.
  User services also need no sudo to restart, so deploys don't either. "Lingering" is
  turned on so the model and voice still start at boot before anyone logs in.
- **The kiosk is started by the desktop.** Chromium needs the Wayland session, which only
  exists once the desktop (labwc, the default on current Raspberry Pi OS) has started.
  labwc's autostart hands its environment to the user's systemd and starts
  `mirror-kiosk`, so Chromium still gets automatic restarts and logs in the journal.
  The cursor is hidden by the page itself (`cursor: none`), which works on any compositor.
- **llama.cpp is built on the Pi.** The official Linux arm64 release binaries are built
  on Ubuntu 24.04 (glibc 2.39), and Raspberry Pi OS Bookworm has glibc 2.36, so they
  won't run. The build targets the Pi 5's CPU exactly (`armv8.2-a+dotprod+fp16`, i.e.
  Cortex-A76 with the dotprod and fp16 instructions llama.cpp uses for quantised
  models). That's set explicitly rather than with `GGML_NATIVE=ON`, because with
  Bookworm's GCC 12 the CPU auto-detection produced flags that don't compile (seen in
  a Bookworm arm64 container). No OpenBLAS: llama.cpp's own docs say BLAS only helps prompt processing in
  big batches and doesn't affect generation speed, which is what you wait for. The
  llama.cpp version is pinned in `install.sh` (`LLAMA_CPP_REF`); bump it and re-run to
  upgrade.
- **Deploy with rsync, not git pull.** The private files have to reach the Pi and must
  never be committed, and it lets you try uncommitted changes on the real hardware.

Sources: llama.cpp [build docs](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md)
(BLAS, `GGML_CPU_ARM_ARCH`) and
[release workflow](https://github.com/ggml-org/llama.cpp/blob/master/.github/workflows/release.yml)
(arm64 built on `ubuntu-24.04-arm`);
[Raspberry Pi kiosk tutorial](https://www.raspberrypi.com/tutorials/how-to-use-a-raspberry-pi-in-kiosk-mode/)
(labwc autostart);
[raspi-config](https://github.com/RPi-Distro/raspi-config) (`do_boot_behaviour`,
`do_blanking`). Whether Moonshine and Kokoro keep up on the Pi is still to be measured.

## Troubleshooting

**`ssh: Could not resolve hostname mirror.local`.** Give the Pi another minute after
boot. Otherwise find its IP address on your router's admin page and use `you@192.168.x.y`.
Some mesh/guest Wi-Fi networks block `.local` names.

**Nothing on the TV, or the desktop instead of the mirror.** Check
`scripts/pi/status.sh`: is `mirror-kiosk` running? It's only started by the desktop, so
it shows "inactive" until the desktop is up. The desktop must be labwc: run
`sudo raspi-config`, *Advanced Options → Wayland*, choose labwc, and reboot. Check the
kiosk line is in `~/.config/labwc/autostart`.

**The screen goes black after 10 minutes.** Run `sudo raspi-config nonint do_blanking 1`
and reboot. (install.sh does this; something may have turned it back on.) The TV itself
may also have an auto power-off setting.

**"Waiting for the model server" for ages.** The first start downloads ~2 GB. The
download progress is in the `mirror-llm` logs. If it keeps restarting, look there
for the error (no network, wrong `llm.model` in `config.yaml`, out of memory).

**Mirror doesn't hear anything, or no sound.** Wrong default device: see section 5.
Check the mic's input volume in `wpctl status` / the desktop's volume control.

**Mirror hears itself.** It mutes the mic while speaking, but a loud speaker right next
to the mic can still leak. Move them apart; echo cancelling is on the roadmap.

**`uv sync --locked` fails on deploy.** `uv.lock` is out of date: run `uv sync` on the
Mac and commit the new lock file, then deploy again.

**Start over on the Pi.** `rm -rf ~/mirror-assistant/.venv` and deploy with
`--install`. To rebuild llama.cpp, delete `~/.local/src/llama.cpp/.mirror-built` first.
