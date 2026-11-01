// The "Explain in plain language" panel, shared by the risk simulator and the
// ticket lookup. Each click spends money on the Claude API, so nothing is
// requested until someone asks. The numbers shown beside each note come from
// the model; only the sentences are written by Claude, and the API has already
// checked them.

import { ApiError } from "./api.js";
import { el, replaceChildren } from "./dom.js";

export function explanationPanel(requestExplanation) {
  const button = el("button", { type: "button", class: "button button-secondary", onclick: () => load() }, "Explain in plain language");
  const body = el("div", { class: "explanation-body", "aria-live": "polite" });
  const root = el("div", { class: "explanation" }, button, body);
  let request = 0;

  async function load() {
    const current = ++request;
    button.disabled = true;
    replaceChildren(body, el("p", { class: "field-note" }, "Writing the explanation…"));
    try {
      const explanation = await requestExplanation();
      if (current === request) replaceChildren(body, ...explanationText(explanation));
    } catch (error) {
      if (current === request) replaceChildren(body, el("p", { class: "field-note" }, explanationError(error)));
    } finally {
      if (current === request) button.disabled = false;
    }
  }

  return {
    root,
    // The ticket changed, so an explanation on screen no longer describes it.
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

function explanationError(error) {
  return error instanceof ApiError ? error.message : "The explanation could not be loaded.";
}
