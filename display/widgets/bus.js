// Next buses: data from mirror_voice/hub/bus.py (Bus Open Data Service).
// Counts down by itself between refreshes, from each bus's `expected` Unix time.
(() => {
  const MINUTES_UNTIL_CLOCK = 30; // same rule as bus.py: "4 min" up to here, then "14:05"
  let last = null; // [body, data] from the most recent render, for the countdown
  let timer = null;

  // Little broadcast-waves mark for buses whose time comes from their live position.
  function liveIcon() {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 16 16");
    svg.setAttribute("class", "bus-live");
    svg.innerHTML =
      '<circle cx="4" cy="12" r="1.6"/><path d="M4 7.5a4.5 4.5 0 0 1 4.5 4.5"/>' +
      '<path d="M4 3a9 9 0 0 1 9 9"/>';
    return svg;
  }

  function due(bus, nowSeconds) {
    const minutes = Math.max(0, Math.floor((bus.expected - nowSeconds) / 60));
    if (minutes <= 0) return "Due";
    if (minutes > MINUTES_UNTIL_CLOCK) return bus.time;
    return `${minutes} min`;
  }

  // Drop buses that have gone since the last refresh (a minute's grace for live ones).
  const notGone = (list, now) => list.filter((b) => b.expected > now - (b.live ? 60 : 0));

  function rowsFor(buses, now, rows = Widgets.el("div", "bus-rows")) {
    const { el } = Widgets;
    for (const b of buses) {
      const when = el("div", "bus-when medium" + (b.live ? "" : " dim"));
      if (b.live) when.append(liveIcon());
      when.append(document.createTextNode(due(b, now)));
      rows.append(el("div", "bus-route medium", b.route), el("div", "bus-dest small dim", b.destination), when);
    }
    return rows;
  }

  function draw(body, data) {
    const { el } = Widgets;
    const now = Date.now() / 1000;
    const none = `No buses in the next ${data.horizon_minutes} min`;
    const children = [el("div", "small dim", data.stop)];
    let buses;

    if (data.groups) {
      // One heading per direction ("Town", "Headingley"), each with its next few buses.
      // All in one grid so the columns line up across groups.
      buses = [];
      const rows = el("div", "bus-rows");
      for (const g of data.groups) {
        const list = notGone(g.departures, now);
        buses.push(...list);
        rows.append(el("div", "small bus-heading", g.label));
        if (list.length) rowsFor(list, now, rows);
        else rows.append(el("div", "small dim bus-none", none));
      }
      children.push(rows);
    } else {
      buses = notGone(data.departures, now);
      children.push(buses.length ? rowsFor(buses, now) : el("div", "small", none));
    }

    if (buses.length && !buses.some((b) => b.live)) {
      children.push(el("div", "tiny dim", data.live_feed ? "Timetable times" : "Timetable times, no live data"));
    }
    body.replaceChildren(...children);
  }

  Widgets.register("bus", {
    slot: "bottom-right",
    title: "Buses",
    render(body, data) {
      last = [body, data];
      draw(body, data);
      timer ??= setInterval(() => last && draw(...last), 15000);
    },
  });
})();
