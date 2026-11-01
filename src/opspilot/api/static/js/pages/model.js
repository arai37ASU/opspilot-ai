// The model: how the deployed model did on the held-out test period, compared
// with simpler baselines, and what it relies on.
//
// Every number is from /model/evaluation, which serves the reports saved by
// the single test evaluation. Nothing is recomputed in the browser.

import { getJSON } from "../api.js";
import { axisStyle, chartCard, dataTable, drawChart, escapeHtml, fillTable, tooltipStyle } from "../charts.js";
import { el, pageHeader } from "../dom.js";
import { featureLabel } from "../features.js";
import { formatDay, formatInteger, formatMonth } from "../format.js";

const REPOSITORY = "https://github.com/arai37ASU/opspilot-ai";
const TOP_FEATURES = 10;

const pct = (value, digits = 0) => `${(value * 100).toFixed(digits)}%`;
const interval = ([low, high], format) => `95% interval ${format(low)} to ${format(high)}`;
const score = (value) => value.toFixed(2);

export async function render(container) {
  const evaluation = await getJSON("/model/evaluation");
  const counts = evaluation.at_threshold;
  const flagged = counts.true_positives + counts.false_positives;
  const breaches = counts.true_positives + counts.false_negatives;

  const comparisonCard = chartCard("Against simpler approaches",
    "Average precision on the same test tickets. A model that guesses scores the breach rate, "
    + `${pct(evaluation.base_rate, 1)}; 1.0 is perfect.`);
  const capacityCard = chartCard("The review-capacity trade-off",
    "Reviewing more tickets catches more breaches but more of the reviews are wasted. "
    + "From the validation folds, where the threshold was chosen.");
  const calibrationCard = chartCard("Calibration",
    "Test tickets in ten equal-size groups by predicted risk. Points on the dashed line mean a predicted 30% "
    + "really breaches about 30% of the time.");
  const importanceCard = chartCard("What the model relies on",
    `The ${TOP_FEATURES} features that move predictions the most on test tickets (mean absolute SHAP value). `
    + "Correlated features share credit, and none of this is causal.");

  container.append(
    pageHeader("The model", "How well the SLA breach model works on tickets it never saw, and where it falls short."),
    el("div", { class: "page-body" },
      el("section", { class: "kpi-row", "aria-label": "Headline results" },
        el("article", { class: "stat stat-hero" },
          el("h2", { class: "stat-label" }, "Flagged tickets that really breached"),
          el("p", { class: "stat-value" }, pct(counts.precision)),
          el("p", { class: "stat-note" },
            `${formatInteger(counts.true_positives)} of ${formatInteger(flagged)} flagged test tickets missed their SLA, `
            + `against ${pct(evaluation.base_rate)} of all tickets. `
            + interval(evaluation.intervals_95.precision_at_threshold, pct) + ".")),
        stat("Breaches caught", pct(counts.recall),
          `${formatInteger(counts.true_positives)} of ${formatInteger(breaches)}, reviewing ${pct(counts.share_flagged)} of tickets`),
        stat("Average precision", score(evaluation.average_precision),
          interval(evaluation.intervals_95.average_precision, score)),
        stat("ROC AUC", score(evaluation.roc_auc), interval(evaluation.intervals_95.roc_auc, score)),
        stat("Calibration error", evaluation.expected_calibration_error.toFixed(3),
          "Average gap between predicted and observed breach rates")),
      outcomesCard(evaluation),
      el("div", { class: "chart-grid" },
        comparisonCard.root, capacityCard.root, calibrationCard.root, importanceCard.root),
      groupsCard(evaluation),
      provenanceCard(evaluation)));

  const charts = {};
  drawComparison(charts, comparisonCard, evaluation.comparison);
  drawCapacity(charts, capacityCard, evaluation.capacity_curve, counts.share_flagged);
  drawCalibration(charts, calibrationCard, evaluation.calibration);
  importanceCard.chart.classList.add("chart-tall");
  drawImportance(charts, importanceCard, evaluation.feature_importance);
  return () => Object.values(charts).forEach((chart) => chart.dispose());
}

function stat(label, value, note) {
  return el("article", { class: "stat" },
    el("h2", { class: "stat-label" }, label),
    el("p", { class: "stat-value" }, value),
    el("p", { class: "stat-note" }, note));
}

// ---- What happened to every test ticket --------------------------------------

