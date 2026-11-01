// A list of similar past tickets and what happened to them. Descriptions are
// inserted as text, like everything else from the API.

import { el } from "./dom.js";
import { humanize } from "./features.js";
import { formatDay, formatHours } from "./format.js";

function outcomeLabel(ticket) {
  if (ticket.sla_breached === null) return humanize(ticket.status);
  return ticket.sla_breached ? "Missed its SLA" : "Met its SLA";
}

function summary({ resolved, breached, median_resolution_hours: median }) {
  if (resolved === 0) return null;
  return `Of the ${resolved} finished, ${breached} missed the SLA, with a median of ${formatHours(median)} to resolve. `
    + "A handful of tickets is an illustration, not a statistic.";
}

export function similarResults(found, title, description) {
  if (found.tickets.length === 0) {
    return el("section", { class: "card" },
      el("h2", {}, title),
      el("p", {}, "No close matches. This may not describe an IT issue, or nothing like it came in earlier."));
  }
  const note = summary(found.outcomes);
  return el("section", { class: "card" },
    el("header", { class: "chart-header" }, el("h2", {}, title), el("p", {}, description)),
    note && el("p", { class: "chart-summary" }, note),
    el("ol", { class: "similar-list" }, found.tickets.map((ticket) => el("li", { class: "similar-item" },
      el("a", { href: `#/tickets?id=${encodeURIComponent(ticket.ticket_id)}` }, ticket.description),
      el("span", { class: "badge" }, outcomeLabel(ticket)),
      el("span", { class: "similar-meta" },
        `${ticket.ticket_id} · ${formatDay(ticket.created_at.slice(0, 10))} · ${humanize(ticket.subcategory)} · `
        + `${ticket.assigned_team} · similarity ${ticket.similarity.toFixed(2)}`)))));
}
