// The date-range filter row shared by the Overview and Teams pages: preset
// buttons plus From/To dates. The chosen range is kept in the page's link
// (#/teams?start=…&end=…), so a filtered view can be shared.

import { el, replaceChildren } from "./dom.js";

export function rangePresets(first, last) {
  return [
    { label: "All data", start: first, end: last },
    { label: "2025", start: "2025-01-01", end: "2025-12-31" },
    { label: "2024", start: "2024-01-01", end: "2024-12-31" },
    { label: "Sep–Dec 2025", start: "2025-09-01", end: "2025-12-31" },
    { label: "Last 90 days", start: "2025-10-03", end: last },
  ];
}

/**
 * Build the filter row. `range` ({start, end}) is updated in place, then
 * onChange() runs; onInvalid(message) runs for a reversed range.
 */
export function dateRangeFilter({ page, first, last, range, onChange, onInvalid }) {
  const presetButtons = el("div", { class: "preset-group", role: "group", "aria-label": "Date range presets" });
  const startInput = el("input", { type: "date", id: "range-start", min: first, max: last });
  const endInput = el("input", { type: "date", id: "range-end", min: first, max: last });
  const root = el("form", { class: "filter-row", "aria-label": "Date range" },
    presetButtons,
    el("div", { class: "date-fields" },
      el("label", { for: "range-start" }, "From"), startInput,
      el("label", { for: "range-end" }, "To"), endInput));

  function sync() {
    startInput.value = range.start;
    endInput.value = range.end;
    replaceChildren(presetButtons, rangePresets(first, last).map((preset) => {
      const active = preset.start === range.start && preset.end === range.end;
      return el("button", {
        type: "button", class: "preset", "aria-pressed": active ? "true" : "false",
        onclick: () => setRange(preset.start, preset.end),
      }, preset.label);
    }));
  }

  function setRange(start, end) {
    if (!start || !end || start > end) {
      onInvalid("Choose a start date on or before the end date.");
      return;
    }
    range.start = start;
    range.end = end;
    // replaceState keeps the link shareable without re-running the router.
    history.replaceState(null, "", `#/${page}?start=${start}&end=${end}`);
    sync();
    onChange();
  }

  startInput.addEventListener("change", () => setRange(startInput.value, endInput.value));
  endInput.addEventListener("change", () => setRange(startInput.value, endInput.value));
  root.addEventListener("submit", (event) => event.preventDefault());
  sync();
  return { root };
}
