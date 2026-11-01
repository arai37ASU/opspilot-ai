// The pill in the top bar: whether the API, its database and the model are
// available, checked when the page loads and every minute after.

import { el, replaceChildren } from "./dom.js";
import { getJSON } from "./api.js";

const INTERVAL_MS = 60_000;

async function refresh(pill) {
  try {
    const [health, model] = await Promise.all([getJSON("/health"), getJSON("/model")]);
    pill.dataset.state = health.status === "ok" ? "ok" : "down";
    replaceChildren(pill, "API live",
      el("span", { class: "status-detail" },
        ` · ${model.model} · test AP ${model.test_metrics.average_precision.toFixed(2)}`));
    pill.title = `Model evaluated from commit ${model.commit.slice(0, 7)}`;
  } catch (error) {
    pill.dataset.state = "down";
    replaceChildren(pill, error.status === 503 ? "Database unavailable" : "API unreachable");
    pill.title = error.message;
  }
}

export function initStatus(pill) {
  refresh(pill);
  setInterval(() => refresh(pill), INTERVAL_MS);
}
