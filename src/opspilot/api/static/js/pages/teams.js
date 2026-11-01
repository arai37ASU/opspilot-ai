// Teams: how each support team is doing for one date range.
//
// Three small bar charts share one team order (worst breach rate first), so a
// team can be followed across them. Clicking a team highlights it in all
// three. A sortable scorecard below has every number.

import { getJSON } from "../api.js";
import { axisStyle, chartCard, drawChart, escapeHtml, tooltipStyle } from "../charts.js";
import { el, pageHeader, replaceChildren } from "../dom.js";
import { dateRangeFilter } from "../filters.js";
import { formatDay, formatHours, formatInteger, formatPercent } from "../format.js";

const MEASURES = [
  { key: "breach_rate_pct", title: "SLA breach rate", description: "Share of resolved tickets that missed their target.",
    format: (v) => formatPercent(v) },
  { key: "median_resolution_hours", title: "Median resolution time", description: "Half of resolved tickets took longer.",
    format: (v) => formatHours(v) },
  { key: "misrouted_pct", title: "Misrouted on arrival", description: "Tickets first assigned here that belonged to another team.",
    format: (v) => formatPercent(v) },
];

const COLUMNS = [
  { key: "team", label: "Team", format: (v) => v },
  { key: "tickets", label: "Tickets", format: formatInteger },
  { key: "resolved", label: "Resolved", format: formatInteger },
  { key: "breach_rate_pct", label: "Breach rate", format: (v) => formatPercent(v) },
  { key: "median_resolution_hours", label: "Median resolution", format: formatHours },
  { key: "misrouted_pct", label: "Misrouted", format: (v) => formatPercent(v) },
  { key: "agents", label: "Agents today", format: formatInteger },
];

export async function render(container, params) {
  const reference = await getJSON("/reference");
  const { start: first, end: last } = reference.date_range;
  const range = { start: params.get("start") || first, end: params.get("end") || last };

  const status = el("p", { class: "load-status", role: "status", "aria-live": "polite" });
  const filter = dateRangeFilter({
    page: "teams", first, last, range, onChange: () => load(),
    onInvalid: (message) => { status.textContent = message; },
  });

  const cards = MEASURES.map((measure) => chartCard(measure.title, measure.description));
  const selection = el("p", { class: "chart-summary" });
  const scorecard = el("div", { class: "table-scroll scorecard" });
  const body = el("div", { class: "page-body" },
    el("div", { class: "small-multiples" }, cards.map((card) => card.root)),
    selection,
    el("section", { class: "card" },
      el("header", { class: "chart-header" },
        el("h2", {}, "Scorecard"),
        el("p", {}, "Every number for the selected period. Select a column heading to sort.")),
      scorecard,
      el("p", { class: "chart-note" },
        "Agents is today's headcount from the teams table. Past staffing changes, such as Desktop Support's "
        + "reduction in April–June 2025, are not recorded, so tickets per agent for a past period would be misleading.")));

  container.append(
    pageHeader("Teams", "Breach rate, resolution time and misrouting for each support team, for any period."),
    filter.root, status, body);

  const charts = {};
  let teams = [];
  let highlighted = null;
  let sort = { key: "breach_rate_pct", descending: true };

  async function load() {
    body.classList.add("is-loading");
    status.textContent = "Loading…";
    try {
      const result = await getJSON(`/metrics/teams?start=${range.start}&end=${range.end}`);
      // One shared order for all three charts: worst breach rate first.
      teams = [...result.teams].sort((a, b) => (b.breach_rate_pct ?? -1) - (a.breach_rate_pct ?? -1));
      if (!teams.some((team) => team.team === highlighted)) highlighted = null;
      drawAll();
      status.textContent = `Showing ${formatDay(range.start)} to ${formatDay(range.end)}.`;
    } catch (error) {
      status.textContent = `Could not load the data: ${error.message}`;
    } finally {
      body.classList.remove("is-loading");
    }
  }

  function drawAll() {
    MEASURES.forEach((measure, i) => drawMeasure(charts, measure, cards[i], teams, highlighted, toggleTeam));
    selection.textContent = highlighted
      ? `${highlighted} is highlighted. Select it again to clear.`
      : "Select a team in any chart to highlight it in all three.";
    renderScorecard();
  }

  function toggleTeam(team) {
    highlighted = highlighted === team ? null : team;
    drawAll();
  }

  function renderScorecard() {
    const rows = [...teams].sort((a, b) => compare(a[sort.key], b[sort.key]) * (sort.descending ? -1 : 1));
    replaceChildren(scorecard, el("table", { class: "data-table" },
      el("caption", {}, `Teams, ${formatDay(range.start)} to ${formatDay(range.end)}`),
      el("thead", {}, el("tr", {}, COLUMNS.map((column) => el("th", {
        scope: "col",
        "aria-sort": column.key === sort.key ? (sort.descending ? "descending" : "ascending") : null,
      }, el("button", {
        type: "button", class: "sort-button",
        onclick: () => {
          sort = { key: column.key, descending: column.key === sort.key ? !sort.descending : column.key !== "team" };
          renderScorecard();
        },
      }, column.label, column.key === sort.key ? (sort.descending ? " ↓" : " ↑") : ""))))),
      el("tbody", {}, rows.map((team) => el("tr", { class: team.team === highlighted ? "is-highlighted" : null },
        COLUMNS.map((column, i) => i === 0
          ? el("th", { scope: "row" }, team.team)
          : el("td", {}, column.format(team[column.key]))))))));
  }

  await load();
  return () => Object.values(charts).forEach((chart) => chart.dispose());
}

function compare(a, b) {
  if (a === b) return 0;
  if (a === null || a === undefined) return -1;
  if (b === null || b === undefined) return 1;
  return typeof a === "string" ? a.localeCompare(b) : a - b;
}

function drawMeasure(charts, measure, card, teams, highlighted, onSelect) {
  card.chart.setAttribute("aria-label", `Bar chart of ${measure.title.toLowerCase()} by team. The scorecard below has the same values.`);
  // The scorecard is this chart's table view.
  card.table.remove();
  drawChart(charts, measure.key, card, (colors) => ({
    grid: { left: 8, right: 64, top: 4, bottom: 4, containLabel: true },
    tooltip: {
      ...tooltipStyle(colors), trigger: "item",
      formatter: (item) => {
        const team = teams[item.dataIndex];
        return `${escapeHtml(team.team)}<br><b>${measure.format(team[measure.key])}</b><br>${formatInteger(team.resolved)} resolved tickets`;
      },
    },
    xAxis: { type: "value", min: 0, show: false },
    yAxis: {
      type: "category", inverse: true, data: teams.map((team) => team.team), ...axisStyle(colors),
      axisLine: { show: false },
      axisLabel: { ...axisStyle(colors).axisLabel, width: 150, overflow: "truncate" },
    },
    series: [{
      type: "bar",
      data: teams.map((team) => ({
        value: team[measure.key],
        // With a team highlighted, the others step back so it stands out.
        itemStyle: { color: colors.accent, opacity: highlighted && team.team !== highlighted ? 0.3 : 1 },
      })),
      barMaxWidth: 18,
      itemStyle: { borderRadius: [0, 4, 4, 0] },
      label: { show: true, position: "right", color: colors.text, fontWeight: 600, formatter: (item) => measure.format(item.value) },
      cursor: "pointer",
    }],
  }));
  const chart = charts[measure.key].instance;
  chart.off("click");
  chart.on("click", (item) => onSelect(teams[item.dataIndex].team));
}
