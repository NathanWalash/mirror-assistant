// Calendar: both flatmates' next few days, from mirror_voice/hub/calendar.py.
//
// RSVP: each person's dot is styled by their own response (solid = going, ring = maybe,
// faint = not replied, struck = declined/cancelled); the title follows the keenest person.
(() => {
  const SUFFIX = { tentative: "maybe", needs_action: "?", declined: "declined", cancelled: "cancelled" };

  function dot(colour, response, name) {
    const d = Widgets.el("span", `cal-dot rsvp-${response || "accepted"}`);
    d.style.color = colour; // CSS paints the dot (fill or ring) in currentColor
    if (name) d.title = response && response !== "accepted" ? `${name}: ${response}` : name;
    return d;
  }

  Widgets.register("calendar", {
    slot: "bottom-left",
    title: "Calendar",
    render(body, cal) {
      const { el } = Widgets;
      const parts = [];

      for (const day of cal.days) {
        const block = el("div", "cal-day");
        block.append(el("div", "small cal-heading", day.label));
        if (!day.events.length) block.append(el("div", "small dim", "Nothing on"));
        for (const e of day.events) {
          const response = e.response || "accepted";
          const row = el("div", `small cal-event rsvp-${response}`);
          const dots = el("span", "cal-dots");
          e.colours.forEach((colour, i) => dots.append(dot(colour, e.responses?.[i], e.who[i])));
          // Time column: "14:30", "All day", or "→ Sat" for something running over several days.
          const time = e.until_short ? `→ ${e.until_short}` : e.all_day ? "All day" : e.time;
          // The RSVP tag sits outside the title so a long title's "…" never hides it.
          row.append(dots, el("span", "cal-time dim", time), el("span", "cal-title", e.title));
          if (SUFFIX[response]) row.append(el("span", "cal-rsvp", SUFFIX[response]));
          block.append(row);
        }
        parts.push(block);
      }

      if (cal.more) parts.push(el("div", "tiny dim", `+${cal.more} more`));

      // Whose colour is whose, once there's more than one person.
      if (cal.people.length > 1) {
        const key = el("div", "tiny dim cal-key");
        for (const p of cal.people) key.append(dot(p.colour), el("span", "", p.name));
        parts.push(key);
      }

      for (const note of cal.notes) parts.push(el("div", "tiny dim", note));
      body.replaceChildren(...parts);
    },
  });
})();
