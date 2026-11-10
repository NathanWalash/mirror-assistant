# Decisions so far

What we picked, and why. Revisit any of these when they stop being true.

## Run everything locally, on the Pi
Privacy, no API bills, and it's a fun challenge. The model is called through an
OpenAI-compatible API, so pointing at a bigger machine later is a config change, not a rewrite.

## Brain: small abliterated model via llama.cpp
- **Size 3–4B, 4-bit quantised (Q4_K_M).** Pi 5 generation is limited by memory bandwidth:
  roughly 4–6 tokens/sec at 3B. Fine for short spoken replies streamed sentence by
  sentence; 7–8B is too slow to chat with.
- **Current model: Llama 3.2 3B Instruct, abliterated** (huihui-ai's, quantised by
  mradermacher). Won the bake-off below; abliteration removes refusals. We started on
  Hermes-3 Llama 3.2 3B abliterated, which played the character but rambled.
- **llama.cpp over Ollama:** reported 10–20% faster on the Pi, and the same files run on Mac.
- **Next:** abliterate the newest small Qwen ourselves with
  [Heretic](https://github.com/p-e-w/heretic) (no training needed, ~30–40 min on a rented
  GPU; can also reduce "assistant slop"), then LoRA fine-tune the personality in.

## Model bake-off (personality eval)
`uv run mirror-eval` asks 33 fixed questions (`personality/eval/questions.yaml`: everyday
help, banter, taboo hypotheticals, pick-a-side opinions, live info it can't know,
identity, follow-ups), each in a fresh conversation with the real persona, and flags
mechanical failures. `scripts/eval.sh <repo:quant> <label>` runs one model on port 8090;
`mirror-eval compare` puts runs side by side in HTML for judging the jokes by eye.

All Q4_K_M on an M2 Max, temperature 0.8, 150-token cap, private persona with the
length/"can't know"/examples tweaks (the same ideas now in `mirror.example.md`):

| Model (abliterated) | Size | Tok/s (M2 Max) | Avg words | >3 sentences | Hit cap | Lists/* | Invents live info | Refusals | Clean /33 |
|---|---|---|---|---|---|---|---|---|---|
| **Llama 3.2 3B Instruct** (huihui-ai) | 2.0 GB | 116 | 34 | 2 | 0 | 0 | 1/5 | 0 | **29** |
| Gemma 3 4B it (mlabonne) | 2.3 GB | 92 | 22 | 6 | 0 | 0 | 0/5 | 0 | 27 |
| Qwen3.5 4B (huihui-ai) | 2.5 GB | 80 | 31 | 2 | 0 | 0 | 1/5 | 0 | 28 |
| Qwen3 4B Instruct 2507 (huihui-ai) | 2.3 GB | 92 | 36 | 9 | 0 | 2 | 0/5 | 0 | 23 |
| Hermes-3 Llama 3.2 3B (previous) | 1.9 GB | 109 | 54 | 23 | 1 | 3 | 1/5 | 0 | 8 |

With the persona as it was before the tweaks, every model invented weather, bus times
and football scores, and Hermes / Qwen3 2507 hit the token cap on 12 / 18 of 33 replies
(markdown lists, `*emphasis*`). Prompt tweaks mattered more than model choice: see the
"Persona" section below.

- **Llama 3.2 3B wins**: tidiest replies, the fastest, swears and picks sides, and
  mostly gets the actual help right (eggs 6–7 minutes; 15% of 42 was 6.30 with the
  tweaked persona, "fifty-six quid" without). The same size and
  architecture as Hermes, so no Pi speed cost. Jokes are hit and miss.
- **Gemma 3 4B is the funniest** by ear (crude and punchy: "I'm a mirror, not the
  fucking BBC"), but 4B is ~30% slower on the Pi, it gets sums wrong, leans on tics
  ("Right then…", badgers), and sometimes dodges the question with a joke. It uses
  sliding-window attention, so **run it with `--swa-full`** or llama.cpp re-reads the
  whole system prompt every reply (first token 0.41s → 0.06s on the Mac; on the Pi that's
  roughly 10s+ vs instant). Worth a listen-test against Llama.
- **Qwen3 4B Instruct 2507** is the non-thinking release, so no `/no_think` needed.
  (The original hybrid Qwen3 and Qwen3.5 need thinking switched off: `--reasoning off`
  on llama-server, or `mirror-eval run --no-think`, which sends
  `chat_template_kwargs: {"enable_thinking": false}`.) Whimsical rather than crude.
- **Qwen3.5 4B**: obeys length well but bland and repetitive, and copies the example
  format ("Mirror: …").
- **Hermes-3 3B**: ignores the length rule whatever the prompt, recites its instructions
  as a list when asked "who are you", and makes things up ("created by a company called
  Megha").
- **Pi speed** (guess, ~10–20x slower than the M2 Max): a 3B at ~5–8 tokens/sec turns
  Llama's ~40-token replies into 5–8s of generation, with the first sentence spoken after
  ~2s. Hermes' ~110-token rambles would take 15–20s. Short replies are the biggest
  latency win on the Pi. Keep the system prompt prefix cached (it's ~500 tokens).
- One sample per question at a fixed seed, so treat single replies as anecdotes; a
  second seed for Llama and Gemma gave similar numbers (28 and 25 clean).

## Persona: rules first, then example exchanges
Small models follow examples far better than rules. What helped every model:
the length rule at the very top ("one to three short sentences, under 40 words"), an
explicit "you have no internet, clock or window" list of things it can't know, and a few
`User:`/`Mirror:` example exchanges (kept off the eval questions so the eval stays fair).
Hermes was the exception: it got wordier.

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

## On the Pi: systemd user services, deployed from the Mac with rsync
Model server and voice loop are systemd *user* services (audio and the screen belong to
the user's session; no sudo needed to restart), started at boot via lingering. The
desktop's autostart starts Chromium in kiosk mode. llama.cpp is built on the Pi (tuned
for its Cortex-A76, no BLAS) because the official arm64 binaries need a newer glibc
than Raspberry Pi OS Bookworm. `deploy.sh` rsyncs the working tree, private files included.
Details and sources in [pi.md](pi.md).

## Personality lives in a plain Markdown file
Re-read on every reply, so we can iterate without restarts. The shared template is
committed and personal copies are git-ignored (the repo is public).
