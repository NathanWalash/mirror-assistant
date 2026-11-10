// Weather: data from mirror_voice/hub/weather.py (Open-Meteo).
(() => {
  // Thin line icons, drawn on a 64x64 grid. Keys match `icon` from weather.py.
  const SUN_RAYS = [0, 45, 90, 135, 180, 225, 270, 315]
    .map((a) => `<line x1="32" y1="10" x2="32" y2="15" transform="rotate(${a} 32 32)"/>`)
    .join("");
  const cloud = (dy = 0) =>
    `<path transform="translate(0 ${dy})" d="M20 46h25a9 9 0 0 0 1-18a13 13 0 0 0-25-2a10 10 0 0 0-1 20z"/>`;
  const drops = (len) =>
    [22, 32, 42].map((x) => `<line x1="${x}" y1="44" x2="${x - 3}" y2="${44 + len}"/>`).join("");
  const ICONS = {
    clear: `<circle cx="32" cy="32" r="10"/>${SUN_RAYS}`,
    "clear-night": `<path d="M38 14a18 18 0 1 0 12 30a15 15 0 0 1-12-30z"/>`,
    "partly-cloudy":
      `<g transform="translate(-8 -8) scale(.8)"><circle cx="32" cy="32" r="10"/>${SUN_RAYS}</g>` +
      `<path fill="#000" d="M22 50h25a9 9 0 0 0 1-18a13 13 0 0 0-25-2a10 10 0 0 0-1 20z"/>`,
    cloud: cloud(),
    fog: [26, 33, 40, 47].map((y, i) => `<line x1="${12 + i * 3}" y1="${y}" x2="${52 - i * 2}" y2="${y}"/>`).join(""),
    drizzle: cloud(-8) + drops(4),
    rain: cloud(-8) + drops(10),
    snow: cloud(-8) + [22, 32, 42].map((x) => `<circle cx="${x}" cy="${48 + (x % 4)}" r="1.6"/>`).join(""),
    thunder: cloud(-8) + `<path d="M34 40l-6 10h7l-4 9"/>`,
  };

  Widgets.register("weather", {
    slot: "top-right",
    title: "Weather",
    render(body, w) {
      const { el } = Widgets;

      const now = el("div", "weather-now");
      const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      icon.setAttribute("viewBox", "0 0 64 64");
      icon.setAttribute("class", "weather-icon");
      icon.innerHTML = ICONS[w.icon] || ICONS.cloud;
      now.append(icon, el("div", "big", `${w.temp}°`));

      const range = [`High ${w.high}°`, `Low ${w.low}°`, w.place].filter(Boolean).join(" · ");

      const bars = el("div", "rain-bars");
      for (const h of w.rain.hours) {
        const col = el("div", "rain-hour");
        const bar = el("div", "rain-bar");
        bar.style.height = `${Math.max(h.chance, 3)}%`;
        bar.style.opacity = 0.35 + (h.chance / 100) * 0.65;
        col.append(el("div", "rain-track"), el("div", "tiny dim", h.time.slice(0, 2)));
        col.firstChild.append(bar);
        bars.append(col);
      }

      body.replaceChildren(
        now,
        el("div", "medium", w.condition),
        el("div", "small dim", range),
        el("div", "small weather-rain", w.rain.summary),
        bars,
      );
    },
  });
})();