function outcomesCard(evaluation) {
  const c = evaluation.at_threshold;
  const cell = (count, label, kind) => el("td", { class: "outcome", dataset: { kind } },
    el("span", { class: "outcome-count" }, formatInteger(count)),
    el("span", { class: "outcome-label" }, label));
  return el("section", { class: "card" },
    el("header", { class: "chart-header" },
      el("h2", {}, `What happened to the ${formatInteger(evaluation.test_tickets)} test tickets`),
      el("p", {}, `Tickets created ${formatDay(evaluation.test_period[0].slice(0, 10))} to `
        + `${formatDay(evaluation.test_period[1].slice(0, 10))}, scored once with the final model and threshold.`)),
    el("div", { class: "table-scroll" },
      el("table", { class: "outcomes" },
        el("caption", {}, "Flag decision against the real outcome"),
        el("thead", {}, el("tr", {}, el("td", {}),
          el("th", { scope: "col" }, "Missed its SLA"), el("th", { scope: "col" }, "Met its SLA"))),
        el("tbody", {},
          el("tr", {}, el("th", { scope: "row" }, "Flagged"),
            cell(c.true_positives, "Caught breaches", "good"), cell(c.false_positives, "False alarms", "cost")),
          el("tr", {}, el("th", { scope: "row" }, "Not flagged"),
            cell(c.false_negatives, "Missed breaches", "cost"), cell(c.true_negatives, "Correctly left alone", "good"))))),
    el("p", { class: "chart-note" },
      "More than half of breaches are not flagged. With review capacity for about 10% of tickets, the model "
      + "spends it on the clearest cases; the breaches it misses had lower predicted risk when they arrived."));
}

// ---- Charts ------------------------------------------------------------------

function drawComparison(charts, card, rows) {
  card.chart.setAttribute("aria-label", "Bar chart of average precision for the deployed model and three baselines. The same values are in the table below.");
  drawChart(charts, "comparison", card, (colors) => ({
    grid: { left: 24, right: 56, top: 4, bottom: 4, containLabel: true },
    tooltip: {
      ...tooltipStyle(colors), trigger: "item",
      formatter: (item) => {
        const row = rows[item.dataIndex];
        return `${escapeHtml(row.name)}<br>Average precision <b>${score(row.average_precision)}</b>`
          + `<br>ROC AUC ${score(row.roc_auc)}<br>Brier score ${row.brier.toFixed(3)}`;
      },
    },
    xAxis: { type: "value", min: 0, max: 1, show: false },
    yAxis: { type: "category", inverse: true, data: rows.map((row) => row.name), ...axisStyle(colors), axisLine: { show: false },
             axisLabel: { ...axisStyle(colors).axisLabel, width: 170, overflow: "truncate" } },
    series: [{
      type: "bar",
      barMaxWidth: 20,
      // The deployed model in the accent; baselines step back.
      data: rows.map((row) => ({
        value: row.average_precision,
        itemStyle: { color: row.selected ? colors.accent : colors.muted, opacity: row.selected ? 1 : 0.45, borderRadius: [0, 4, 4, 0] },
      })),
      label: { show: true, position: "right", color: colors.text, fontWeight: 600, formatter: (item) => score(item.value) },
    }],
  }));
  fillTable(card.table, "Scores on the test tickets", ["Model", "Average precision", "ROC AUC", "Brier score"],
    rows.map((row) => [row.name, score(row.average_precision), score(row.roc_auc), row.brier.toFixed(3)]));
}

