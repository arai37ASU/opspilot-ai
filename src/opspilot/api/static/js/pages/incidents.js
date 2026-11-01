// Incident radar: two years of daily volume as a calendar, with unusual
// bursts of one issue marked on it.
//
// Which bursts are suspected incidents is decided by the API from ticket data
// alone (/metrics/spikes). A calendar is a poor target for a keyboard or a
// phone, so every event is also a button and any day can be typed in.

import { getJSON } from "../api.js";
import { axisStyle, chartCard, drawChart, dataTable, escapeHtml, fillTable, tooltipStyle } from "../charts.js";
import { el, pageHeader, replaceChildren } from "../dom.js";
import { humanize } from "../features.js";
import {
  CENSORING_DAYS, daysBetween, formatDay, formatInteger, formatPercent, formatShortDay,
} from "../format.js";

const CELL_HEIGHT = 16;
const YEAR_GAP = 48;

export async function render(container, params) {
  const [reference, daily, spikes] = await Promise.all([
    getJSON("/reference"), getJSON("/metrics/daily"), getJSON("/metrics/spikes"),
  ]);
  const { start: first, end: last } = reference.date_range;
  const days = new Map(daily.map((row) => [row.day, row]));
  const owners = new Map(reference.subcategories.map((row) => [row.subcategory, row.owning_team]));
  const years = [...new Set(daily.map((row) => row.day.slice(0, 4)))];
  const incidents = spikes.episodes.filter((episode) => episode.kind === "one_off");
  const surgeDays = spikes.days.filter((day) => day.kind === "recurring");
  const spikesOn = (day) => spikes.days.filter((spike) => spike.day === day);

  const calendarCard = chartCard("Tickets per day",
    "Each square is a day; darker means more tickets. Select a day to see what happened.");
  const scroller = el("div", { class: "calendar-scroll" });
  calendarCard.chart.classList.add("chart-calendar");
  calendarCard.chart.replaceWith(scroller);
  scroller.append(calendarCard.chart);
  scroller.after(el("ul", { class: "mark-key", "aria-label": "Calendar marks" },
    el("li", {}, el("span", { class: "mark mark-incident" }), "Suspected incident"),
    el("li", {}, el("span", { class: "mark mark-surge" }), "Recurring surge")));

  const dayInput = el("input", { type: "date", id: "radar-day", min: first, max: last });
  const dayPanel = el("div", { class: "day-panel", "aria-live": "polite" });
  const incidentList = el("ul", { class: "event-list" }, incidents.map((episode) => el("li", {},
    el("button", { type: "button", class: "event", dataset: { start: episode.start }, onclick: () => select(episode.start) },
      el("span", { class: "event-title" }, humanize(episode.subcategory)),
      el("span", { class: "event-date" }, episodeDates(episode)),
      el("span", { class: "event-numbers" },
        `${formatInteger(episode.tickets)} tickets, usually ${typicalLabel(episode.typical_daily)} a day; `
        + `${formatInteger(episode.peak_two_hours)} in the busiest two hours`)))));

  container.append(
    pageHeader("Incident radar", "Two years of daily volume, with unusual bursts of the same issue found from ticket data alone."),
    el("div", { class: "page-body" },
      calendarCard.root,
      el("div", { class: "radar-columns" },
        el("section", { class: "card" },
          el("div", { class: "day-heading" },
            el("h2", {}, "Selected day"),
            el("div", { class: "date-fields" }, el("label", { for: "radar-day" }, "Go to"), dayInput)),
          dayPanel),
        el("section", { class: "card" },
          el("header", { class: "chart-header" },
            el("h2", {}, `${incidents.length} suspected incidents`),
            el("p", {}, "Issues that spiked once in two years and never came back.")),
          incidentList)),
      el("section", { class: "card" },
        el("header", { class: "chart-header" },
          el("h2", {}, "How a burst is found"),
          el("p", {}, "A day counts as a spike when an issue has at least four times its median daily tickets and at "
            + "least 15 more than that median. Spikes in a row form an episode. An issue with one episode is a suspected "
            + "incident; an issue that comes back is a recurring surge.")),
        el("p", { class: "chart-note" },
          "This rule has blind spots. Two outages of the same kind would count as recurring, and a seasonal surge "
          + "looks like an incident the first time it happens. The incidents here are inferred, not confirmed."),
        el("details", { class: "table-view" },
          el("summary", {}, `Show the ${surgeDays.length} recurring surge days`),
          el("div", { class: "table-scroll" }, dataTable("Recurring surge days", ["Day", "Issue", "Tickets", "Typical day", "Busiest 2 hours"],
            surgeDays.map((spike) => [formatDay(spike.day), humanize(spike.subcategory), formatInteger(spike.tickets),
                                      formatInteger(spike.typical_daily), formatInteger(spike.peak_two_hours)])))))));

  const charts = {};
  let selected = null;

  function select(day) {
    if (!days.has(day)) return;
    selected = day;
    dayInput.value = day;
    history.replaceState(null, "", `#/incidents?day=${day}`);
    showDay();
    for (const button of incidentList.querySelectorAll(".event")) {
      const episode = incidents.find((item) => item.start === button.dataset.start);
      button.setAttribute("aria-pressed", String(day >= episode.start && day <= episode.end));
    }
    drawCalendar();
    // Where the calendar scrolls sideways, bring the selected month into view.
    const yearProgress = (Number(day.slice(5, 7)) - 1) / 11;
    scroller.scrollLeft = yearProgress * (scroller.scrollWidth - scroller.clientWidth);
  }

  function showDay() {
    const row = days.get(selected);
    const spikesToday = spikesOn(selected);
    const tags = [humanize(row.academic_period), row.is_weekend && "Weekend", row.is_holiday && "Holiday"].filter(Boolean);
    replaceChildren(dayPanel,
      el("p", { class: "day-date" }, formatDay(selected)),
      el("p", { class: "field-note" }, tags.join(" · ")),
      el("dl", { class: "facts" },
        el("dt", {}, "Tickets"), el("dd", {}, formatInteger(row.tickets)),
        el("dt", {}, "Breach rate"), el("dd", {}, formatPercent(row.breach_rate_pct))),
      daysBetween(selected, last) <= CENSORING_DAYS && el("p", { class: "chart-note" },
        "Slow tickets from the last two weeks were still open when the data ends, so this rate is lower than the final one would be."),
      spikesToday.length === 0
        ? el("p", { class: "field-note" }, "No unusual burst of any one issue.")
        : el("ul", { class: "spike-list" }, spikesToday.map((spike) => el("li", { class: "spike", dataset: { kind: spike.kind } },
          el("span", { class: "event-title" }, humanize(spike.subcategory)),
          el("span", { class: "badge" }, spike.kind === "one_off" ? "Suspected incident" : "Recurring surge"),
          el("p", { class: "field-note" },
            `${formatInteger(spike.tickets)} tickets, usually ${typicalLabel(spike.typical_daily)} a day; `
            + `${formatInteger(spike.peak_two_hours)} in the busiest two hours. Handled by ${owners.get(spike.subcategory)}.`)))));
  }

  function drawCalendar() {
    calendarCard.chart.setAttribute("aria-label", "Calendar of tickets per day for each year, with spikes marked. "
      + "The same values are in the table below, and the incidents are listed on this page.");
    const inYear = (year) => (row) => row.day.startsWith(year);
    const mostTickets = Math.max(...daily.map((row) => row.tickets));

    drawChart(charts, "calendar", calendarCard, (colors) => {
      const marks = (kind, style, size) => years.map((year, calendarIndex) => ({
        type: "scatter", coordinateSystem: "calendar", calendarIndex, symbolSize: size, itemStyle: style,
        data: [...new Set(spikes.days.filter((spike) => spike.kind === kind && spike.day.startsWith(year)).map((spike) => spike.day))]
          .map((day) => [day, 1]),
      }));
      return {
        animation: false,
        tooltip: {
          ...tooltipStyle(colors), trigger: "item",
          formatter: (item) => {
            const day = item.data[0];
            const row = days.get(day);
            const names = spikesOn(day).map((spike) => escapeHtml(humanize(spike.subcategory)));
            return `${escapeHtml(formatDay(day))}<br><b>${formatInteger(row.tickets)}</b> tickets`
              + (names.length ? `<br>Spike: ${names.join(", ")}` : "");
          },
        },
        visualMap: {
          seriesIndex: years.map((_, i) => i), min: 0, max: mostTickets, orient: "horizontal", left: 48, bottom: 0,
          itemWidth: 12, itemHeight: 140, calculable: false, text: [formatInteger(mostTickets), "0"],
          textStyle: { color: colors.muted, fontSize: 12 },
          // One hue, light to dark, because the colour shows how many.
          inRange: { color: [colors.surface2, colors.accent] },
        },
        calendar: years.map((year, i) => ({
          range: year, left: 48, right: 16, top: 24 + i * (7 * CELL_HEIGHT + YEAR_GAP), cellSize: ["auto", CELL_HEIGHT],
          splitLine: { show: false },
          itemStyle: { color: colors.surface2, borderColor: colors.surface, borderWidth: 2 },
          dayLabel: { firstDay: 1, nameMap: ["S", "M", "T", "W", "T", "F", "S"], color: colors.muted, fontSize: 11 },
          monthLabel: { color: colors.muted, fontSize: 12 },
          yearLabel: { color: colors.text, fontSize: 13, fontWeight: 600, margin: 28 },
        })),
        series: [
          ...years.map((year, calendarIndex) => ({
            type: "heatmap", coordinateSystem: "calendar", calendarIndex,
            data: daily.filter(inYear(year)).map((row) => [row.day, row.tickets]),
          })),
          ...marks("recurring", { color: "transparent", borderColor: colors.text, borderWidth: 1.5 }, 8),
          // Incidents second, so they stay on top on a day that has both.
          ...marks("one_off", { color: colors.risk.high, borderColor: colors.surface, borderWidth: 2 }, 11),
          {
            type: "scatter", coordinateSystem: "calendar", silent: true, symbol: "rect", symbolSize: CELL_HEIGHT,
            calendarIndex: years.indexOf(selected.slice(0, 4)),
            itemStyle: { color: "transparent", borderColor: colors.text, borderWidth: 2 },
            data: [[selected, 1]],
          },
        ],
      };
    });
    fillTable(calendarCard.table, "Tickets per day", ["Day", "Tickets", "Breach rate"],
      daily.map((row) => [formatDay(row.day), formatInteger(row.tickets), formatPercent(row.breach_rate_pct)]));
    charts.calendar.instance.off("click");
    charts.calendar.instance.on("click", (item) => select(item.data[0]));
  }

  dayInput.addEventListener("change", () => select(dayInput.value));
  // Open on the requested day, or else the latest suspected incident.
  const requested = params.get("day");
  select(days.has(requested) ? requested : incidents.at(-1)?.start ?? last);
  return () => Object.values(charts).forEach((chart) => chart.dispose());
}

function episodeDates(episode) {
  return episode.start === episode.end
    ? formatDay(episode.start)
    : `${formatShortDay(episode.start)} to ${formatDay(episode.end)}`;
}

const typicalLabel = (value) => (value < 1 ? "fewer than 1" : formatInteger(value));
