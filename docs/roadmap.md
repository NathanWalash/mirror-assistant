# Roadmap

Rough order. AI first, then the mirror around it.

## Voice & personality
- [x] Voice loop on Mac: Moonshine → llama.cpp → TTS, streamed sentence by sentence
- [x] Editable persona file, live reload; personal copies git-ignored
- [x] Swappable voices (Kokoro / Piper / ZipVoice) via one config line; audio streamed
      in chunks so Kokoro's first audio arrives in ~0.25s
- [x] Personal `config.yaml` (git-ignored) over shared `config.example.yaml`
- [ ] Agree the character with both flatmates (working draft: "Michael", a funny,
      wildly inappropriate, no-filter but genuinely helpful assistant; voice Kokoro
      `am_adam`)
- [ ] Model bake-off with the persona: Hermes-3 3B vs Qwen3 4B abliterated vs Llama 3.2 3B
      abliterated. Hermes-3 3B with prompt alone keeps the name and has no filter, but
      rambles past the length rule, invents details, and isn't very funny.
- [x] Teach speech-to-text the assistant's name (`assistant.name`, plus `stt.keyterms`
      for flatmates' names in your private config)
- [ ] Personality test set: ~30 fixed questions + script that saves replies side by side,
      to judge prompt/model/fine-tune changes
- [ ] Personality dataset + LoRA fine-tune (MLX on the M2 Max, or Unsloth on a rented GPU)
- [ ] Heretic-abliterate the newest small Qwen ourselves
- [ ] Wake word ("hey Michael") with openWakeWord
- [ ] Interrupting it while it talks (barge-in), see echo-cancelling mic below
- [ ] Teach speech-to-text the assistant's name (Moonshine keyterms)

## Raspberry Pi
- [ ] Pi setup/deploy script: OS packages, llama.cpp build, uv + deps, systemd services,
      Chromium kiosk showing the display
- [x] Benchmark mode to measure it: `mirror-talk --bench` (and `--bench tts`)
- [ ] Measure real latency on the Pi and pick model size / STT model accordingly
- [ ] **Kokoro on the Pi is the biggest risk.** Only published numbers are Pi 4: ~2.8-3.2s
      to generate 1s of speech on 4 threads (sherpa-onnx). Pi 5 is maybe 2-3x faster,
      so roughly real time, while also sharing CPU with the LLM. If it stutters: synthesise
      the full reply before speaking, or fall back to a `piper_*` voice.
- [ ] Echo-cancelling mic (needed for interrupting with speakers on)

## The mirror
- [x] Hub: widget framework (background refreshers, stale handling, `mirror-hub` to run
      the screen without the voice loop), see docs/widgets.md
- [x] Hub: weather (Open-Meteo)
- [x] Hub: both calendars (private ICS links; recurring, all-day, time zones)
- [x] Hub: local bus stop (Bus Open Data Service: daily GTFS timetable + live GTFS-RT positions)
- [x] Display v1: orb that reacts to idle/listening/thinking/speaking + subtitles
- [x] Display: widget slots around the orb, clock/date, weather
- [x] Display: calendar widget (bottom-left)
- [x] Display: bus widget (bottom-right)
- [ ] Buses: watch the live times against the real stop for a week; tune if often off
- [ ] Chromium kiosk on the Pi
- [ ] Mirror can answer from real data ("what's my day like?"); `Hub.snapshot()` has it
      (the calendar data carries ready-made `summary` lines for this)
