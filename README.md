# mirror-assistant

An old TV + a Raspberry Pi 5, turned into a smart mirror for our flat: weather, calendars,
buses, and **Mirror**, a sarcastic Yorkshire assistant you can talk to out loud.
Everything runs locally, with no cloud.

**Status:** the voice loop works on a Mac. The display, data and Pi deployment come later.

## Quickstart (macOS)

```bash
scripts/setup.sh   # once: installs llama.cpp + deps, downloads the voice, creates your persona
scripts/talk.sh    # talk to Mirror (first run downloads the ~2 GB model)
```

Then just talk. Mirror answers when you pause, and Ctrl+C quits. macOS will ask for
microphone access for your terminal the first time.

No mic, or just checking it works? `scripts/talk.sh --selftest` asks Mirror a question
with a synthetic voice and saves the reply to `models/selftest_reply.wav`.

## Changing Mirror

| What | Where | Applies |
|---|---|---|
| Personality | `personality/personas/mirror.md` (your private copy) | next reply, no restart |
| Shared personality template | `personality/personas/mirror.example.md` | after re-copying |
| Model, voice, speed, creativity, reply length | `config.yaml` | restart `talk.sh` |
| Your private setting overrides | `config.local.yaml` (create it) | restart `talk.sh` |

`mirror.md` and `config.local.yaml` are git-ignored, so personal stuff is safe there.
**This repo is public**, so keep names and private details out of everything else.

## How it works

```
mic → Moonshine (speech-to-text) → llama.cpp (Hermes-3 Llama 3.2 3B, abliterated)
    → Piper (text-to-speech, northern English voice) → speakers
```

The reply is streamed and spoken sentence by sentence, so Mirror starts talking before
it has finished thinking. More detail in [docs/decisions.md](docs/decisions.md).

## Repo layout

```
voice/         the talk loop (Python package: mirror_voice)
personality/   personas now; fine-tuning datasets and scripts later
scripts/       setup.sh, talk.sh
models/        downloaded models and voices (git-ignored)
docs/          decisions, hardware notes, roadmap
hub/ display/ deploy/   coming later
```

Working on it together: see [CONTRIBUTING.md](CONTRIBUTING.md).
