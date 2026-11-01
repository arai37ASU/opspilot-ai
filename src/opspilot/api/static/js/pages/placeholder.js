// Shared layout for pages that are not built yet, so each says what it will
// show instead of looking broken. Removed as each page is built.

import { el, pageHeader } from "../dom.js";

export function renderPlaceholder(container, { title, description, step, features }) {
  container.append(
    pageHeader(title, description),
    el("section", { class: "card coming-soon" },
      el("span", { class: "badge" }, `Coming in Phase 7 step ${step}`),
      el("ul", {}, features.map((feature) => el("li", {}, feature)))),
  );
}
