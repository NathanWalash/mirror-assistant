# mirror-assistant

An old TV + a Raspberry Pi 5, turned into a smart mirror for our flat: weather, calendars,
buses, and **Mirror**, a sarcastic Yorkshire assistant you can talk to out loud.
Everything runs locally, with no cloud.

**Status:** voice loop + a first display (a glowing orb with subtitles) work on a Mac.
Weather, calendars and Pi deployment come later.

## Quickstart (macOS)

```bash
scripts/setup.sh   # once: installs llama.cpp + deps, downloads the voice, creates your persona
scripts/talk.sh    # talk to Mirror (first run downloads the ~2 GB model)
```

Then just talk. Mirror answers when you pause, and Ctrl+C quits. macOS will ask for
microphone access for your terminal the first time.

A browser tab opens with **Mirror's face**: a glowing orb that breathes when idle, lights
up when it hears you, swirls while thinking, and pulses as it talks, with subtitles.
Click it or press F for full screen. (It's at http://127.0.0.1:8765, and you can turn the
auto-open off in `config.yaml`.)

No mic, or just checking it works? `scripts/talk.sh --selftest` asks Mirror a question
with a synthetic voice and saves the reply to `models/selftest_reply.wav`.

## Changing Mirror

| What | Where | Applies |
|---|---|---|
| Personality | `personality/personas/mirror.md` (your private copy) | next reply, no restart |
| Shared personality template | `personality/personas/mirror.example.md` | after re-copying |
| **Voice** (`tts.voice`), talking speed | `config.yaml` | restart `talk.sh` |
| Model, creativity, reply length, display | `config.yaml` | restart `talk.sh` |
| Your private setting overrides | `config.local.yaml` (create it) | restart `talk.sh` |

**Trying voices:**
```bash
uv run mirror-talk --voices                                  # list them all
uv run mirror-talk --say "Ey up, you look rough" --voice kokoro_bm_lewis   # hear one
```
Then set the one you like as `tts.voice` in `config.yaml` (or `config.local.yaml` to keep it to yourself).

`mirror.md` and `config.local.yaml` are git-ignored, so personal stuff is safe there.
**This repo is public**, so keep names and private details out of everything else.

## How it works

```
mic → Moonshine (speech-to-text) → llama.cpp (Hermes-3 Llama 3.2 3B, abliterated)
    → Kokoro (text-to-speech, "George", British male) → speakers
                                  ↘ display/ (orb + subtitles, live via Server-Sent Events)
```

The reply is streamed and spoken sentence by sentence, so Mirror starts talking before
it has finished thinking. More detail in [docs/decisions.md](docs/decisions.md).

## Repo layout

```
voice/         the talk loop (Python package: mirror_voice)
display/       the mirror screen (plain HTML/JS, served by the voice loop)
personality/   personas now; fine-tuning datasets and scripts later
scripts/       setup.sh, talk.sh
models/        downloaded models and voices (git-ignored)
docs/          decisions, hardware notes, roadmap
hub/ deploy/   coming later
```

Working on it together: see [CONTRIBUTING.md](CONTRIBUTING.md).
