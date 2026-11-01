// The two pieces that show a prediction, shared by the risk simulator and
// the ticket lookup: the risk card (headline, flag, meter against the review
// threshold) and the reasons card (the features that moved the risk most).

import { fillTable } from "./charts.js";
import { el, replaceChildren } from "./dom.js";
import { featureLabel, featureValue } from "./features.js";

// Reason bars share a fixed scale, so bars stay comparable between tickets
// and while the simulator's slider moves, unless a contribution is larger.
const REASON_SCALE = 3;

// A model's probability is never exactly 0 or 1, so the extremes are shown as
// "<1%" and ">99%" rather than rounded to 0% and 100%.
export function percentLabel(probability) {
  if (probability < 0.005) return "<1%";
  if (probability > 0.995) return ">99%";
  return `${Math.round(probability * 100)}%`;
}

export function riskCard(threshold, title = "Chance of missing the SLA") {
  const value = el("p", { class: "stat-value" });
  const badge = el("span", { class: "badge risk-badge" });
  const fill = el("div", { class: "meter-fill" });
  const extra = el("div", { class: "risk-extra" });
  const root = el("section", { class: "card risk-card", "aria-live": "polite" },
    el("h2", { class: "stat-label" }, title),
    el("div", { class: "risk-headline" }, value, badge),
    el("div", { class: "meter", "aria-hidden": "true" },
      fill,
      el("div", { class: "meter-threshold", style: `left: ${threshold * 100}%` })),
    el("div", { class: "meter-scale", "aria-hidden": "true" },
      el("span", {}, "0%"),
      el("span", { class: "meter-threshold-label", style: `left: ${threshold * 100}%` },
        `Review threshold ${percentLabel(threshold)}`),
      el("span", {}, "100%")),
    el("p", { class: "stat-note" },
      `Tickets at or above ${percentLabel(threshold)} are flagged for review. The threshold was chosen so that `
      + "about 10% of tickets are flagged, the review capacity the desk has."),
    extra);

  return {
    root,
    extra,  // room for page-specific notes, such as the known outcome
    show(risk, flagged) {
      value.textContent = percentLabel(risk);
      badge.textContent = flagged ? "Flagged for review" : "Below the review threshold";
      root.dataset.flagged = String(flagged);
      fill.style.width = `${risk * 100}%`;
    },
  };
}

export function reasonsCard() {
  const list = el("ol", { class: "reason-list" });
  const inputs = el("details", { class: "table-view" });
  const root = el("section", { class: "card" },
    el("header", { class: "chart-header" },
      el("h2", {}, "Why"),
      el("p", {}, "The three features that moved this ticket's risk the most, measured in log-odds (SHAP values). "
        + "They show what the model relies on, not what causes breaches.")),
    list, inputs);

  return {
    root,
    show(prediction) {
      replaceChildren(list, prediction.reasons.map(reasonRow));
      fillTable(inputs, "Every value the model received for this ticket", ["Feature", "Value"],
        Object.entries(prediction.inputs).map(([name, value]) => [featureLabel(name), featureValue(name, value)]));
      inputs.querySelector("summary").textContent = "Show everything the model saw";
    },
  };
}

function reasonRow(reason) {
  const size = Math.abs(reason.contribution);
  const width = (size / Math.max(REASON_SCALE, size)) * 50;
  const raises = reason.contribution > 0;
  return el("li", { class: "reason", dataset: { direction: raises ? "up" : "down" } },
    el("div", { class: "reason-text" },
      el("span", { class: "reason-name" }, featureLabel(reason.feature)),
      el("span", { class: "reason-value" }, featureValue(reason.feature, reason.value))),
    el("div", { class: "reason-bar", "aria-hidden": "true" },
      el("span", { class: "reason-fill", style: raises ? `left: 50%; width: ${width}%` : `right: 50%; width: ${width}%` })),
    el("span", { class: "reason-amount" }, `${raises ? "Raises" : "Lowers"} risk, ${raises ? "+" : "−"}${size.toFixed(2)}`));
}
