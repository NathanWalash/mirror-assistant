# Decisions so far

What we picked, and why. Revisit any of these when they stop being true.

## Run everything locally, on the Pi
Privacy, no API bills, and it's a fun challenge. The model is called through an
OpenAI-compatible API, so pointing at a bigger machine later is a config change, not a rewrite.

## Brain: small abliterated model via llama.cpp
- **Size 3–4B, 4-bit quantised (Q4_K_M).** Pi 5 generation is limited by memory bandwidth:
  roughly 4–6 tokens/sec at 3B. Fine for short spoken replies streamed sentence by
  sentence; 7–8B is too slow to chat with.
- **Current model: Hermes-3 Llama 3.2 3B, abliterated.** Hermes is tuned for playing a
  character; abliteration removes refusals. A quick, ready-made pick to get going.
- **llama.cpp over Ollama:** reported 10–20% faster on the Pi, and the same files run on Mac.
- **Next:** abliterate the newest small Qwen ourselves with
  [Heretic](https://github.com/p-e-w/heretic) (no training needed, ~30–40 min on a rented
  GPU; can also reduce "assistant slop"), then LoRA fine-tune the personality in.

## Speech-to-text: Moonshine (`small_streaming`)
Built for edge devices and transcribes while you talk. Its own Pi 5 benchmarks: Tiny
Streaming ~0.24s and Small Streaming ~0.53s, vs ~5.9s for Whisper Tiny (vendor numbers,
to be verified on our Pi). Voice activity detection is built in.

## Text-to-speech: Kokoro via Moonshine (`kokoro_bm_george`)
Piper's northern voice sounded too robotic. Moonshine (already our speech-to-text) also
runs Kokoro, Piper and ZipVoice voices behind one API, so the voice is a single config
line (`tts.voice`) and `mirror-talk --voices` lists the options.

Kokoro sounds far more natural but is ~6x slower than Piper (about 6x real time on an
M2 Max; roughly real time on a Pi is our guess). Streaming fixes the wait: the first
audio chunk is ready in ~0.25s instead of ~1.2s for a whole sentence, and synthesis and
playback run in parallel. If the Pi can't keep up, fall back to a `piper_*` voice.
ZipVoice can clone a voice from a short clip but is probably too slow for the Pi.

## Display: a plain web page fed by Server-Sent Events
The voice loop serves `display/index.html` and pushes state/subtitle/loudness events over
SSE using only Python's standard library. No framework or build step yet: one HTML file
with a canvas orb. On the Pi, Chromium in kiosk mode shows the same page. We'll reach
for a framework only once widgets make the page complex.

## Personality lives in a plain Markdown file
Re-read on every reply, so we can iterate without restarts. The shared template is
committed and personal copies are git-ignored (the repo is public).
