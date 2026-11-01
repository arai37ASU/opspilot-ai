// Risk simulator: build a ticket, choose when it arrives, and see the model's
// predicted risk of an SLA breach, the reasons behind it, and how the same
// ticket's risk changes across the day.
//
// The page sends exactly what POST /predictions accepts. The API computes the
// queue features (backlog, recent arrivals, recent breach rates) from the
// database as of the chosen moment, so the date matters as well as the time.

import { getJSON, postJSON } from "../api.js";
import { axisStyle, chartCard, drawChart, escapeHtml, fillTable, tooltipStyle } from "../charts.js";
import { el, pageHeader, replaceChildren } from "../dom.js";
import { explanationPanel } from "../explanation.js";
import { humanize } from "../features.js";
import { formatDay } from "../format.js";
import { percentLabel, reasonsCard, riskCard } from "../risk.js";

// The day is scored in half-hour slots: 48 tickets, the batch endpoint's limit.
const SLOTS = 48;
const SLOT_TIMES = Array.from({ length: SLOTS }, (_, i) =>
  `${String(Math.floor(i / 2)).padStart(2, "0")}:${i % 2 ? "30" : "00"}`);

// Moving the slider fires many events; wait this long after the last one
// before asking the API for reasons.
const DEBOUNCE_MS = 150;

const EXAMPLES = [
  {
    label: "Projector, Wednesday evening",
    ticket: { date: "2025-09-03", time: "19:30", priority: "P2", subcategory: "projector_display",
              assigned_team: "Classroom Technology", requester_type: "faculty", channel: "phone" },
  },
  {
    label: "Password reset, Tuesday morning",
    ticket: { date: "2025-10-14", time: "10:00", priority: "P3", subcategory: "password_reset",
              assigned_team: "Service Desk", requester_type: "student", channel: "portal" },
  },
  {
    label: "Wi-Fi sent to the wrong team",
    ticket: { date: "2025-09-08", time: "14:00", priority: "P2", subcategory: "wifi_connectivity",
              assigned_team: "Service Desk", requester_type: "student", channel: "chat" },
  },
];
const FIELDS = Object.keys(EXAMPLES[0].ticket);

