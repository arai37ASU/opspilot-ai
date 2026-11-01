// ECharts wrapper shared by every page.
//
// Colours are read from the CSS variables in app.css, so charts always match
// the current theme, and every chart redraws when the theme changes or its
// card is resized. Mark specs follow the project's chart rules: thin marks,
// 4px rounded data ends, 2px lines, 8px markers with a surface ring,
// hairline recessive grid, text in text colours (never the series colour).

import { el, replaceChildren } from "./dom.js";
import { onThemeChange } from "./theme.js";

export function themeColors() {
  const style = getComputedStyle(document.documentElement);
  const read = (name) => style.getPropertyValue(name).trim();
  return {
    text: read("--text"),
    muted: read("--text-muted"),
    border: read("--border"),
    surface: read("--surface"),
    surface2: read("--surface-2"),
    accent: read("--accent"),
    risk: { low: read("--risk-low"), medium: read("--risk-medium"), high: read("--risk-high") },
    font: read("--font"),
  };
}

// ECharts builds tooltip text as HTML, so any value that came from the API is
// escaped before it goes into a tooltip.
export function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
}

// Pieces most charts share.
export function axisStyle(colors) {
  return {
    axisLine: { lineStyle: { color: colors.border, width: 1 } },
    axisTick: { show: false },
    axisLabel: { color: colors.muted, fontSize: 12 },
    splitLine: { lineStyle: { color: colors.border, width: 1, type: "solid" } },
  };
}

export function tooltipStyle(colors) {
  return {
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
    padding: [8, 12],
    textStyle: { color: colors.text, fontSize: 13, fontFamily: colors.font },
    extraCssText: "border-radius: 8px; box-shadow: 0 4px 16px rgb(0 0 0 / 0.12);",
  };
}

// The same left and right padding on every time chart, so stacked charts line up.
export const TIME_GRID = { left: 56, right: 64, top: 16, bottom: 32, containLabel: false };

/**
 * Draw a chart into `container` and keep it in sync with theme and size.
 * `build(colors)` returns an ECharts option. Returns update(), dispose(), and
 * the ECharts instance for pages that need its events.
 */
export function mountChart(container, build) {
  const chart = window.echarts.init(container, null, { renderer: "svg" });
  let currentBuild = build;
  const draw = () => {
    const colors = themeColors();
    chart.setOption({ textStyle: { fontFamily: colors.font }, animationDuration: 500, ...currentBuild(colors) }, true);
  };
  draw();

  const resize = new ResizeObserver(() => chart.resize());
  resize.observe(container);
  // Wait a frame so the new theme's CSS variables are in effect before redrawing.
  const stopListening = onThemeChange(() => requestAnimationFrame(draw));

  return {
    instance: chart,
    update(nextBuild) {
      currentBuild = nextBuild;
      draw();
    },
    dispose() {
      resize.disconnect();
      stopListening();
      chart.dispose();
    },
  };
}

// ---- Chart cards -------------------------------------------------------------

export function chartCard(title, description) {
  const chart = el("div", { class: "chart", role: "img" });
  const table = el("details", { class: "table-view" });
  const root = el("section", { class: "card chart-card" },
    el("header", { class: "chart-header" }, el("h2", {}, title), el("p", {}, description)),
    chart, table);
  return { root, chart, table };
}

// Every chart has a table twin, so no value is reachable only by hovering.
export function fillTable(details, caption, headers, rows) {
  replaceChildren(details,
    el("summary", {}, "Show as table"),
    el("div", { class: "table-scroll" }, dataTable(caption, headers, rows)));
}

// A plain table: the first cell of each row is its header.
export function dataTable(caption, headers, rows) {
  return el("table", { class: "data-table" },
    el("caption", {}, caption),
    el("thead", {}, el("tr", {}, headers.map((header) => el("th", { scope: "col" }, header)))),
    el("tbody", {}, rows.map((row) => el("tr", {}, row.map((cell, i) =>
      i === 0 ? el("th", { scope: "row" }, cell) : el("td", {}, cell))))));
}

// Draw into a card, reusing its chart if one is already mounted.
export function drawChart(charts, key, card, build) {
  if (charts[key]) charts[key].update(build);
  else charts[key] = mountChart(card.chart, build);
}
