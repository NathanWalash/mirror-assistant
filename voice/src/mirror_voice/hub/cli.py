"""Run the mirror display and widgets without the voice loop (no model, no mic).

uv run mirror-hub                  # serve the display with live widgets, Ctrl+C to quit
uv run mirror-hub --once weather   # fetch one widget now and print its data as JSON
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import webbrowser

from mirror_voice.config import WidgetConfig, load_config
from mirror_voice.display_server import Broadcaster, DisplayServer
from mirror_voice.hub import WIDGETS, Hub


def main() -> None:
    parser = argparse.ArgumentParser(description="Mirror display + widgets, no voice.")
    parser.add_argument("--once", metavar="WIDGET", help="fetch one widget, print it, exit")
    parser.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    cfg = load_config()

    if args.once:
        module = WIDGETS.get(args.once)
        if module is None:
            sys.exit(f"Unknown widget {args.once!r}. Known: {', '.join(WIDGETS)}")
        wc = cfg.widgets.get(args.once) or WidgetConfig.from_raw({})
        print(json.dumps(module.fetch(dict(wc.settings)), indent=2, ensure_ascii=False))
        return

    broadcaster = Broadcaster(cfg.display.page_settings())
    server = DisplayServer(cfg.root / "display", cfg.display.port, broadcaster).start()
    hub = Hub(cfg.widgets, broadcaster.publish).start()
    print(f"Display: {server.url}  (widgets: {', '.join(hub.refreshers) or 'none'})", flush=True)
    if cfg.display.open_browser and not args.no_browser:
        webbrowser.open(server.url)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\nTa-ra.")
    finally:
        hub.stop()
        server.stop()


if __name__ == "__main__":
    main()
