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

**Names via key-term biasing.** Moonshine's streaming models can be nudged towards a list
of words (`set_keyterms`), no retraining. We pass the assistant's name plus `stt.keyterms`
from the private config (real names stay out of the repo). On synthetic speech it fixed
names misheard as ordinary words (one came out as "my code", another as "gay poem") and
left names it already got right alone. Side effect seen: biased lines sometimes lose their
punctuation, which the LLM doesn't mind. Keep the list short; Moonshine warns that long
lists cost accuracy on other words.

## Measure, don't guess: `mirror-talk --bench`
The Pi numbers in this file are mostly vendor figures and guesses. `--bench` runs fixed
questions through the real pipeline with no mic or speakers and logs every stage to
`models/bench.jsonl`, so model, STT and voice choices come from our own Pi.
`--bench tts` isolates the voice, Kokoro on the Pi being the biggest unknown.
Baseline on an M-series Mac (Hermes-3 3B Q4_K_M, small_streaming, Kokoro George): STT
~0.2s, LLM first token ~0.1s at ~65 tok/s, TTS real-time factor ~0.25-0.3, and ~0.9s
from end of speech to first audio.

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
**Buses: Bus Open Data Service (BODS), timetable + live positions, worked out ourselves.**
BODS is the DfT's free, legally-mandated feed for every English local bus, but it has no
"next departures at stop X" call: it publishes timetables (TransXChange, and GTFS per
region) and live bus positions (SIRI-VM, and GTFS-Realtime). So:

- *Timetable, once a day:* download the Yorkshire GTFS (~150 MB zip, ~1 GB unzipped; no key
  needed), stream it straight out of the zip without unpacking, keep only the trips that
  pick up at our stop(s) in the next three days, cache that (~700 KB for a busy
  city-centre stop, less for a suburban one) and delete the zip. Measured on the dev Mac
  for a stop with ~450 trips: 5 s download + 7 s filtering, 65 MB peak memory for the
  whole process, 150 MB of temporary disk. A Pi 5 is maybe 3–4x slower at the filtering
  (not yet measured), so well under a minute, once a day. It
  rebuilds after 05:00 (BODS regenerates the files ~04:30) and keeps using yesterday's
  cut if the download fails.
- *Live, every minute:* GTFS-RT vehicle positions in a box around the routes up to our
  stop. We chose GTFS-RT over SIRI-VM because BODS has already matched each bus to its
  GTFS `trip_id`, the same id as in the timetable (96 of 99 buses in central Leeds when we
  tried it), so there's no fuzzy matching on route names and start times. The protobuf is
  read by ~100 lines of our own (`hub/gtfs_rt.py`) instead of adding `protobuf`.
  Positions aren't predictions, so we place each bus on its route between two stops,
  compare with when it was timetabled to be there, and carry that delay on to our stop.
  Buses waiting at the start of their route aren't counted as early; we never believe
  a bus is more than 5 minutes early.
- Each departure is marked live or timetabled. No key, or the live call fails: timetable
  only, clearly labelled. Needs `BODS_API_KEY` (free) in `.env`.

Alternatives looked at: West Yorkshire Metro's "yournextbus" real-time service has no
documented public API; bustimes.org is a great site (and how to find your stop code)
but scraping it isn't ours to do; paid aggregators (TransportAPI) cost money for what
BODS gives free.

## Answering from the board: keyword routing, not tool calls
Mirror answers "do I need a coat?" or "what's my day like?" from the hub's live data
(`voice/src/mirror_voice/context.py`). We don't give the model tools. Instead, cheap
keyword routing looks at the question and adds a short `[Live info]` note under it: the
time, plus the weather, buses or today's and tomorrow's calendar if the question is about
them (all of it for "give me a rundown").
- *Why not tool calls:* a 3B model picks and fills in tools unreliably, and a tool call
  means a second model pass (call, result, then answer) that roughly doubles the wait
  on the Pi. Keyword lists are predictable, testable without a model, and easy to extend.
  They miss some phrasings; the note always has the time, and a miss just means Mirror
  says it doesn't know.
- *Why so short:* the Pi reads the prompt at only tens of tokens a second, so every
  line costs. A weather or bus question adds ~50-70 tokens, a calendar one ~80, a full
  briefing ~160; "tell me a joke" adds ~17 (the time). Calendar is today and tomorrow
  only, at most four events a day, titles cut at 40 characters.
- *Why at the end:* llama.cpp reuses its cache for the longest unchanged start of the
  prompt. The persona stays byte-identical at the top and the history is stored without
  the notes, so only the new question (and the tail of the last turn) is read afresh.
  Measured on a Mac with Llama 3.2 3B: 260 of the prompt's tokens came from cache on
  every turn, and only 26-170 were read new.
- *Never invented:* only data the hub actually fetched goes in. A failing widget is
  "(not updated since 14:05)" or "unavailable"; a named flatmate without a linked
  calendar gets "no calendar for Sam", not someone else's plans. Route numbers and
  destinations come from the bus data itself, so no place names are hard-coded here.
- *Still the weak spot:* the 3B model sometimes garbles the details it's given (wrong
  bus of two, "morning" in the afternoon). Better models or a fine-tune fix that; the
  data it's handed is right.

## Personality lives in a plain Markdown file
Re-read on every reply, so we can iterate without restarts. The shared template is
committed and personal copies are git-ignored (the repo is public).