export async function render(container, params) {
  const reference = await getJSON("/reference");
  const subcategories = new Map(reference.subcategories.map((row) => [row.subcategory, row]));
  const ticket = initialTicket(params, reference, subcategories);
  const threshold = reference.threshold;

  // ---- Controls ----
  const dateInput = el("input", { type: "date", id: "sim-date", min: reference.date_range.start,
                                  max: reference.date_range.end, value: ticket.date });
  const timeOutput = el("output", { for: "sim-time", class: "time-output" });
  const timeSlider = el("input", { type: "range", id: "sim-time", min: 0, max: SLOTS - 1, step: 1,
                                   value: SLOT_TIMES.indexOf(ticket.time) });
  const priorityGroup = el("div", { class: "segmented", role: "group", "aria-labelledby": "sim-priority-label" });
  const subcategorySelect = el("select", { id: "sim-subcategory" }, subcategoryOptions(reference.subcategories));
  const teamSelect = el("select", { id: "sim-team" },
    reference.teams.map((team) => el("option", { value: team.team }, team.team)));
  const teamNote = el("p", { class: "field-note", id: "sim-team-note" });
  const requesterSelect = select("sim-requester", reference.requester_types);
  const channelSelect = select("sim-channel", reference.channels);

  const examples = el("div", { class: "preset-group", role: "group", "aria-label": "Example tickets" },
    EXAMPLES.map((example) => el("button", {
      type: "button", class: "preset", onclick: () => { Object.assign(ticket, example.ticket); changed("all"); },
    }, example.label)));

  const form = el("form", { class: "card sim-controls", "aria-label": "Ticket details" },
    el("h2", {}, "The ticket"),
    field("When it arrives", "sim-date", dateInput),
    el("div", { class: "field" },
      el("div", { class: "field-row" }, el("label", { for: "sim-time" }, "Time of day"), timeOutput),
      timeSlider),
    el("div", { class: "field" }, el("span", { class: "field-label", id: "sim-priority-label" }, "Priority"), priorityGroup),
    field("Issue", "sim-subcategory", subcategorySelect),
    field("Assigned team", "sim-team", teamSelect, teamNote),
    field("Requester", "sim-requester", requesterSelect),
    field("Channel", "sim-channel", channelSelect));
  form.addEventListener("submit", (event) => event.preventDefault());

  // ---- Results ----
  const risk = riskCard(threshold);
  const reasons = reasonsCard();
  const explanation = explanationPanel(() => postJSON("/explanations", toRequest(ticket, ticket.time)));
  reasons.root.append(explanation.root);
  const thresholdPercent = percentLabel(threshold);

  const dayCard = chartCard("Risk across the day",
    "The same ticket arriving at every half hour of the chosen day. Click the chart to pick a time.");
  const daySummary = el("p", { class: "chart-summary" });
  dayCard.chart.before(daySummary);

  const status = el("p", { class: "load-status", role: "status", "aria-live": "polite" });
  const results = el("div", { class: "sim-results" }, risk.root, reasons.root);

  container.append(
    pageHeader("Risk simulator", "Build a ticket and see how likely it is to miss its SLA, why, and how the answer changes with the time it arrives."),
    el("div", { class: "filter-row" }, el("span", { class: "field-label" }, "Try an example"), examples),
    status,
    el("div", { class: "sim-layout" }, form, results),
    dayCard.root);

  // ---- Behaviour ----
  const charts = {};
  let dayRisks = null;  // the 48 batch results for the current ticket's day
  let singleRequest = 0;
  let dayRequest = 0;
  let debounce = null;
  let chartClicksBound = false;

  function syncControls() {
    const allowed = subcategories.get(ticket.subcategory).allowed_priorities;
    replaceChildren(priorityGroup, reference.priorities.map((priority) => el("button", {
      type: "button", class: "preset", "aria-pressed": priority === ticket.priority ? "true" : "false",
      disabled: !allowed.includes(priority),
      title: allowed.includes(priority) ? null : "No SLA policy for this priority on this issue",
      onclick: () => { ticket.priority = priority; changed("all"); },
    }, priority)));
    dateInput.value = ticket.date;
    timeSlider.value = SLOT_TIMES.indexOf(ticket.time);
    timeOutput.textContent = ticket.time;
    timeSlider.setAttribute("aria-valuetext", ticket.time);
    subcategorySelect.value = ticket.subcategory;
    teamSelect.value = ticket.assigned_team;
    requesterSelect.value = ticket.requester_type;
    channelSelect.value = ticket.channel;

    const owner = subcategories.get(ticket.subcategory).owning_team;
    teamNote.textContent = owner === ticket.assigned_team
      ? "The team that normally handles this issue."
      : `Normally handled by ${owner}. Assigning another team counts as misrouting.`;
    teamNote.dataset.warning = owner === ticket.assigned_team ? "false" : "true";
  }

  // "time" means only the slider moved, so the day curve is still valid.
  function changed(what) {
    syncControls();
    explanation.reset();
    history.replaceState(null, "", `#/simulator?${new URLSearchParams(ticket)}`);
    if (what === "time") {
      showFromDay();
      clearTimeout(debounce);
      debounce = setTimeout(scoreSelected, DEBOUNCE_MS);
    } else {
      scoreDay();
      scoreSelected();
    }
  }

  async function scoreSelected() {
    const request = ++singleRequest;
    status.textContent = "Scoring…";
    try {
      const prediction = await postJSON("/predictions", toRequest(ticket, ticket.time));
      if (request !== singleRequest) return;  // a newer request has been sent
      risk.show(prediction.risk, prediction.flagged);
      reasons.show(prediction);
      status.textContent = `Scored as of ${formatDay(ticket.date)} at ${ticket.time}, using the queue as it was then.`;
    } catch (error) {
      if (request === singleRequest) status.textContent = `Could not score this ticket: ${error.message}`;
    }
  }

  async function scoreDay() {
    const request = ++dayRequest;
    dayCard.root.classList.add("is-loading");
    try {
      const batch = await postJSON("/predictions/batch",
        { tickets: SLOT_TIMES.map((time) => toRequest(ticket, time)) });
      if (request !== dayRequest) return;
      dayRisks = batch.risks;
      drawDay();
    } catch (error) {
      if (request === dayRequest) daySummary.textContent = `Could not score the day: ${error.message}`;
    } finally {
      if (request === dayRequest) dayCard.root.classList.remove("is-loading");
    }
  }

  // While the slider moves, the headline and the marker update at once from
  // the day's results; the reasons follow when the debounced request returns.
  function showFromDay() {
    if (!dayRisks) return;
    const slot = dayRisks[SLOT_TIMES.indexOf(ticket.time)];
    risk.show(slot.risk, slot.flagged);
    drawDay();
  }

  function drawDay() {
    const selected = SLOT_TIMES.indexOf(ticket.time);
    const percents = dayRisks.map((slot) => slot.risk * 100);
    const flaggedSlots = dayRisks.filter((slot) => slot.flagged).length;
    const low = percents.indexOf(Math.min(...percents));
    const high = percents.indexOf(Math.max(...percents));
    daySummary.textContent = `Lowest at ${SLOT_TIMES[low]} (${percents[low].toFixed(0)}%), highest at `
      + `${SLOT_TIMES[high]} (${percents[high].toFixed(0)}%). Flagged in ${flaggedSlots} of ${SLOTS} half-hour slots.`;
    dayCard.chart.setAttribute("aria-label", `Line chart of predicted risk for each half hour of ${formatDay(ticket.date)}. `
      + "The same values are in the table below.");

    drawChart(charts, "day", dayCard, (colors) => ({
      grid: { left: 48, right: 24, top: 24, bottom: 32, containLabel: false },
      tooltip: {
        ...tooltipStyle(colors), trigger: "axis",
        axisPointer: { type: "line", lineStyle: { color: colors.muted, width: 1 } },
        formatter: ([item]) => `${escapeHtml(SLOT_TIMES[item.dataIndex])}<br><b>${item.value.toFixed(0)}%</b> risk`
          + (dayRisks[item.dataIndex].flagged ? "<br>Flagged for review" : ""),
      },
      xAxis: {
        type: "category", data: SLOT_TIMES, boundaryGap: false, ...axisStyle(colors), splitLine: { show: false },
        axisLabel: { ...axisStyle(colors).axisLabel, interval: 5 },
      },
      yAxis: { type: "value", min: 0, max: 100, ...axisStyle(colors),
               axisLabel: { ...axisStyle(colors).axisLabel, formatter: (v) => `${v}%` } },
      series: [{
        type: "line",
        data: percents,
        lineStyle: { color: colors.accent, width: 2, cap: "round", join: "round" },
        symbol: "circle",
        symbolSize: (value, item) => (item.dataIndex === selected ? 10 : 0),
        showSymbol: true,
        // The selected point takes the flag colour; the badge above says the same in words.
        itemStyle: { color: dayRisks[selected].flagged ? colors.risk.high : colors.risk.low,
                     borderColor: colors.surface, borderWidth: 2 },
        // Everything above the threshold is the flagged zone, shaded and labelled.
        markArea: {
          silent: true,
          itemStyle: { color: colors.risk.high, opacity: 0.08 },
          label: { show: true, position: "insideTopLeft", color: colors.text, formatter: "Flagged for review" },
          data: [[{ yAxis: threshold * 100 }, { yAxis: 100 }]],
        },
        markLine: {
          silent: true, symbol: "none", animation: false,
          data: [
            { yAxis: threshold * 100, lineStyle: { color: colors.risk.high, type: "dashed", width: 1 },
              label: { formatter: `Review threshold ${thresholdPercent}`, position: "insideEndBottom", color: colors.text } },
            { xAxis: selected, lineStyle: { color: colors.text, type: "solid", width: 1, opacity: 0.35 },
              label: { formatter: ticket.time, position: "end", color: colors.text, fontWeight: 600 } },
          ],
        },
      }],
    }));
    fillTable(dayCard.table, `Predicted risk on ${formatDay(ticket.date)}`, ["Time", "Risk", "Flagged"],
      dayRisks.map((slot, i) => [SLOT_TIMES[i], `${(slot.risk * 100).toFixed(1)}%`, slot.flagged ? "Yes" : "No"]));

    if (!chartClicksBound) {
      const chart = charts.day.instance;
      chart.getZr().on("click", (event) => {
        const point = [event.offsetX, event.offsetY];
        if (!chart.containPixel("grid", point)) return;
        const [index] = chart.convertFromPixel({ seriesIndex: 0 }, point);
        ticket.time = SLOT_TIMES[Math.min(Math.max(Math.round(index), 0), SLOTS - 1)];
        changed("time");
      });
      chartClicksBound = true;
    }
  }

  dateInput.addEventListener("change", () => {
    if (!dateInput.value) return;
    ticket.date = dateInput.value;
    changed("all");
  });
  timeSlider.addEventListener("input", () => {
    ticket.time = SLOT_TIMES[Number(timeSlider.value)];
    changed("time");
  });
  subcategorySelect.addEventListener("change", () => {
    const row = subcategories.get(subcategorySelect.value);
    ticket.subcategory = row.subcategory;
    // A new issue goes to the team that owns it, at a priority it allows.
    ticket.assigned_team = row.owning_team;
    if (!row.allowed_priorities.includes(ticket.priority)) ticket.priority = row.allowed_priorities[0];
    changed("all");
  });
  for (const [control, key] of [[teamSelect, "assigned_team"], [requesterSelect, "requester_type"], [channelSelect, "channel"]]) {
    control.addEventListener("change", () => { ticket[key] = control.value; changed("all"); });
  }

  changed("all");
  return () => {
    clearTimeout(debounce);
    Object.values(charts).forEach((chart) => chart.dispose());
  };
}

