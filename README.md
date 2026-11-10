# mirror-assistant

An old TV + a Raspberry Pi 5, turned into a smart mirror for our flat: weather, calendars,
buses, and **Mirror**, a sarcastic Yorkshire assistant you can talk to out loud.
Everything runs locally, with no cloud.

**Status:** voice loop + the display (a glowing orb with subtitles, a clock, the weather,
both our calendars and the next buses around it) work on a Mac. The Pi setup (boots
straight into the mirror) is written but not yet tried on real hardware.

## Quickstart (macOS)

```bash
scripts/setup.sh   # once: installs llama.cpp + deps, downloads the voice, creates your persona
scripts/talk.sh    # talk to Mirror (first run downloads the ~2 GB model)
```

Then just talk. Mirror answers when you pause, and Ctrl+C quits. macOS will ask for
microphone access for your terminal the first time.

A browser tab opens with **Mirror's face**: a glowing orb that breathes when idle, lights
up when it hears you, swirls while thinking, and pulses as it talks, with subtitles.
Around it sit the time and date and the weather (from Open-Meteo, no API key: set your
`latitude`/`longitude` under `widgets.weather` in `config.yaml`).
Bottom left shows the next few days from everyone's calendars, see below.
Bottom right are the **next buses** from your stop (see [Buses](#buses) below).
Click it or press F for full screen. (It's at http://127.0.0.1:8765, and you can turn the
auto-open off in your `config.yaml`. A kiosk browser should open http://127.0.0.1:8765/?kiosk,
which never shows the "full screen" hint.) From midnight to 06:30 the whole screen dims
so it doesn't light up the room: change the hours or brightness under `display.night` in
your `config.yaml` (add `?now=03:00` to the address to preview it).

**Just the screen, no talking:** `uv run mirror-hub` serves the display and widgets without
the model or mic, and `uv run mirror-hub --once weather` (or `bus`) prints what that
widget would show.

## On the Raspberry Pi

Flash Raspberry Pi OS with hostname `mirror` and SSH on, then from your Mac:

```bash
MIRROR_HOST=you@mirror.local scripts/pi/deploy.sh --install   # first time
MIRROR_HOST=you@mirror.local scripts/pi/deploy.sh             # after each change
MIRROR_HOST=you@mirror.local scripts/pi/status.sh -f          # logs
```

The Pi then boots straight into the mirror. Full guide, including picking the mic and
speakers: [docs/pi.md](docs/pi.md).

## Checking it works

No mic, or just checking it works? `scripts/talk.sh --selftest` asks Mirror a question
with a synthetic voice and saves the reply to `models/selftest_reply.wav`.

**How fast is it?** `scripts/talk.sh --bench` asks five fixed questions the same way (no
mic or speakers) and prints a table of each stage: speech-to-text time, the model's time to
first token and tokens/sec, the voice's real-time factor, and how long until Mirror starts
talking. `uv run mirror-talk --bench tts` times just the voice (no model server needed;
add `--voice piper_en_GB-alan-medium` to compare voices), and `--bench stt` just
speech-to-text. Each run is also appended as one JSON line to `models/bench.jsonl`.

## Changing Mirror

| What | Where | Applies |
|---|---|---|
| Personality | `personality/personas/mirror.md` (your private copy) | next reply, no restart |
| **Name** (`assistant.name`), flatmates (`assistant.people`), names to listen out for (`stt.keyterms`) | `config.yaml` (your private copy) | restart `talk.sh` |
| Shared personality template | `personality/personas/mirror.example.md` | after re-copying |
| **Voice** (`tts.voice`), talking speed | `config.yaml` (your private copy) | restart `talk.sh` |
| Model, creativity, reply length, display | `config.yaml` (your private copy) | restart `talk.sh` |
| Widgets: location, refresh rate, on/off (`widgets:`) | `config.yaml` (your private copy) | restart |
| Shared defaults for everyone | `config.example.yaml` | restart `talk.sh` |

**Adding your calendar:** get your calendar's private iCal (ICS) link
(Google Calendar: Settings → your calendar → Integrate calendar → "Secret address in
iCal format"; Outlook: Settings → Calendar → Shared calendars → Publish a calendar → ICS
link) and paste it into **your `config.yaml`** (never `config.example.yaml`: anyone with
the link can read your calendar):

```yaml
widgets:
  calendar:
    calendars:
      - name: Alex
        url: "https://calendar.google.com/calendar/ical/.../basic.ics"
      - name: Sam
        url: "https://outlook.office365.com/owa/calendar/.../calendar.ics"
        colour: "#ffa66b"   # optional
```

Check it with `uv run mirror-hub --once calendar`. The links never appear in logs, errors
or the page. `days`, `max_events` and `refresh_minutes` are in `config.example.yaml`.

Each event shows your RSVP: a solid dot means you're going, a ring with "maybe" is
tentative, a faint dot with "?" means you haven't replied, and events you declined are
hidden (`show_declined: true` brings them back). Google feeds say whose calendar they are.
For other feeds, add `email:` to that calendar's entry so Mirror can find your reply. The
email stays private: only the going/maybe/not-replied state reaches the screen.

**Trying voices:**
```bash
uv run mirror-talk --voices                                  # list them all
uv run mirror-talk --say "Ey up, you look rough" --voice kokoro_bm_lewis   # hear one
```
Then set the one you like as `tts.voice` in your `config.yaml`.

**Renaming it:** set `assistant.name` in your `config.yaml` (and change the name in your
`mirror.md` persona too). The name is shown in the console and taught to speech-to-text,
so it isn't misheard as ordinary words. Add your own names to `stt.keyterms`
there as well (e.g. `keyterms: [Alex, Sam]`) so it hears who's talking about whom.

Your `config.yaml` and `mirror.md` are git-ignored (setup creates them from the
`*.example*` templates), so personal stuff is safe there.
**This repo is public**, so keep names and private details out of everything else.

## Mirror reads the board

Ask about what's on the screen and Mirror answers from it: "do I need a coat?",
"when's the next bus into town?", "what's my day like?", "what's Sam up to tomorrow?",
"give me a rundown". No tool calls: each question is matched against keyword lists
(`voice/src/mirror_voice/context.py`), and a few lines of the board's live data are added
under it as a `[Live info]` note:

| You say something about | It adds |
|---|---|
| anything at all | the time and date |
| weather, rain, coat, cold, umbrella, outside... | the weather |
| bus, into town, a route number ("the 24"), a destination | the next few buses |
| today, tomorrow, my day, meetings, busy, plans, a flatmate's name | today's and tomorrow's calendar |
| "rundown", "morning brief", "catch me up", "what's going on" | all of it, briefly |

To make it work well, in your `config.yaml`:

```yaml
assistant:
  people: [Alex, Sam]   # everyone in the flat, calendar or not
widgets:
  bus:
    town: [Leeds]       # destinations with this word count as "into town"
```

`people` lets "what's Sam up to?" narrow the calendar to Sam, and stops the model passing
someone else's plans off as theirs when they have no calendar linked. A widget that's
failing is described as "not updated since 14:05", or "unavailable": Mirror is told to
say it doesn't know rather than guess. The data only flows while the hub runs, which
`talk.sh` does whenever the display is on; without it Mirror only knows the time.
To teach it a new phrase, add it to one of the lists at the top of `context.py`.

## Buses

The bus widget shows departures from your stop like the countdown sign at a stop
(`33  Leeds Bus Stn  4 min`), from the government's free
[Bus Open Data Service](https://data.bus-data.dft.gov.uk/) (BODS).

1. **Find your stop's code.** Search for your stop on [bustimes.org](https://bustimes.org),
   open it, and copy the long number on its page (the ATCO code, e.g. `450010687`; West
   Yorkshire's start `450`). The two sides of a road are different stops with different
   codes, so pick the direction you want, or list both. The official list is
   [NaPTAN](https://beta-naptan.dft.gov.uk/) (the `ATCOCode` column).
2. **Put it in your `config.yaml`:**
   ```yaml
   widgets:
     bus:
       stops: ["450012345"]   # yours
       routes: ["33", "33A"]  # optional: just these
       walk_minutes: 4        # hide buses you can't make
   ```
3. **For live times, add a free BODS API key** (sign up at
   [data.bus-data.dft.gov.uk](https://data.bus-data.dft.gov.uk/account/signup/); the key
   is under *Account settings*) to a `.env` file in the repo folder (never committed):
   ```
   BODS_API_KEY=your-key-here
   ```
   Without a key you get timetable times, labelled as such. With one, buses that are
   being tracked show a small signal icon and a time worked out from where the bus is.
4. **Optional: one heading per direction.** If you list stops on both sides of the road,
   group them so each direction gets its own heading and next few buses (the groups'
   stops replace `stops`; NaPTAN's `Bearing` column says which way each stop faces):
   ```yaml
   widgets:
     bus:
       groups:
         - label: Town
           stops: ["450012345"]
         - label: Headingley
           stops: ["450012346", "450012347"]
       max_per_group: 3       # or max_departures on a single group
   ```

Check it with `uv run mirror-hub --once bus`. The first run each day downloads the
Yorkshire timetable (~150 MB, about 15 seconds on a Mac), keeps only your stop's buses
in `cache/bus/timetable.json` and deletes the download. Outside Yorkshire, set `region:`
(e.g. `north_west`).

## How it works

```
mic → Moonshine (speech-to-text) → llama.cpp (Llama 3.2 3B Instruct, abliterated)
    → Kokoro (text-to-speech, "George" by default, British male) → speakers
                                  ↘ display/ (orb + subtitles, live via Server-Sent Events)
hub (background threads: weather, calendars, buses) ↗
   └→ "Live info" note on each question, so Mirror can answer from the board
```

The reply is streamed and spoken sentence by sentence, so Mirror starts talking before
it has finished thinking. Widgets are fetched by the hub on their own timers and pushed
down the same event stream. More detail in [docs/decisions.md](docs/decisions.md);
adding a widget: [docs/widgets.md](docs/widgets.md).

## Repo layout

```
voice/         the talk loop (Python package: mirror_voice); mirror_voice/hub/ = widget fetchers
display/       the mirror screen (plain HTML/JS, served by the voice loop); widgets/ = one file each
personality/   personas now; fine-tuning datasets and scripts later
scripts/       setup.sh, talk.sh; pi/ for installing on and deploying to the Pi
deploy/        systemd services for the Pi
models/        downloaded models and voices (git-ignored)
cache/         downloaded data, e.g. the bus timetable (git-ignored)
docs/          decisions, Pi guide, widgets, roadmap
```

Working on it together: see [CONTRIBUTING.md](CONTRIBUTING.md).
