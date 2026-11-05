# Roadmap

Rough order. AI first, then the mirror around it.

## Voice & personality (now)
- [x] Voice loop on Mac: Moonshine → llama.cpp → Piper, streamed
- [x] Editable persona file, live reload
- [ ] Define the character properly (both flatmates' input)
- [ ] Interrupting Mirror while it talks (barge-in), see hardware note below
- [ ] Wake word ("hey Mirror") with openWakeWord
- [ ] Model bake-off: Hermes-3 3B vs Qwen3 4B abliterated vs Llama 3.2 3B abliterated
- [ ] Heretic-abliterate the newest small Qwen ourselves
- [ ] Personality dataset + LoRA fine-tune (MLX on the Mac, or Unsloth on a rented GPU)

## Raspberry Pi
- [ ] Pi setup script: llama.cpp build, Python deps, autostart services
- [ ] Measure real latency on the Pi, and choose model size and STT model accordingly
- [ ] Echo-cancelling mic (needed for interrupting with speakers on)

## The mirror
- [ ] Hub: weather (Open-Meteo), both calendars (private ICS links), local bus stop
      (Bus Open Data Service, West Yorkshire)
- [x] Display v1: orb that reacts to idle/listening/thinking/speaking + subtitles
- [ ] Display: weather/calendar/bus widgets around the orb; Chromium kiosk on the Pi
- [ ] Mirror can answer from real data ("what's my day like?")