// The ticket in the link if it is valid, otherwise the first example.
function initialTicket(params, reference, subcategories) {
  const ticket = { ...EXAMPLES[0].ticket };
  for (const key of FIELDS) if (params.has(key)) ticket[key] = params.get(key);

  const { start, end } = reference.date_range;
  const subcategory = subcategories.get(ticket.subcategory);
  const valid = subcategory
    && /^\d{4}-\d{2}-\d{2}$/.test(ticket.date) && ticket.date >= start && ticket.date <= end
    && SLOT_TIMES.includes(ticket.time)
    && subcategory.allowed_priorities.includes(ticket.priority)
    && reference.teams.some((team) => team.team === ticket.assigned_team)
    && reference.requester_types.includes(ticket.requester_type)
    && reference.channels.includes(ticket.channel);
  return valid ? ticket : { ...EXAMPLES[0].ticket };
}

function toRequest(ticket, time) {
  const { date, time: _, ...rest } = ticket;
  return { ...rest, created_at: `${date}T${time}:00` };
}

function subcategoryOptions(subcategories) {
  const byCategory = new Map();
  for (const row of subcategories) {
    if (!byCategory.has(row.category)) byCategory.set(row.category, []);
    byCategory.get(row.category).push(row);
  }
  return [...byCategory].map(([category, rows]) => el("optgroup", { label: category },
    rows.map((row) => el("option", { value: row.subcategory }, humanize(row.subcategory)))));
}

function select(id, values) {
  return el("select", { id }, values.map((value) => el("option", { value }, humanize(value))));
}

function field(label, id, control, note) {
  return el("div", { class: "field" }, el("label", { for: id, class: "field-label" }, label), control, note);
}
