// Overview: headline numbers, volume and breach rate over time, and breach
// rate by priority, all for one date range chosen in the filter row.
//
// Every number comes from the API. Volume and breach rate are two charts on
// a shared time axis rather than one chart with two y-axes, which would
// suggest a relationship the data does not show.

import { getJSON } from "../api.js";
import { TIME_GRID, axisStyle, chartCard, drawChart, escapeHtml, fillTable, tooltipStyle } from "../charts.js";
import { el, pageHeader, replaceChildren } from "../dom.js";
import { dateRangeFilter } from "../filters.js";
import {
  CENSORING_DAYS, daysBetween, formatCompact, formatDay, formatHours, formatInteger, formatMonth,
  formatPercent, formatScore, formatShortDay,
} from "../format.js";

// Ranges up to this length are shown per day; longer ones per month.
const DAILY_LIMIT_DAYS = 92;

export async function render(container, params) {
  const reference = await getJSON("/reference");
  const { start: first, end: last } = reference.date_range;
  const range = { start: params.get("start") || first, end: params.get("end") || last };

  const status = el("p", { class: "load-status", role: "status", "aria-live": "polite" });
  const filter = dateRangeFilter({
    page: "overview", first, last, range, onChange: () => load(),
    onInvalid: (message) => { status.textContent = message; },
  });

  const kpis = el("section", { class: "kpi-row", "aria-label": "Headline numbers" });
  const volumeCard = chartCard("Tickets created", "Volume over the selected period.");
  const breachCard = chartCard("SLA breach rate", "Share of resolved tickets that missed their target, on the same time axis.");
  const priorityCard = chartCard("Breach rate by priority", "Higher priorities have tighter targets, so they breach more often.");
  const body = el("div", { class: "page-body" }, kpis, volumeCard.root, breachCard.root, priorityCard.root);

  container.append(
    pageHeader("Overview", "How the service desk is doing: volume, SLA breaches and resolution times for any period."),
    filter.root, status, body);

  const charts = {};

  async function load() {
    body.classList.add("is-loading");
    status.textContent = "Loading…";
    const query = `start=${range.start}&end=${range.end}`;
    const daily = daysBetween(range.start, range.end) <= DAILY_LIMIT_DAYS;
    try {
      const [overview, series] = await Promise.all([
        getJSON(`/metrics/overview?${query}`),
        daily ? getJSON(`/metrics/daily?${query}`) : getJSON(`/metrics/trend?${query}`),
      ]);
      const points = series.map((row) => ({
        label: daily ? formatShortDay(row.day) : formatMonth(row.month),
        fullLabel: daily ? formatDay(row.day) : formatMonth(row.month),
        tickets: row.tickets,
        breach: row.breach_rate_pct,
      }));
      renderKpis(kpis, overview);
      drawVolume(charts, volumeCard, points, daily);
      drawBreach(charts, breachCard, points, daily);
      showCensoringNote(breachCard, range.end, last);
      drawPriority(charts, priorityCard, overview.by_priority);
      status.textContent = `Showing ${formatDay(range.start)} to ${formatDay(range.end)}, ${daily ? "per day" : "per month"}.`;
    } catch (error) {
      status.textContent = `Could not load the data: ${error.message}`;
    } finally {
      body.classList.remove("is-loading");
    }
  }

  await load();
  return () => Object.values(charts).forEach((chart) => chart.dispose());
}

// ---- Headline numbers ----------------------------------------------------

function renderKpis(container, overview) {
  replaceChildren(container,
    el("article", { class: "stat stat-hero" },
      el("h2", { class: "stat-label" }, "SLA breach rate"),
      el("p", { class: "stat-value" }, formatPercent(overview.breach_rate_pct)),
      el("p", { class: "stat-note" },
        `${formatInteger(overview.breached)} of ${formatInteger(overview.resolved)} resolved tickets missed their target`)),
    stat("Tickets created", formatInteger(overview.tickets), "In the selected period"),
    stat("Median resolution time", formatHours(overview.median_resolution_hours), "Resolved tickets; half took longer"),
    stat("Unresolved at snapshot", formatInteger(overview.unresolved), "Still open when the data ends, 31 Dec 2025"),
    stat("Satisfaction", overview.mean_satisfaction == null ? "—" : `${formatScore(overview.mean_satisfaction)} / 5`,
      `Survey respondents only (${formatPercent(overview.survey_response_rate_pct)} of resolved tickets)`));
}

function stat(label, value, note) {
  return el("article", { class: "stat" },
    el("h2", { class: "stat-label" }, label),
    el("p", { class: "stat-value" }, value),
    el("p", { class: "stat-note" }, note));
}

// ---- Charts ------------------------------------------------------------------

