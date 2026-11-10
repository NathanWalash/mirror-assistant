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

## Text-to-speech: Kokoro via Moonshine (`kokoro_bm_george` by default)
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

## Widgets: a hub of small fetchers, pushed down the same event stream
Each widget is one Python module with a `fetch(settings) -> dict` (stdlib `urllib`, no
extra dependencies) and one JS file that draws it into a named slot around the orb.
The hub runs a thread per widget on its own timer and publishes `{"widget": ...}` events
through the display's existing SSE stream; the server remembers each widget's latest event
so a freshly opened page fills in at once. A failed fetch never touches the voice loop: the
last good data stays up, dimmed, with "not updated since ...". Still no framework or build
step, so the Pi's Chromium can load it offline. `mirror-hub` runs the screen without the
model, for working on widgets.

**Weather: Open-Meteo.** Free, no API key or account, good UK coverage, and it gives an
hourly chance of rain, which matters more in West Yorkshire than the temperature does.

**Calendars: private ICS links, parsed with `icalendar` + `recurring-ical-events`.** Every
calendar app (Google, Outlook, iCloud) can publish a read-only ICS link, so there's no
OAuth app to register and no tokens to refresh. The first exception to "stdlib only":
recurring events with exceptions, moved occurrences, Outlook's Windows time-zone names
and the clocks changing are exactly what goes wrong in a hand-written parser, and these
two libraries are well maintained and pure Python (fine on the Pi). The links are
secrets, so they live in `config.yaml` only and are redacted from every error and log line.

## Personality lives in a plain Markdown file
Re-read on every reply, so we can iterate without restarts. The shared template is
committed and personal copies are git-ignored (the repo is public).