function drawCapacity(charts, card, points, currentShare) {
  const labels = points.map((p) => pct(p.review_share));
  const current = points.findIndex((p) => Math.abs(p.review_share - currentShare) < 0.01);
  const lastIndex = points.length - 1;
  card.chart.setAttribute("aria-label", "Line chart of precision and recall for each review share. The same values are in the table below.");
  drawChart(charts, "capacity", card, (colors) => {
    // Precision solid, recall dashed, both named at their line ends: the two
    // lines differ in more than colour.
    const line = (name, key, color, type) => ({
      name, type: "line", data: points.map((p) => [p.review_share * 100, p[key] * 100]),
      lineStyle: { color, width: 2, type },
      itemStyle: { color, borderColor: colors.surface, borderWidth: 2 },
      symbol: "circle", symbolSize: 8,
      label: { show: true, position: "right", color: colors.text, formatter: (item) => (item.dataIndex === lastIndex ? name : "") },
    });
    return {
      grid: { left: 48, right: 80, top: 32, bottom: 40 },
      legend: { top: 0, right: 0, icon: "roundRect", itemWidth: 14, itemHeight: 3, textStyle: { color: colors.text } },
      tooltip: {
        ...tooltipStyle(colors), trigger: "axis",
        axisPointer: { type: "line", lineStyle: { color: colors.muted, width: 1 } },
        formatter: (items) => `Review ${escapeHtml(labels[items[0].dataIndex])} of tickets<br>`
          + items.map((item) => `${item.seriesName} <b>${item.value[1].toFixed(0)}%</b>`).join("<br>"),
      },
      // A value axis, so 20% to 30% takes twice the room of 5% to 10%.
      xAxis: { type: "value", min: 0, max: 30, interval: 5, name: "Share of tickets reviewed", nameLocation: "middle",
               nameGap: 26, nameTextStyle: { color: colors.muted }, ...axisStyle(colors), splitLine: { show: false },
               axisLabel: { ...axisStyle(colors).axisLabel, formatter: (v) => `${v}%` } },
      yAxis: { type: "value", min: 0, max: 100, ...axisStyle(colors),
               axisLabel: { ...axisStyle(colors).axisLabel, formatter: (v) => `${v}%` } },
      series: [
        {
          ...line("Precision", "precision", colors.accent, "solid"),
          markLine: current < 0 ? undefined : {
            silent: true, symbol: "none", animation: false,
            lineStyle: { color: colors.text, opacity: 0.35, type: "solid", width: 1 },
            label: { formatter: `Chosen: ${pct(currentShare)}`, position: "end", color: colors.text, fontWeight: 600 },
            data: [{ xAxis: points[current].review_share * 100 }],
          },
        },
        line("Recall", "recall", colors.muted, "dashed"),
      ],
    };
  });
  fillTable(card.table, "Precision and recall by review share (validation folds)", ["Reviewed", "Threshold", "Precision", "Recall"],
    points.map((p) => [pct(p.review_share), pct(p.threshold, 1), pct(p.precision, 1), pct(p.recall, 1)]));
}

function drawCalibration(charts, card, bands) {
  card.chart.setAttribute("aria-label", "Scatter chart of observed against predicted breach rate for ten risk groups. The same values are in the table below.");
  drawChart(charts, "calibration", card, (colors) => ({
    grid: { left: 48, right: 24, top: 16, bottom: 40 },
    tooltip: {
      ...tooltipStyle(colors), trigger: "item",
      formatter: (item) => {
        if (item.seriesIndex !== 0) return "";
        const band = bands[item.dataIndex];
        return `Group ${band.band + 1} of 10, ${formatInteger(band.n)} tickets<br>Predicted <b>${pct(band.mean_predicted, 1)}</b>`
          + `<br>Observed <b>${pct(band.observed_rate, 1)}</b>`;
      },
    },
    xAxis: { type: "value", min: 0, max: 100, name: "Predicted breach rate", nameLocation: "middle", nameGap: 26,
             nameTextStyle: { color: colors.muted }, ...axisStyle(colors), axisLabel: { ...axisStyle(colors).axisLabel, formatter: (v) => `${v}%` } },
    yAxis: { type: "value", min: 0, max: 100, ...axisStyle(colors), axisLabel: { ...axisStyle(colors).axisLabel, formatter: (v) => `${v}%` } },
    series: [
      {
        type: "line",
        data: bands.map((band) => [band.mean_predicted * 100, band.observed_rate * 100]),
        lineStyle: { color: colors.accent, width: 2 },
        itemStyle: { color: colors.accent, borderColor: colors.surface, borderWidth: 2 },
        symbol: "circle", symbolSize: 9,
      },
      {
        type: "line", silent: true, symbol: "none", data: [[0, 0], [100, 100]],
        lineStyle: { color: colors.muted, type: "dashed", width: 1 },
        endLabel: { show: true, color: colors.muted, formatter: "Perfect", offset: [-56, -12] },
      },
    ],
  }));
  fillTable(card.table, "Calibration on the test tickets", ["Group", "Tickets", "Predicted", "Observed"],
    bands.map((band) => [String(band.band + 1), formatInteger(band.n), pct(band.mean_predicted, 1), pct(band.observed_rate, 1)]));
}