function drawVolume(charts, card, points, daily) {
  card.chart.setAttribute("aria-label", `Column chart of tickets created ${daily ? "per day" : "per month"}. The same values are in the table below.`);
  drawChart(charts, "volume", card, (colors) => ({
    grid: TIME_GRID,
    tooltip: {
      ...tooltipStyle(colors), trigger: "item",
      formatter: (item) => `${escapeHtml(points[item.dataIndex].fullLabel)}<br><b>${formatInteger(item.value)}</b> tickets`,
    },
    xAxis: { type: "category", data: points.map((p) => p.label), ...axisStyle(colors), splitLine: { show: false } },
    yAxis: { type: "value", ...axisStyle(colors), axisLabel: { ...axisStyle(colors).axisLabel, formatter: formatCompact } },
    series: [{
      type: "bar",
      data: points.map((p) => p.tickets),
      barMaxWidth: 24,
      itemStyle: { color: colors.accent, borderRadius: [4, 4, 0, 0] },
      emphasis: { itemStyle: { color: colors.accent, opacity: 0.8 } },
    }],
  }));
  fillTable(card.table, "Tickets created", [daily ? "Day" : "Month", "Tickets"],
    points.map((p) => [p.fullLabel, formatInteger(p.tickets)]));
}

function drawBreach(charts, card, points, daily) {
  const lastIndex = points.length - 1;
  card.chart.setAttribute("aria-label", `Line chart of the SLA breach rate ${daily ? "per day" : "per month"}. The same values are in the table below.`);
  drawChart(charts, "breach", card, (colors) => ({
    grid: TIME_GRID,
    tooltip: {
      ...tooltipStyle(colors), trigger: "axis",
      axisPointer: { type: "line", lineStyle: { color: colors.muted, width: 1 } },
      formatter: ([item]) => `${escapeHtml(points[item.dataIndex].fullLabel)}<br><b>${formatPercent(item.value)}</b> breached`,
    },
    xAxis: { type: "category", data: points.map((p) => p.label), boundaryGap: true, ...axisStyle(colors), splitLine: { show: false } },
    yAxis: { type: "value", min: 0, ...axisStyle(colors), axisLabel: { ...axisStyle(colors).axisLabel, formatter: (v) => `${v}%` } },
    series: [{
      type: "line",
      data: points.map((p) => p.breach),
      connectNulls: false,
      lineStyle: { color: colors.accent, width: 2, cap: "round", join: "round" },
      itemStyle: { color: colors.accent, borderColor: colors.surface, borderWidth: 2 },
      symbol: "circle",
      symbolSize: (value, item) => (item.dataIndex === lastIndex ? 9 : 0),
      showSymbol: true,
      areaStyle: { color: colors.accent, opacity: 0.08 },
      // Label only the latest value; the axis, tooltip and table carry the rest.
      label: {
        show: true, position: "right", color: colors.text, fontWeight: 600,
        formatter: (item) => (item.dataIndex === lastIndex ? formatPercent(item.value) : ""),
      },
    }],
  }));
  fillTable(card.table, "SLA breach rate", [daily ? "Day" : "Month", "Breach rate"],
    points.map((p) => [p.fullLabel, formatPercent(p.breach)]));
}

// The chart is accurate but would read as a sudden improvement without this.

function showCensoringNote(card, rangeEnd, dataEnd) {
  card.root.querySelector(".chart-note")?.remove();
  if (daysBetween(rangeEnd, dataEnd) > CENSORING_DAYS) return;
  card.chart.after(el("p", { class: "chart-note" },
    `The rate falls in the last ${CENSORING_DAYS} days because slow tickets created then were still open when the `
    + "data ends, so they are not counted yet. It is not a real improvement."));
}

function drawPriority(charts, card, byPriority) {
  card.chart.setAttribute("aria-label", "Bar chart of the SLA breach rate for each priority. The same values are in the table below.");
  drawChart(charts, "priority", card, (colors) => ({
    grid: { left: 40, right: 72, top: 8, bottom: 8, containLabel: false },
    tooltip: {
      ...tooltipStyle(colors), trigger: "item",
      formatter: (item) => {
        const row = byPriority[item.dataIndex];
        return `${escapeHtml(row.priority)}<br><b>${formatPercent(row.breach_rate_pct)}</b> breached<br>${formatInteger(row.resolved)} resolved tickets`;
      },
    },
    xAxis: { type: "value", min: 0, show: false },
    yAxis: { type: "category", inverse: true, data: byPriority.map((row) => row.priority), ...axisStyle(colors), axisLine: { show: false } },
    series: [{
      type: "bar",
      data: byPriority.map((row) => row.breach_rate_pct),
      barMaxWidth: 24,
      itemStyle: { color: colors.accent, borderRadius: [0, 4, 4, 0] },
      label: { show: true, position: "right", color: colors.text, fontWeight: 600, formatter: (item) => formatPercent(item.value) },
    }],
  }));
  fillTable(card.table, "SLA breach rate by priority", ["Priority", "Breach rate", "Resolved tickets"],
    byPriority.map((row) => [row.priority, formatPercent(row.breach_rate_pct), formatInteger(row.resolved)]));
}
