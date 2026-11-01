// The AI panels: "Explain in plain language" on the risk simulator and ticket
// lookup, and the management briefing on the overview. Each click spends money
// on the Claude API, so nothing is requested until someone asks. The API has
// already checked the text; the page only shows it.

import { ApiError } from "./api.js";
import { el, replaceChildren } from "./dom.js";

export const explanationPanel = (request) => aiPanel("Explain in plain language", "Writing the explanation…", request, explanationText);
export const briefingPanel = (request) => aiPanel("Write a management briefing", "Writing the briefing…", request, briefingText);

function aiPanel(label, waiting, requestText, render) {
  const button = el("button", { type: "button", class: "button button-secondary", onclick: () => load() }, label);
  const body = el("div", { class: "explanation-body", "aria-live": "polite" });
  const root = el("div", { class: "explanation" }, button, body);
  let request = 0;

  async function load() {
    const current = ++request;
    button.disabled = true;
    replaceChildren(body, el("p", { class: "field-note" }, waiting));
    try {
      const result = await requestText();
      if (current === request) replaceChildren(body, ...render(result));
    } catch (error) {
      if (current === request) replaceChildren(body, el("p", { class: "field-note" }, explanationError(error)));
    } finally {
      if (current === request) button.disabled = false;
    }
  }

  return {
    root,
    // The ticket or period changed, so the text on screen no longer describes it.
    reset() {
      request += 1;
      button.disabled = false;
      replaceChildren(body);
    },
  };
}

function explanationText(explanation) {
  return [
    el("p", { class: "explanation-summary" }, explanation.summary),
    el("ul", { class: "explanation-reasons" }, explanation.reasons.map((reason) => el("li", {},
      el("span", { class: "reason-name" }, `${reason.label}: ${reason.value}`),
      el("span", { class: "reason-value" }, ` (${reason.direction})`),
      el("p", { class: "field-note" }, reason.note)))),
    el("p", { class: "explanation-action" }, el("strong", {}, "Suggested next step: "), explanation.suggested_action),
    el("p", { class: "field-note" },
      `Written by ${explanation.model} from the model's output. Every number was checked against those facts. `
      + "This shows what the model relies on, not what causes breaches."),
  ];
}

const SECTION_NAMES = {
  overview: "headline metrics", by_priority: "priorities", by_team: "teams", comparison: "last year", spikes: "spikes",
};

function briefingText(briefing) {
  return [
    el("p", { class: "briefing-headline" }, briefing.headline),
    el("ul", { class: "briefing-findings" }, briefing.findings.map((finding) => el("li", {},
      el("p", { class: "explanation-summary" }, finding.text),
      el("p", { class: "field-note" }, `Based on: ${finding.sources.map((source) => SECTION_NAMES[source] ?? source).join(", ")}`)))),
    el("div", {},
      el("p", { class: "explanation-action" }, el("strong", {}, "Suggested next steps")),
      el("ul", { class: "briefing-actions" }, briefing.actions.map((action) => el("li", { class: "explanation-action" }, action)))),
    ...briefing.caveats.map((caveat) => el("p", { class: "chart-note" }, caveat)),
    el("p", { class: "field-note" },
      `Written by ${briefing.model} from the verified metrics. Every number was checked against them; `
      + "causes are not claimed, and suspected incidents are inferred from ticket data."),
  ];
}

function explanationError(error) {
  return error instanceof ApiError ? error.message : "The explanation could not be loaded.";
}
