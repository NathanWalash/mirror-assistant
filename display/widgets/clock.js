// Clock and date. Runs entirely in the browser: no hub module, no events.
Widgets.register("clock", {
  slot: "top-left",
  title: "Clock",
  init(body) {
    const { el } = Widgets;
    const time = el("div", "big");
    const date = el("div", "medium dim");
    body.append(time, date);
    function tick() {
      const now = new Date();
      time.textContent = now.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
      date.textContent = now.toLocaleDateString("en-GB", {
        weekday: "long",
        day: "numeric",
        month: "long",
      });
      setTimeout(tick, 1000 - now.getMilliseconds() + 5); // just after each new second
    }
    tick();
  },
});