function drawImportance(charts, card, features) {
  const top = features.slice(0, TOP_FEATURES);
  card.chart.setAttribute("aria-label", "Bar chart of the most influential features. The table below has all features.");
  drawChart(charts, "importance", card, (colors) => ({
    grid: { left: 24, right: 48, top: 4, bottom: 4, containLabel: true },
    tooltip: {
      ...tooltipStyle(colors), trigger: "item",
      formatter: (item) => {
        const row = top[item.dataIndex];
        return `${escapeHtml(featureLabel(row.feature))}<br>Mean |SHAP| <b>${row.mean_abs_shap.toFixed(2)}</b>`
          + `<br>Average precision drops ${row.ap_drop_mean.toFixed(3)} when shuffled`;
      },
    },
    xAxis: { type: "value", min: 0, show: false },
    yAxis: { type: "category", inverse: true, data: top.map((row) => featureLabel(row.feature)), ...axisStyle(colors),
             axisLine: { show: false }, // Half the chart, so names fit where there is room and truncate on a phone.
             axisLabel: { ...axisStyle(colors).axisLabel, width: card.chart.clientWidth / 2, overflow: "truncate" } },
    series: [{
      type: "bar", barMaxWidth: 16, data: top.map((row) => row.mean_abs_shap),
      itemStyle: { color: colors.accent, borderRadius: [0, 4, 4, 0] },
      label: { show: true, position: "right", color: colors.text, fontWeight: 600, formatter: (item) => item.value.toFixed(2) },
    }],
  }));
  fillTable(card.table, "Every feature, by mean absolute SHAP value", ["Feature", "Mean |SHAP|", "AP drop when shuffled"],
    features.map((row) => [featureLabel(row.feature), row.mean_abs_shap.toFixed(3), `${row.ap_drop_mean.toFixed(3)} ± ${row.ap_drop_std.toFixed(3)}`]));
}

// ---- By team and month, and where the numbers come from ----------------------

function groupRows(groups, label) {
  return groups.map((g) => [label(g.group), formatInteger(g.n), pct(g.base_rate, 1), score(g.average_precision),
                            pct(g.share_flagged, 1), pct(g.precision_at_threshold), pct(g.recall_at_threshold)]);
}

function groupsCard(evaluation) {
  const headers = ["", "Tickets", "Breach rate", "Avg. precision", "Flagged", "Precision", "Recall"];
  const serviceDesk = evaluation.by_team.find((g) => g.group === "Service Desk");
  return el("section", { class: "card" },
    el("header", { class: "chart-header" },
      el("h2", {}, "By team and by month"),
      el("p", {}, "The same test results split up, to check the model works for every team and does not decay over time.")),
    el("div", { class: "table-scroll" }, dataTable("By assigned team", ["Team", ...headers.slice(1)],
      groupRows(evaluation.by_team, (g) => g))),
    serviceDesk && el("p", { class: "chart-note" },
      `Service Desk's tickets breach rarely (${pct(serviceDesk.base_rate, 1)}), so few are flagged and its average `
      + "precision is the lowest. Average precision depends on how common breaches are, so compare it with the breach rate."),
    el("details", { class: "table-view" },
      el("summary", {}, "Show by month"),
      el("div", { class: "table-scroll" }, dataTable("By month created", ["Month", ...headers.slice(1)],
        groupRows(evaluation.by_month, (g) => formatMonth(`${g}-01`))))));
}

function provenanceCard(evaluation) {
  const short = evaluation.commit.slice(0, 7);
  const versions = Object.entries(evaluation.versions).map(([name, version]) => `${name} ${version}`).join(", ");
  const facts = [
    ["Model", `${evaluation.model}, threshold ${pct(evaluation.threshold, 1)}`],
    ["Trained on", `${formatInteger(evaluation.train_tickets)} tickets, ${formatDay(evaluation.train_period[0].slice(0, 10))} `
      + `to ${formatDay(evaluation.train_period[1].slice(0, 10))}`],
    ["Tested on", `${formatInteger(evaluation.test_tickets)} tickets, ${formatDay(evaluation.test_period[0].slice(0, 10))} `
      + `to ${formatDay(evaluation.test_period[1].slice(0, 10))}, evaluated once`],
    ["Evaluated", formatDay(evaluation.evaluated_at.slice(0, 10))],
    ["Code", el("a", { href: `${REPOSITORY}/commit/${evaluation.commit}`, target: "_blank", rel: "noopener" }, `commit ${short}`)],
    ["Libraries", versions],
  ];
  return el("section", { class: "card" },
    el("h2", {}, "Where these numbers come from"),
    el("dl", { class: "facts" }, facts.flatMap(([label, value]) => [el("dt", {}, label), el("dd", {}, value)])),
    el("p", { class: "field-note" },
      "The model card in the repository explains the data, the selection rule, the threshold and the known limitations."));
}
