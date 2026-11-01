// Ticket lookup: score a stored ticket from what was known when it was
// created, then compare the prediction with what actually happened.
//
// Tickets created before the test period were used to train the model, so
// their scores are more confident than a new ticket's would be. The page
// says so whenever that applies.

import { ApiError, getJSON, postJSON } from "../api.js";
import { el, pageHeader, replaceChildren } from "../dom.js";
import { explanationPanel } from "../explanation.js";
import { humanize } from "../features.js";
import { formatDay } from "../format.js";
import { reasonsCard, riskCard } from "../risk.js";

const EXAMPLE_LABELS = {
  caught_breach: "Caught breach",
  false_alarm: "False alarm",
  missed_breach: "Missed breach",
};

// What the flag and the outcome mean together.
const VERDICTS = {
  "true,true": { label: "Caught breach", text: "Flagged, and it did miss its SLA. Review would have helped here." },
  "true,false": { label: "False alarm", text: "Flagged, but it met its SLA. Reviewing it would have cost time without changing the outcome." },
  "false,true": { label: "Missed breach", text: "Not flagged, but it missed its SLA. The model did not see this one coming." },
  "false,false": { label: "Correctly not flagged", text: "Not flagged, and it met its SLA." },
};

export async function render(container, params) {
  const [reference, evaluation] = await Promise.all([getJSON("/reference"), getJSON("/model/evaluation")]);
  const trainStart = evaluation.train_period[0].slice(0, 10);
  const testStart = evaluation.test_period[0].slice(0, 10);
  const testEnd = evaluation.test_period[1].slice(0, 10);

  const input = el("input", { type: "search", id: "ticket-id", placeholder: "TKT-041779", autocomplete: "off",
                              spellcheck: "false", value: params.get("id") || "" });
  const form = el("form", { class: "lookup-form", role: "search" },
    el("label", { for: "ticket-id", class: "field-label" }, "Ticket ID"),
    el("div", { class: "lookup-row" }, input, el("button", { type: "submit", class: "button" }, "Look up")));
  const examples = el("div", { class: "preset-group", role: "group", "aria-label": "Example tickets from the test period" },
    evaluation.examples.map((example) => el("button", {
      type: "button", class: "preset", onclick: () => lookUp(example.ticket_id),
    }, `${EXAMPLE_LABELS[example.case]}: ${example.ticket_id}`)));

  const status = el("p", { class: "load-status", role: "status", "aria-live": "polite" });
  const result = el("div", { class: "page-body" });

  container.append(
    pageHeader("Ticket lookup", "Score a past ticket as the model would have when it arrived, and compare with what actually happened."),
    el("div", { class: "filter-row" }, form,
      el("div", { class: "lookup-examples" }, el("span", { class: "field-label" }, "Examples from the test period"), examples)),
    status, result);

  async function lookUp(rawId) {
    const id = rawId.trim().toUpperCase();
    input.value = id;
    if (!id) {
      status.textContent = "Enter a ticket ID, such as TKT-041779.";
      return;
    }
    history.replaceState(null, "", `#/tickets?id=${encodeURIComponent(id)}`);
    result.classList.add("is-loading");
    status.textContent = "Scoring…";
    try {
      const ticket = await getJSON(`/tickets/${encodeURIComponent(id)}/risk`);
      showTicket(ticket);
      status.textContent = `Scored from the features ${ticket.ticket_id} had when it was created.`;
    } catch (error) {
      replaceChildren(result);
      status.textContent = error instanceof ApiError && error.status === 404
        ? `There is no ticket ${id}. IDs look like TKT-041779.`
        : `Could not score this ticket: ${error.message}`;
    } finally {
      result.classList.remove("is-loading");
    }
  }

  function showTicket(ticket) {
    const risk = riskCard(reference.threshold, "Predicted chance of missing the SLA");
    const reasons = reasonsCard();
    risk.show(ticket.risk, ticket.flagged);
    reasons.show(ticket);
    reasons.root.append(explanationPanel(() =>
      postJSON(`/tickets/${encodeURIComponent(ticket.ticket_id)}/explanation`)).root);

    const note = dataNote(ticket, { trainStart, testStart, testEnd });
    if (note) risk.extra.append(el("p", { class: "chart-note" }, note));

    replaceChildren(result,
      el("div", { class: "sim-layout" },
        ticketFacts(ticket),
        el("div", { class: "sim-results" }, risk.root, reasons.root)));
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    lookUp(input.value);
  });
  if (input.value) await lookUp(input.value);
}

// Which part of the modeling data the ticket belonged to, when it matters
// for how far to trust its score. Only resolved tickets were modelled.
function dataNote(ticket, { trainStart, testStart, testEnd }) {
  const created = ticket.created_at.slice(0, 10);
  if (created < trainStart) {
    return `Created before ${formatDay(trainStart)}. The first month was left out of modeling because the `
      + "history features (recent breach rates, recent arrivals) need a month of data, so treat this score with care.";
  }
  if (created > testEnd) {
    return `Created after the evaluation period, which ends ${formatDay(testEnd)}. Many tickets from the last two `
      + "weeks were still open when the data ends, so these were left out of training and testing.";
  }
  if (created < testStart && ticket.sla_breached !== null) {
    return "This ticket was in the training data, so the model has seen its outcome and the score is likely more "
      + `confident than it would be for a new ticket. Tickets created from ${formatDay(testStart)} were held out.`;
  }
  return null;
}

function ticketFacts(ticket) {
  const inputs = ticket.inputs;
  const [date, time] = ticket.created_at.split("T");
  const outcome = ticket.sla_breached === null
    ? `Unknown: the ticket is ${humanize(ticket.status).toLowerCase()}`
    : ticket.sla_breached ? "Missed its SLA" : "Met its SLA";
  const verdict = ticket.sla_breached === null ? null : VERDICTS[`${ticket.flagged},${ticket.sla_breached}`];

  const facts = [
    ["Created", `${formatDay(date)}, ${time.slice(0, 5)}`],
    ["Priority", inputs.priority],
    ["Issue", humanize(inputs.subcategory)],
    ["Assigned team", inputs.assigned_team],
    ["Requester", humanize(inputs.requester_type)],
    ["Channel", humanize(inputs.channel)],
    ["Status", humanize(ticket.status)],
    ["Outcome", outcome],
  ];

  return el("section", { class: "card ticket-facts" },
    el("h2", {}, ticket.ticket_id),
    verdict && el("div", { class: "verdict", dataset: { correct: String(ticket.flagged === ticket.sla_breached) } },
      el("p", { class: "verdict-label" }, verdict.label),
      el("p", {}, verdict.text)),
    el("dl", { class: "facts" }, facts.flatMap(([label, value]) => [el("dt", {}, label), el("dd", {}, value)])),
    el("a", { class: "button button-secondary", href: simulatorLink(ticket) }, "Try variations in the simulator"),
    el("p", { class: "field-note" },
      "The simulator rounds the time to the half hour and recomputes the queue for that moment, so its score can differ slightly."));
}

// The same ticket in the simulator, at the half hour it was created in.
function simulatorLink(ticket) {
  const [date, time] = ticket.created_at.split("T");
  const [hours, minutes] = time.split(":");
  const inputs = ticket.inputs;
  return `#/simulator?${new URLSearchParams({
    date, time: `${hours}:${Number(minutes) < 30 ? "00" : "30"}`,
    priority: inputs.priority, subcategory: inputs.subcategory, assigned_team: inputs.assigned_team,
    requester_type: inputs.requester_type, channel: inputs.channel,
  })}`;
}
