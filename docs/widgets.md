# Adding a widget

A widget is three small pieces: a Python module that **fetches**, a JS file that **draws**,
and a block in the config. Weather is the worked example; copy it.

```
voice/src/mirror_voice/hub/weather.py   fetch(settings) -> dict       (runs in the hub)
display/widgets/weather.js              Widgets.register("weather", …) (runs in the page)
config.example.yaml  widgets.weather    enabled, refresh_minutes, + its own settings
```

The name (`weather`) must match in all three places.

## 1. Fetch: `voice/src/mirror_voice/hub/<name>.py`

```python
DEFAULT_REFRESH_MINUTES = 15.0  # used if the config doesn't set refresh_minutes


def fetch(settings: dict[str, Any]) -> dict[str, Any]:
    """Return JSON-able data for the display. Raise on any failure."""
```

- `settings` is the widget's config block minus `enabled` and `refresh_minutes`.
- Use the standard library (`urllib.request`, always with a `timeout=`). Add a dependency
  only if you really need one (see CONTRIBUTING.md).
- Don't catch errors to return something half-empty: raise, and the hub handles it.
- Keep the network call thin and put the work in a pure `parse(payload, settings)` you can
  test with a saved response in `voice/tests/fixtures/` (no network in tests).
- Return what the screen needs, already tidied (rounded numbers, `"14:00"` strings,
  a one-line summary). Mirror will later read the same data to answer questions.
- Keep secrets (calendar links, API keys) out of the returned data and error messages.

Then register it in `voice/src/mirror_voice/hub/__init__.py`:

```python
from mirror_voice.hub import bus, weather

WIDGETS = {"weather": weather, "bus": bus}
```

## 2. Config: `config.example.yaml`

```yaml
widgets:
  bus:
    enabled: true
    refresh_minutes: 1
    stop_id: "450000000"   # a public example, not anyone's real stop
```

Real, personal values (your stop, your calendar's private ICS link, your home's
coordinates) go only in your git-ignored `config.yaml`. The example must work, or at
least fail gracefully, for anyone who clones the repo.

## 3. Draw: `display/widgets/<name>.js`

```js
Widgets.register("bus", {
  slot: "bottom-right",       // top-left | top-right | bottom-left | bottom-right
  title: "Buses",             // shown as "Buses unavailable" if there's no data yet
  order: 0,                   // optional: order within a shared slot
  render(body, data, event) { // called with each fresh `data` from fetch()
    const { el } = Widgets;
    body.replaceChildren(el("div", "medium", `${data.route} in ${data.minutes} min`));
  },
});
```

and load it in `display/index.html`, after `widgets.js`:

```html
<script src="widgets/bus.js"></script>
```

- `render` only ever gets real data. The registry handles the rest: if a fetch fails it
  dims the last data and adds "not updated since 14:05"; if there's never been any data
  it shows "<title> unavailable".
- Build DOM with `Widgets.el(tag, className, text)` / `textContent`, not `innerHTML` with
  fetched data.
- Use the shared type scale from `index.html` so everything matches and reads from 2m:
  `big` (the one headline number), `medium`, `small`, `tiny`, and `dim` for grey.
- Widget-specific CSS goes in `index.html`'s `<style>` under a comment with the widget name.
- No frameworks, CDNs or web fonts: the Pi shows this offline.
- A widget with no server side (like `clock.js`) uses `init(body)` instead of `render`
  and needs no Python module or config.

Slots: top-left has the clock, top-right the weather. **bottom-left** (calendar) and
**bottom-right** (buses) are free. Bottom slots are narrower (27% of the width) because
the subtitles share the bottom edge; keep those widgets to short lines.

## 4. Check it

```bash
uv run mirror-hub --once bus     # print what fetch() returns, using your config.yaml
uv run mirror-hub                # the screen with live widgets, no model or mic needed
uv run ruff check . && uv run ruff format --check . && uv run pytest
```

`voice/tests/test_hub.py` checks that every registered widget has a config block and a
JS file loaded by `index.html`.

## What goes over the wire

Every fetch, success or not, sends one event down `/events`:

```json
{"widget": "weather", "status": "ok", "data": {...}, "updated": 1762770000.0}
{"widget": "weather", "status": "stale", "data": {...last good...}, "updated": 1762770000.0, "error": "timed out"}
{"widget": "weather", "status": "error", "data": null, "updated": null, "error": "HTTP Error 400: Bad Request"}
```

`updated` is the Unix time of the last successful fetch. After a failure the hub retries
within a minute (or sooner if the widget's interval is shorter). The server replays each
widget's latest event to newly opened pages, so they fill in straight away.
