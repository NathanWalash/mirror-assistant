// Widget registry: each widget file calls Widgets.register(...) and index.html routes
// {"widget": ...} events from the hub to Widgets.update(...). See docs/widgets.md.
//
//   Widgets.register("weather", {
//     slot: "top-right",          // top-left | top-right | bottom-left | bottom-right
//     title: "Weather",           // used in "Weather unavailable"
//     order: 0,                   // optional: position when several widgets share a slot
//     init(body) {},              // optional: called once (e.g. a clock that ticks itself)
//     render(body, data, event) {},  // optional: called with fresh data from the hub
//   });
//
// The registry handles the stale/unavailable states, so render() only sees real data.
const Widgets = (() => {
  const widgets = {};

  // Small DOM helper for widget files: el("div", "big", "14:05") -> <div class="big">14:05</div>
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  const hhmm = (unixSeconds) =>
    new Date(unixSeconds * 1000).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });

  function register(name, def) {
    const slot = document.getElementById("slot-" + def.slot);
    if (!slot) {
      console.error(`Widget ${name}: no slot called ${def.slot}`);
      return;
    }
    const box = el("section", "widget widget-" + name);
    box.style.order = def.order ?? 0;
    const body = el("div", "widget-body");
    const note = el("div", "widget-note small dim");
    box.append(body, note);
    slot.append(box);
    widgets[name] = { def, box, body, note };
    def.init?.(body);
  }

  function update(event) {
    const w = widgets[event.widget];
    if (!w) return; // the hub knows a widget the page doesn't (yet)
    const ok = event.status === "ok";
    w.box.classList.toggle("stale", !ok);
    if (event.data) {
      w.def.render?.(w.body, event.data, event);
      w.note.textContent = ok || !event.updated ? "" : `not updated since ${hhmm(event.updated)}`;
    } else {
      w.body.replaceChildren(el("div", "small dim", `${w.def.title || event.widget} unavailable`));
      w.note.textContent = "";
    }
  }

  return { register, update, el };
})();
